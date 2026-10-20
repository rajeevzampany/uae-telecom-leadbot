"""Daily run: collect -> qualify with AI -> merge duplicates -> enrich -> dedupe -> Google Sheet."""
import csv
import sys
from collections import Counter
from datetime import datetime

from . import config, dedupe, freezones, notify, search, sheet, sources, state
from .enrich import enrich
from .extract import extract_leads


def tag_free_zone(lead: dict):
    """Return the Zone for a lead: AI's answer first, then keyword match on location / item text."""
    src = lead["source"]
    return (freezones.detect(lead.get("free_zone_hint", ""))
            or freezones.detect(lead["location"], src.title, src.snippet))


def build_row(today: str, lead: dict, zone) -> list[str]:
    """One sheet row in config.HEADERS order."""
    src = lead["source"]
    url = lead.get("article_url") or src.url          # publisher's real URL when found
    location = lead["location"]
    if zone:
        if zone.code.lower() not in location.lower() and zone.name.lower() not in location.lower():
            location = f"{location} ({zone.name})" if location else f"{zone.name}, {zone.emirate}"
        source = f"Free Zone: {zone.code} via {src.channel} | {url}"
    else:
        source = f"{src.channel} | {url}"
    extra = lead.get("extra_sources", [])
    if extra:
        source += f" | also in: {', '.join(dict.fromkeys(s.channel for s in extra))}"
    if zone:
        source += f" | verify: {zone.verify_url}"
    emirate = lead.get("emirate") or (zone.emirate if zone else "")
    values = {
        "DATE": today, "COMPANY NAME": lead["company_name"],
        "SECTOR": lead.get("sector") or (lead.get("business_type") or "").title(),
        "STAGE": lead.get("stage", ""), "EXPECTED OPENING": lead.get("expected_opening", ""),
        "NEW TO UAE": lead.get("new_to_uae", "Unknown"), "ORIGIN": lead.get("origin", ""),
        "EMIRATE": emirate, "LOCATION": location, "FREE ZONE": zone.name if zone else "",
        "WEBSITE": lead["website"], "CONTACT NUMBER": lead["phone"], "EMAIL": lead["email"],
        "SOURCE": source,
    }
    return [values.get(h, "") for h in config.HEADERS]


def run(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv
    now = datetime.now(config.DUBAI_TZ)
    today = now.strftime("%Y-%m-%d")
    print(f"=== UAE telecom lead bot | {now:%Y-%m-%d %H:%M} Dubai | dry_run={dry_run} ===")

    seen = state.load()
    cands = [c for c in sources.collect() if c.key not in seen][: config.MAX_CANDIDATES]
    seen_keys = [c.key for c in cands]
    print(f"[collect] {len(cands)} new items to review")
    expanded = sources.expand_listing_articles(cands)
    if expanded:
        print(f"[site] read {expanded} listing-site articles in full")

    leads = extract_leads(cands) if cands else []
    print(f"[ai] {len(leads)} qualified mentions")

    # 1) the same company found by several searches/articles -> one lead
    leads = dedupe.merge_within(leads)
    print(f"[dedupe] {len(leads)} unique companies after merging repeats")

    # 2) drop companies already in the sheet
    existing = dedupe.Index()
    ws = None
    if not dry_run:
        ws = sheet.open_worksheet()
        header, existing_values = sheet.existing_rows(ws)
        for r in existing_values:
            existing.add_sheet_row(r, header)
        before = len(leads)
        leads = [l for l in leads if existing.match(l) is None]
        print(f"[dedupe] {before - len(leads)} already in the sheet")
    optouts = sheet.load_optouts()

    # 3) enrich, then de-duplicate again on website / phone / email
    budget = search.Budget(config.MAX_LOOKUPS)
    kept, kept_idx = [], dedupe.Index()
    for lead in leads:
        lead = enrich(lead, budget)
        if existing.match(lead) is not None:
            print(f"[dedupe] {lead['company_name']} matches a sheet row after enrichment")
            continue
        m = kept_idx.match(lead)
        if m is not None:
            print(f"[dedupe] merged {lead['company_name']} into {kept[m]['company_name']}")
            dedupe.merge_into(kept[m], lead)
            continue
        if sheet.is_opted_out(lead, optouts):
            print(f"[optout] skipped {lead['company_name']}")
            continue
        if config.REQUIRE_CONTACT and not (lead["phone"] or lead["email"]):
            continue
        kept_idx.add_lead(lead, len(kept))
        kept.append(lead)
    print(f"[lookup] {config.MAX_LOOKUPS - budget.left} of {config.MAX_LOOKUPS} search lookups used")

    rows = []
    for lead in kept:
        lead["zone"] = tag_free_zone(lead)
        rows.append(build_row(today, lead, lead["zone"]))

    if dry_run:
        with open("leads_preview.csv", "w", newline="") as f:
            csv.writer(f).writerows([config.HEADERS] + rows)
        print(f"[dry-run] wrote {len(rows)} rows to leads_preview.csv")
    else:
        sheet.append(ws, rows)
        print(f"[sheet] appended {len(rows)} rows")
        expired = sheet.apply_retention(ws, now.date())
        if expired:
            print(f"[retention] deleted {expired} rows older than {config.RETENTION_DAYS} days")
        for k in seen_keys:           # only mark items seen once the sheet write succeeded
            seen[k] = today
        state.save(seen)

    by_emirate = Counter(l.get("emirate") or "Unknown" for l in kept)
    by_stage = Counter(l.get("stage") or "Unknown" for l in kept)
    fz = Counter(l["zone"].code for l in kept if l["zone"])
    new_uae = sum(1 for l in kept if l.get("new_to_uae") == "Yes")
    with_contact = sum(1 for l in kept if l["phone"] or l["email"])
    summary = (f"UAE market-entry leads - {today}\n"
               f"{len(rows)} new companies ({new_uae} new to the UAE, {sum(fz.values())} in free zones, "
               f"{with_contact} with phone/email) from {len(cands)} items\n"
               "By stage: " + ", ".join(f"{k}: {v}" for k, v in by_stage.most_common()) + "\n"
               "By emirate: " + ", ".join(f"{k}: {v}" for k, v in by_emirate.most_common())
               + (("\nFree zones: " + ", ".join(f"{k}: {v}" for k, v in fz.most_common())) if fz else "")
               + "\n\n" + "\n".join(f"- {l['company_name']} ({l.get('stage') or '?'}, {l.get('emirate') or 'UAE'})"
                                     for l in kept[:20]))
    print(summary)
    if not dry_run and rows:
        notify.telegram(summary)
    return rows


if __name__ == "__main__":
    run()
