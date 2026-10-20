# UAE Telecom Lead Bot

Every morning at **08:00 Dubai time** this bot scans news and social media for businesses
opening in the UAE, including **all major free zones**. It uses Claude to qualify them as B2B
internet/landline prospects, finds published contact details, and appends new leads to a Google Sheet:

| DATE | COMPANY NAME | CONTACT NUMBER | EMAIL | LOCATION | WEBSITE | SOURCE | FREE ZONE |
|------|--------------|----------------|-------|----------|---------|--------|-----------|

A second tab, **Free Zone Directories**, lists each free zone with its official register / directory
link so the sales team can verify a free-zone lead by hand.

## How it works

```
Time Out Dubai / Abu Dhabi feeds (full articles)        ─┐
Search API: Instagram / LinkedIn / Facebook / X / web   ├─► dedupe ─► Claude (qualify + extract + free zone)
  (35 queries incl. free-zone + Time Out site: queries)  │                │
Google News RSS (56 UAE + free-zone + Time Out queries) ─┘                │
                                                                          ▼
              tag free zone ─► enrich (item text · source article · company website, robots.txt respected)
                                    ─► dedupe vs sheet ─► opt-out check ─► Google Sheet ─► Telegram summary
```

### City guides: Time Out Dubai & Time Out Abu Dhabi
Each site is read three ways, so one blocked route doesn't lose the source:
1. the site's own RSS feed (`/feed`, `/restaurants/feed`), only if robots.txt allows;
2. Google News `site:timeoutdubai.com` / `site:timeoutabudhabi.com` searches (last 24h);
3. search-API `site:` searches.

Opening articles ("new restaurants this month", "now open", "first look") are read in full — with
robots.txt respected — so every venue in a round-up becomes its own lead; deals/brunch articles are
filtered out. SOURCE shows `Time Out Dubai | <article URL>`. Add more guides (What's On, Caterer
Middle East…) by appending to `LISTING_SITES` in `leadbot/config.py`.

### Free zones (39 covered)
DMCC/JLT, DIFC, JAFZA, DAFZ, Dubai Silicon Oasis, Dubai Internet City, Dubai Media City, Dubai
Knowledge Park, Academic City, d3, Production City, Studio City, Science Park, Outsource City,
Industrial City, Dubai South, Expo City, Meydan, IFZA, DWTC, Dubai Healthcare City, CommerCity,
Maritime City, ADGM (Al Maryah / Al Reem), KEZAD, Masdar City, twofour54, Abu Dhabi Airport FZ,
SAIF Zone, Hamriyah, Shams, Sharjah Publishing City, SRTI Park, Ajman FZ, Ajman Media City, RAKEZ,
Fujairah Creative City, Fujairah FZ, UAQ FTZ. Edit the list in `leadbot/freezones.py`.

For each free-zone lead:
- **FREE ZONE** column = zone name (filterable)
- **LOCATION** gets the zone appended, e.g. `Almas Tower, Dubai (DMCC Free Zone)`
- **SOURCE** = `Free Zone: DMCC via Google News: WAM | <article> | verify: <official register>`

**Why the bot doesn't scrape free-zone directories:** no UAE free zone publishes a feed or API of
newly registered companies, and directory terms forbid it — DMCC's directory explicitly prohibits
copying, storing, or using listings for email/telephone marketing. The bot therefore discovers openings
from public news/posts and links to the official register for a **manual** check. Zones without a public
directory link to the federal **National Economic Register** (licence status, issuing authority, issue date).
If you need registry data at scale, ask the free zone / Ministry of Economy about an official data licence.

### Contact lookup (needs BRAVE_API_KEY or SERPER_API_KEY)
For each qualified lead the bot (a) finds the publisher's original article for Google News
headlines and reads it in full — the AI then pulls the precise location, free zone and any
contact details for that company; (b) searches for the official website, accepting only a domain
that contains a distinctive word of the company name (never news, directories or social pages);
(c) reads that website's homepage + contact page. Max `MAX_LOOKUPS` (default 40) searches per run.

### Duplicates
One company = one row. Leads are treated as the same company when the name matches (also
fuzzy: "ROKA" = "Roka Dubai", "Cafe Bateel" = "Bateel", legal suffixes ignored), or the website
domain, email or phone number matches. Repeats found in the same run are merged into one row
(blank fields filled from the others; SOURCE lists `also in: …`), and anything already in the
sheet is skipped.

### Compliance features
- Social platforms are read through search results only — no logins, no direct scraping.
- robots.txt respected and ≥2 s between requests to any one website; honest bot user-agent.
- Google Places removed (its terms don't allow storing phone/website/address long-term).
- UAE mobiles are flagged `(mobile - may be personal)`; landlines listed first.
- `optout.txt` — anyone who asks not to be contacted is never added again.
- `RETENTION_DAYS` — optional automatic deletion of old rows.
- Brave Search API (official API) is used in preference to Serper when both keys exist.

> Using these leads for calls is governed by the UAE telemarketing rules (Cabinet Resolution 56/2024:
> TDRA approval, 9 AM–6 PM, DNCR, registered landlines). Check with your compliance team.

## Setup (≈15 minutes)

1. **Repo** – push this folder to a new **private** GitHub repo.
2. **Google Sheet access**
   - Google Cloud Console → create a project → enable **Google Sheets API**.
   - IAM → Service Accounts → create one → Keys → *Add key* → JSON. Download it (never commit it).
   - Open the leads sheet → **Share** → add the service account's `…@…iam.gserviceaccount.com`
     address as **Editor**.
   - Copy the sheet ID from its URL: `docs.google.com/spreadsheets/d/<SHEET_ID>/edit`.
3. **GitHub secrets** (Settings → Secrets and variables → Actions):

   | Secret | Required | Where to get it |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | yes | console.anthropic.com |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | yes | paste the whole JSON key file |
   | `SHEET_ID` | yes | from the sheet URL |
   | `BRAVE_API_KEY` (preferred) **or** `SERPER_API_KEY` | strongly recommended | brave.com/search/api / serper.dev — needed for social + free-zone posts |
   | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | optional | daily summary to Telegram |

   Optional **variable** (Variables tab): `RETENTION_DAYS`, e.g. `180`.

4. **Test** – Actions tab → *UAE Telecom Lead Bot* → **Run workflow**. Check the log and the sheet.
   The first run renames the sheet's first tab to **Leads**, adds the FREE ZONE column and creates the
   **Free Zone Directories** tab.

GitHub may start scheduled jobs a few minutes after 08:00.

## Local run

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=... BRAVE_API_KEY=...
python -m leadbot --dry-run      # writes leads_preview.csv (git-ignored), doesn't touch the sheet
python -m unittest -v tests/test_offline.py
```
Don't run it from a corporate network — test on GitHub or a home connection.

## Tuning

Env vars: `ANTHROPIC_MODEL` (default `claude-haiku-5-5`), `MIN_CONFIDENCE` (0.6),
`MAX_CANDIDATES` (200/day), `REQUIRE_CONTACT` (`true` drops leads with no phone/email),
`WORKSHEET_NAME` (`Leads`), `RETENTION_DAYS` (0 = keep).

Daily volume: ~56 Google News feeds, 4 Time Out feeds, ~35 search-API queries (~1,050/month — check
this against your Brave/Serper plan), 5–15 Haiku calls. A few cents a day.
