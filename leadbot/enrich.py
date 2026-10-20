"""Fill in location / website / phone / email for a qualified lead from public sources.

Steps (each only when still needed):
  1. contacts printed in the item itself
  2. the original article: Google News only gives a headline + redirect, so the real article
     is found with one search, read in full (robots.txt respected), and the AI pulls this
     company's details out of it (precise location, free zone, website, phone, email)
  3. the official website: one search for the company name, accepted only when the domain
     contains a distinctive word of the name (avoids directories / news / social pages)
  4. the official website's homepage + contact page (robots.txt respected)

Google Places is NOT used: its terms don't allow storing phone/website/address long-term.
"""
import difflib
import re
import urllib.parse

from . import config, contacts, extract, http, search, sources
from .dedupe import distinctive_tokens
from .sheet import norm_name

_SOCIAL = ("news.google.", "instagram.", "linkedin.", "facebook.", "x.com", "twitter.", "tiktok.")

# never an official company website
NOT_OFFICIAL = _SOCIAL + (
    "youtube.", "wikipedia.", "google.", "bing.", "yelp.", "tripadvisor.", "zomato.", "talabat.", "deliveroo.",
    "careem.", "noon.", "amazon.", "booking.com", "timeout", "whatson.", "gulfnews.", "khaleejtimes.",
    "thenationalnews.", "zawya.", "arabianbusiness.", "gulfbusiness.", "wam.ae", "emirates247.", "lovin",
    "yellowpages", "dubizzle.", "bayut.", "propertyfinder.", "glassdoor.", "indeed.", "bloomberg.", "reuters.",
    "crunchbase.", "dnb.com", "zoominfo.", "opentable.", "eatapp.", "sevenrooms.", "foursquare.", "menu",
    "caterermiddleeast.", "hoteliermiddleeast.", "fact", "bbcgoodfood", "harpersbazaar", "esquireme", "msn.",
    "yahoo.", "apple.com", "dmcc.ae", "difc.", "adgm.", "u.ae", "economy.ae",
)


def near_name(text: str, name: str, window: int = 350) -> str:
    """Text following each mention of `name` (contacts in round-ups come after the venue name)."""
    key = name.lower()[:20]
    low, out, i = text.lower(), [], 0
    while key and (i := low.find(key, i)) != -1:
        out.append(text[i:i + len(key) + window])
        i += len(key)
    return " ".join(out)


def clean_location(loc: str) -> str:
    """'Dubai, Dubai' -> 'Dubai'; drops empty / repeated parts and a trailing 'UAE'."""
    parts, seen = [], set()
    for p in (x.strip() for x in (loc or "").split(",")):
        if p and p.lower() not in seen and p.lower() not in ("uae", "united arab emirates"):
            seen.add(p.lower())
            parts.append(p)
    return ", ".join(parts)


def headline(title: str) -> str:
    return re.split(r" [-|] ", title)[0].strip()


def is_official_site(url: str, company: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    if not host or any(b in host for b in NOT_OFFICIAL):
        return False
    compact = re.sub(r"[^a-z0-9]", "", host.rsplit(".", 1)[0])      # drop TLD, dots, hyphens
    toks = distinctive_tokens(norm_name(company))
    return bool(toks) and (any(t in compact for t in toks) or "".join(sorted(toks)) in compact
                           or "".join(norm_name(company).split()) in compact)


def find_article(lead: dict, budget: search.Budget) -> tuple[str, str]:
    """For a Google News item: find the publisher's real URL and read the article. -> (url, text)"""
    src = lead["source"]
    if "news.google." not in src.url or not budget.take():
        return "", ""
    h = headline(src.title)
    try:
        results = search.web_search(f'"{h}"', count=5)
    except Exception as e:
        print(f"[lookup] article search failed for {lead['company_name']}: {e}")
        return "", ""
    for r in results:
        if "news.google." in r["url"]:
            continue
        if difflib.SequenceMatcher(None, headline(r["title"]).lower(), h.lower()).ratio() < 0.6:
            continue
        text = r["description"]
        try:
            res = http.polite_get(r["url"], timeout=20)
            if res:
                text = sources.article_text(res[1])[: config.FULLTEXT_CHARS] or text
        except Exception:
            pass
        return r["url"], text
    return "", ""


def find_website(lead: dict, budget: search.Budget) -> str:
    if not budget.take():
        return ""
    emirate = next((e for e in config.EMIRATES if e.lower() in lead["location"].lower()), "UAE")
    try:
        results = search.web_search(f'"{lead["company_name"]}" {emirate}', count=10)
    except Exception as e:
        print(f"[lookup] website search failed for {lead['company_name']}: {e}")
        return ""
    for r in results:
        if is_official_site(r["url"], lead["company_name"]):
            p = urllib.parse.urlparse(r["url"])
            return f"{p.scheme}://{p.netloc}"
    return ""


def enrich(lead: dict, budget: search.Budget | None = None) -> dict:
    budget = budget or search.Budget(0)
    src = lead["source"]

    # 1) contacts printed in the item itself (round-ups: only near this company's name)
    if len(src.snippet) >= 1500:
        phones, emails = contacts.extract(f"{lead['phone']} {lead['email']} " + near_name(src.snippet, lead["company_name"]))
        phones, emails = phones[:1], emails[:1]
    else:
        phones, emails = contacts.extract(f"{src.title} {src.snippet} {lead['phone']} {lead['email']}")

    # 2) the original article, read in full
    article_url, article = find_article(lead, budget) if search.available() else ("", "")
    if not article and len(src.snippet) < 1500 and not any(d in src.url for d in _SOCIAL):
        try:
            res = http.polite_get(src.url, timeout=15)
            if res:
                article_url, article = src.url, sources.article_text(res[1])[: config.FULLTEXT_CHARS]
        except Exception:
            pass
    if article_url:
        lead["article_url"] = article_url
    if len(article) > 300:
        d = extract.details_from_article(lead["company_name"], article)
        if d.get("location") and len(d["location"]) >= len(lead["location"]):
            lead["location"] = d["location"]
        for f_src, f_dst in (("free_zone", "free_zone_hint"), ("website", "website")):
            if d.get(f_src) and not lead.get(f_dst):
                lead[f_dst] = d[f_src]
        p, e = contacts.extract(f"{d.get('phone', '')} {d.get('email', '')} " + near_name(article, lead["company_name"]))
        phones += [x for x in p[:1] if x not in phones]
        emails += [x for x in e[:1] if x not in emails]
        lead["article_text"] = article

    # 3) official website via search
    website = lead["website"]
    if website and not is_official_site(website, lead["company_name"]) and \
            any(b in website for b in NOT_OFFICIAL):
        website = ""                                   # e.g. an Instagram link isn't a website
    if not website and search.available():
        website = find_website(lead, budget)

    # 4) official website's homepage + contact page
    if website and (not phones or not emails):
        p, e = contacts.scrape_site(website)
        phones += [x for x in p if x not in phones]
        emails += [x for x in e if x not in emails]

    phones.sort(key=lambda x: x.startswith("+971 5"))  # landlines / toll-free first
    lead.update(
        phone=", ".join(contacts.label(p) for p in phones[:2]),
        email=contacts.best_email(emails, website),
        website=website,
        location=clean_location(lead["location"]),
    )
    return lead
