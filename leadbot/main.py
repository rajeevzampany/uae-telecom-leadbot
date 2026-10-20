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
    return [today, lead["company_name"], lead["phone"], lead["email"], location,
            lead["website"], source, zone.name if zone else ""]


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
        for r in sheet.existing_rows(ws):
            existing.add_sheet_row(r)
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

    by_type = Counter(l["business_type"] or "other" for l in kept)
    fz = Counter(l["zone"].code for l in kept if l["zone"])
    with_contact = sum(1 for l in kept if l["phone"] or l["email"])
    with_site = sum(1 for l in kept if l["website"])
    summary = (f"UAE telecom leads - {today}\n"
               f"{len(rows)} new leads ({with_contact} with phone/email, {with_site} with website, "
               f"{sum(fz.values())} in free zones) from {len(cands)} items\n"
               + ", ".join(f"{k}: {v}" for k, v in by_type.most_common())
               + (("\nFree zones: " + ", ".join(f"{k}: {v}" for k, v in fz.most_common())) if fz else "")
               + "\n\n" + "\n".join(f"- {r[1]} ({r[4] or 'UAE'})" for r in rows[:15]))
    print(summary)
    if not dry_run and rows:
        notify.telegram(summary)
    return rows


if __name__ == "__main__":
    run()
