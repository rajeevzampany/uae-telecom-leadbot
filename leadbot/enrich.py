"""Fill in missing phone / email for a lead from public pages the business or press published.

Google Places was removed on purpose: Google Maps Platform terms don't allow storing Places
content (phone, website, address) in your own database long-term.
"""
import re
import urllib.parse

from . import contacts, http

_SOCIAL = ("news.google.", "instagram.", "linkedin.", "facebook.", "x.com", "twitter.", "tiktok.")


def near_name(text: str, name: str, window: int = 350) -> str:
    """Text following each mention of `name` (contacts in round-ups come after the venue name)."""
    key = name.lower()[:20]
    low, out, i = text.lower(), [], 0
    while key and (i := low.find(key, i)) != -1:
        out.append(text[i:i + len(key) + window])
        i += len(key)
    return " ".join(out)


def enrich(lead: dict) -> dict:
    src = lead["source"]

    # 1) contacts mentioned in the item itself. A full article (e.g. a Time Out round-up) names
    #    many venues, so only look in a window around this company's name.
    if len(src.snippet) >= 1500:
        phones, emails = contacts.extract(f"{lead['phone']} {lead['email']} " + near_name(src.snippet, lead["company_name"]))
        phones, emails = phones[:1], emails[:1]   # the first number after the name is this venue's
    else:
        phones, emails = contacts.extract(f"{src.title} {src.snippet} {lead['phone']} {lead['email']}")

    # 2) the source article (never social pages, which need login/JS and forbid scraping;
    #    skipped when we already hold the article's full text)
    host = urllib.parse.urlparse(src.url).netloc
    if len(src.snippet) < 1500 and not any(d in host for d in _SOCIAL):
        try:
            res = http.polite_get(src.url, timeout=15)
        except Exception:
            res = None
        if res:
            _, page = res
            # only keep contacts that sit next to the company name, not the publisher's own number
            key = lead["company_name"].lower()[:20]
            for chunk in re.split(r"</p>|<br\s*/?>|\n", page):
                if key in chunk.lower():
                    p, e = contacts.extract(re.sub(r"<[^>]+>", " ", chunk))
                    phones += [x for x in p if x not in phones]
                    emails += [x for x in e if x not in emails]

    # 3) the company's own website (homepage + contact page), robots.txt respected
    website = lead["website"]
    if website and (not phones or not emails):
        p, e = contacts.scrape_site(website)
        phones += [x for x in p if x not in phones]
        emails += [x for x in e if x not in emails]

    # landlines / toll-free first, mobiles flagged as possibly personal
    phones.sort(key=lambda x: x.startswith("+971 5"))
    lead.update(
        phone=", ".join(contacts.label(p) for p in phones[:2]),
        email=contacts.best_email(emails, website),
        website=website,
    )
    return lead
