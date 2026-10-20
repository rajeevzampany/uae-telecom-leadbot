"""Central configuration. Everything tunable lives here or in env vars."""
import os
from datetime import timedelta, timezone

from . import freezones

DUBAI_TZ = timezone(timedelta(hours=4))
EMIRATES = ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Ras Al Khaimah", "Fujairah", "Umm Al Quwain"]

# ---- Output sheet -----------------------------------------------------------
SHEET_ID = os.getenv("SHEET_ID", "")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Leads")
REFERENCE_TAB = "Free Zone Directories"
# Market-entry information first; contact details are secondary.
HEADERS = ["DATE", "COMPANY NAME", "SECTOR", "STAGE", "EXPECTED OPENING", "NEW TO UAE", "ORIGIN",
           "EMIRATE", "LOCATION", "FREE ZONE", "WEBSITE", "CONTACT NUMBER", "EMAIL", "SOURCE"]

# Delete rows older than N days (0 = keep forever). Supports data-minimisation under PDPL.
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "0"))
# Companies / domains / phones / emails that asked not to be contacted - one per line.
OPTOUT_FILE = os.getenv("OPTOUT_FILE", "optout.txt")

# ---- AI extraction ----------------------------------------------------------
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.6"))
BATCH_SIZE = 15                      # candidate items per LLM call
# Max paid search calls per run spent on enrichment (finding the original article and the
# official website: up to 2 per lead). Brave includes ~1,000 calls/month in its free credit.
MAX_LOOKUPS = int(os.getenv("MAX_LOOKUPS", "40"))
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "400"))

# Keep leads that have no phone/email after enrichment? (location/website may still help)
REQUIRE_CONTACT = os.getenv("REQUIRE_CONTACT", "false").lower() == "true"

# ---- State ------------------------------------------------------------------
STATE_FILE = os.getenv("STATE_FILE", "state/seen.json")
STATE_RETENTION_DAYS = 45

# ---- Search window ------------------------------------------------------------
# Daily runs look back 7 days: search engines index announcements and social posts with a
# delay. Overlap is harmless - processed items and companies already in the sheet are skipped.
NEWS_WINDOW = os.getenv("NEWS_WINDOW", "7d")     # Google News "when:" value
WEB_FRESHNESS = os.getenv("WEB_FRESHNESS", "pw")  # search API: pd = day, pw = week

ALL_AREAS = EMIRATES + ["Al Ain"]
_OPENING_SOON = '"opening soon" OR "set to open" OR "will open" OR "to open" OR "coming soon" OR "plans to open"'
_OPENED = 'opens OR inaugurates OR "now open" OR "grand opening" OR "new branch" OR "new office"'

# ---- Google News RSS (English, no key needed) ------------------------------------
NEWS_QUERIES = [
    # companies entering the UAE market (all emirates)
    '"enters UAE market" OR "entry into the UAE" OR "expands into the UAE" OR "expansion into the UAE"',
    '"first store in the UAE" OR "first UAE store" OR "first branch in the UAE" OR "UAE debut"',
    '"first outlet in the UAE" OR "first restaurant in the UAE" OR "first location in the UAE"',
    '"regional headquarters" UAE opens OR establishes OR relocates',
    '"opens office in Abu Dhabi" OR "opens office in Dubai" OR "opens office in Sharjah"',
    '"master franchise" UAE OR "franchise agreement" UAE',
    '"plans to open" UAE stores OR branches OR outlets OR restaurants OR clinics',
    '"to open in 2027" UAE OR "opening in 2027" UAE OR "opens in 2027" UAE',
    'UAE new factory OR plant OR warehouse opens OR "set to open"',
    '"signs agreement to open" UAE OR "signs lease" UAE',
    '"new hotel" UAE "opening" OR "to open"',
    '"new school" UAE "to open" OR "opening" 2027',
    '"new hospital" OR "new clinic" UAE opens OR "to open"',
    '"new mall" OR "new showroom" UAE opens',
] + [
    # every emirate: opening soon + just opened
    q for area in ALL_AREAS for q in (f'"{area}" {_OPENING_SOON}', f'"{area}" {_OPENED}')
] + freezones.news_queries()          # + one query per UAE free zone (39 zones)

# ---- Google News RSS (Arabic) - northern-emirate and local business news ---------
NEWS_QUERIES_AR = [
    '"افتتاح فرع جديد" الإمارات',          # opening a new branch, UAE
    '"يفتتح قريباً" الإمارات',             # opens soon, UAE
    '"أول فرع" الإمارات افتتاح',           # first branch, UAE, opening
    '"دخول السوق الإماراتية"',             # entering the UAE market
    'افتتاح مقر إقليمي الإمارات',          # opening a regional headquarters, UAE
] + [f'افتتاح "{a}"' for a in ["أبوظبي", "الشارقة", "عجمان", "رأس الخيمة", "الفجيرة", "أم القيوين", "العين"]]

# ---- Social + web queries (need BRAVE_API_KEY or SERPER_API_KEY) -------------
# Social platforms are reached through search-engine results, not by logging in or
# scraping the platforms directly (keeps the bot within platform terms).
_NON_DUBAI = '("Abu Dhabi" OR Sharjah OR Ajman OR "Ras Al Khaimah" OR Fujairah OR "Umm Al Quwain" OR "Al Ain")'
WEB_QUERIES = [
    'site:instagram.com "opening soon" (Dubai OR UAE)',
    f'site:instagram.com "opening soon" OR "coming soon" {_NON_DUBAI}',
    f'site:instagram.com "now open" {_NON_DUBAI}',
    'site:instagram.com "now open" Dubai',
    'site:linkedin.com/posts "new office" (Dubai OR UAE)',
    f'site:linkedin.com/posts "new office" OR "opened our" {_NON_DUBAI}',
    'site:linkedin.com/posts "expanding to the UAE" OR "entering the UAE" OR "launching in the UAE"',
    'site:linkedin.com/posts "regional headquarters" UAE',
    'site:facebook.com "grand opening" OR "opening soon" UAE',
    'site:x.com "now open" OR "opening soon" UAE',
    '"coming soon" UAE first store OR branch OR restaurant 2026 OR 2027',
    '"enters the UAE" OR "launches in the UAE" brand opening',
    'whatson.ae new openings',
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
