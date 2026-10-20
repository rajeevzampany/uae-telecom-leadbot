"""Central configuration. Everything tunable lives here or in env vars."""
import os
from datetime import timedelta, timezone

from . import freezones

DUBAI_TZ = timezone(timedelta(hours=4))

# ---- Output sheet -----------------------------------------------------------
SHEET_ID = os.getenv("SHEET_ID", "")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Leads")
REFERENCE_TAB = "Free Zone Directories"
HEADERS = ["DATE", "COMPANY NAME", "CONTACT NUMBER", "EMAIL", "LOCATION", "WEBSITE", "SOURCE", "FREE ZONE"]

# Delete rows older than N days (0 = keep forever). Supports data-minimisation under PDPL.
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "0"))
# Companies / domains / phones / emails that asked not to be contacted - one per line.
OPTOUT_FILE = os.getenv("OPTOUT_FILE", "optout.txt")

# ---- AI extraction ----------------------------------------------------------
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.6"))
BATCH_SIZE = 15                      # candidate items per LLM call
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "200"))

# Keep leads that have no phone/email after enrichment? (location/website may still help)
REQUIRE_CONTACT = os.getenv("REQUIRE_CONTACT", "false").lower() == "true"

# ---- State ------------------------------------------------------------------
STATE_FILE = os.getenv("STATE_FILE", "state/seen.json")
STATE_RETENTION_DAYS = 45

EMIRATES = ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Ras Al Khaimah", "Fujairah", "Umm Al Quwain"]

# ---- Open-web / news queries (Google News RSS, no key needed, last 24h) ------
NEWS_QUERIES = [
    '"opening soon" restaurant Dubai',
    '"now open" restaurant Dubai',
    '"new cafe" Dubai',
    '"opens" cafe "Abu Dhabi"',
    '"new restaurant" "Abu Dhabi"',
    '"opens new office" Dubai',
    '"new office" "Abu Dhabi" opens',
    '"regional headquarters" Dubai opens',
    '"inaugurates" office UAE',
    '"grand opening" UAE',
    '"new branch" Sharjah',
    '"opens" Sharjah restaurant OR cafe OR store',
    '"now open" "Ras Al Khaimah" OR Ajman OR Fujairah',
    '"launches" "first store" UAE',
    '"new clinic" Dubai opens',
] + freezones.news_queries()          # + one query per UAE free zone (39 zones)

# ---- Social + web queries (need SERPER_API_KEY or BRAVE_API_KEY) -------------
# Social platforms are reached through search-engine results, not by logging in or
# scraping the platforms directly (keeps the bot within platform terms).
WEB_QUERIES = [
    'site:instagram.com "opening soon" Dubai',
    'site:instagram.com "now open" Dubai cafe',
    'site:instagram.com "now open" "Abu Dhabi"',
    'site:instagram.com "soft opening" Dubai',
    'site:linkedin.com/posts "new office" Dubai',
    'site:linkedin.com/posts "opened our" office Dubai OR "Abu Dhabi"',
    'site:linkedin.com/posts "proud to announce" opening Dubai office',
    'site:facebook.com "grand opening" Dubai OR Sharjah',
    'site:x.com "now open" Dubai',
    'site:tiktok.com "new cafe" Dubai',
    '"coming soon" restaurant Dubai 2026',
    '"new opening" cafe Sharjah',
    'whatson.ae new restaurant openings',
] + freezones.web_queries()           # + LinkedIn / Instagram posts mentioning free zones

# ---- Listing / city-guide websites ---------------------------------------------
# Read three ways so one blocked route doesn't lose the source:
#   1) the site's own RSS feed (robots.txt respected)  2) Google News site: search
#   3) search-API site: search. Opening articles are then read in full (robots.txt
#   respected) so every business in a "new restaurants this month" list is captured.
LISTING_SITES = [
    {"name": "Time Out Dubai", "domain": "timeoutdubai.com",
     "feeds": ["https://www.timeoutdubai.com/feed", "https://www.timeoutdubai.com/restaurants/feed"]},
    {"name": "Time Out Abu Dhabi", "domain": "timeoutabudhabi.com",
     "feeds": ["https://www.timeoutabudhabi.com/feed", "https://www.timeoutabudhabi.com/restaurants/feed"]},
]
FULLTEXT_CHARS = 8000                 # article text passed to the AI per listing-site article

for _s in LISTING_SITES:
    NEWS_QUERIES.append(f'site:{_s["domain"]} opening OR "now open" OR "new restaurant" OR "new cafe" '
                        f'OR opens OR "coming soon"')
    WEB_QUERIES.append(f'site:{_s["domain"]} "new restaurants" OR "now open" OR "opening soon"')
    WEB_QUERIES.append(f'site:{_s["domain"]} "new cafe" OR "new bar" OR "opens" OR "first look"')
