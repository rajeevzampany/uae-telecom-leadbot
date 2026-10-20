"""Daily run: collect -> qualify with AI -> tag free zone -> enrich -> dedupe -> append to Google Sheet."""
import csv
import sys
from collections import Counter
from datetime import datetime

from . import config, freezones, notify, sheet, sources, state
from .enrich import enrich
from .extract import extract_leads


def tag_free_zone(lead: dict):
    """Return the Zone for a lead: AI's answer first, then keyword match on location / item text."""
    src = lead["source"]
    return (freezones.detect(lead.get("free_zone_hint", ""))
            or freezones.detect(lead["location"], src.title, src.snippet))


def build_row(today: str, lead: dict, zone) -> list[str]:
    src = lead["source"]
    location = lead["location"]
    if zone:
        if zone.code.lower() not in location.lower() and zone.name.lower() not in location.lower():
            location = f"{location} ({zone.name})" if location else f"{zone.name}, {zone.emirate}"
        source = f"Free Zone: {zone.code} via {src.channel} | {src.url} | verify: {zone.verify_url}"
    else:
        source = f"{src.channel} | {src.url}"
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
    print(f"[collect] {len(cands)} new items to review")
    expanded = sources.expand_listing_articles(cands)
    if expanded:
        print(f"[site] read {expanded} listing-site articles in full")

    leads = extract_leads(cands) if cands else []
    print(f"[ai] {len(leads)} qualified leads")

    if dry_run:
        ws, names, sites = None, set(), set()
    else:
        ws = sheet.open_worksheet()
        names, sites = sheet.existing_keys(ws)
    optouts = sheet.load_optouts()

    rows, kept = [], []
    for lead in leads:
        n = sheet.norm_name(lead["company_name"]) or lead["company_name"].lower()
        if n in names:
            continue
        lead = enrich(lead)
        s = sheet.norm_site(lead["website"])
        if s and s in sites:
            continue
        if sheet.is_opted_out(lead, optouts):
            print(f"[optout] skipped {lead['company_name']}")
            continue
        if config.REQUIRE_CONTACT and not (lead["phone"] or lead["email"]):
            continue
        names.add(n)
        if s:
            sites.add(s)
        zone = tag_free_zone(lead)
        lead["zone"] = zone
        rows.append(build_row(today, lead, zone))
        kept.append(lead)

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
        for c in cands:              # only mark items seen once the sheet write succeeded
            seen[c.key] = today
        state.save(seen)

    by_type = Counter(l["business_type"] or "other" for l in kept)
    fz = Counter(l["zone"].code for l in kept if l["zone"])
    with_contact = sum(1 for l in kept if l["phone"] or l["email"])
    summary = (f"UAE telecom leads - {today}\n"
               f"{len(rows)} new leads ({with_contact} with phone/email, {sum(fz.values())} in free zones) "
               f"from {len(cands)} items\n"
               + ", ".join(f"{k}: {v}" for k, v in by_type.most_common())
               + (("\nFree zones: " + ", ".join(f"{k}: {v}" for k, v in fz.most_common())) if fz else "")
               + "\n\n" + "\n".join(f"- {r[1]} ({r[4] or 'UAE'})" for r in rows[:15]))
    print(summary)
    if not dry_run and rows:
        notify.telegram(summary)
    return rows


if __name__ == "__main__":
    run()
