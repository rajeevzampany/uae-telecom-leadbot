"""Phone/email extraction and website contact scraping."""
import re
import urllib.parse

from . import http

# UAE numbers: +971 / 00971 / 0, then mobile (5x) or landline area code (2,3,4,6,7,9), or 800/600
PHONE_RE = re.compile(
    r"(?<![\d+])(?:\+971|00971|0)[\s\-.()]*"
    r"(?:5[0-9]|[234679]|800|600)[\s\-.)]*\d{3}[\s\-.]*\d{3,4}(?!\d)"
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_BAD_EMAIL = re.compile(r"\.(png|jpe?g|gif|webp|svg)$|@(sentry|example|wixpress|domain)\.", re.I)
_CONTACT_HREF = re.compile(r'href=["\']([^"\']*(?:contact|reach|location|about)[^"\']*)["\']', re.I)


def normalize_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw)
    if d.startswith("00971"):
        d = d[5:]
    elif d.startswith("971"):
        d = d[3:]
    elif d.startswith("0"):
        d = d[1:]
    if d.startswith(("800", "600")):
        return "+971 " + d[:3] + " " + d[3:]
    if len(d) == 9 and d.startswith("5"):        # mobile 5X XXX XXXX
        return f"+971 {d[:2]} {d[2:5]} {d[5:]}"
    if len(d) == 8:                               # landline X XXX XXXX
        return f"+971 {d[0]} {d[1:4]} {d[4:]}"
    return ""


def label(phone: str) -> str:
    """Business landlines / toll-free are safe to list; UAE mobiles (+971 5x) may be personal."""
    return f"{phone} (mobile - may be personal)" if phone.startswith("+971 5") else phone


def extract(text: str) -> tuple[list[str], list[str]]:
    phones, emails = [], []
    for m in PHONE_RE.findall(text or ""):
        p = normalize_phone(m)
        if p and p not in phones:
            phones.append(p)
    for m in EMAIL_RE.findall(text or ""):
        e = m.lower().rstrip(".")
        if not _BAD_EMAIL.search(e) and e not in emails:
            emails.append(e)
    return phones, emails


def best_email(emails: list[str], website: str = "") -> str:
    """Prefer an address on the company's own domain, and info@/sales@ style inboxes."""
    if not emails:
        return ""
    host = urllib.parse.urlparse(website).netloc.lower().removeprefix("www.")
    def score(e):
        s = 0
        if host and e.endswith("@" + host):
            s += 2
        if e.split("@")[0] in ("info", "hello", "contact", "sales", "enquiries", "inquiries", "reservations"):
            s += 1
        return -s
    return sorted(emails, key=score)[0]


def scrape_site(website: str, max_pages: int = 3) -> tuple[list[str], list[str]]:
    """Fetch the homepage plus a couple of contact-ish pages and pull phones/emails."""
    if not website:
        return [], []
    if not website.startswith("http"):
        website = "https://" + website
    phones, emails, queue, done = [], [], [website], set()
    while queue and len(done) < max_pages:
        url = queue.pop(0)
        if url in done:
            continue
        done.add(url)
        try:
            res = http.polite_get(url, timeout=15)
        except Exception:
            continue
        if res is None:                 # robots.txt says no
            continue
        final, page = res
        # tel:/mailto: links are the most reliable signal
        tel = " ".join(re.findall(r'href=["\']tel:([^"\']+)', page, re.I))
        mail = " ".join(re.findall(r'href=["\']mailto:([^"\'?]+)', page, re.I))
        p, e = extract(tel + " " + mail + " " + re.sub(r"<[^>]+>", " ", page))
        phones += [x for x in p if x not in phones]
        emails += [x for x in e if x not in emails]
        if len(done) == 1:
            base_host = urllib.parse.urlparse(final).netloc
            for href in _CONTACT_HREF.findall(page)[:5]:
                nxt = urllib.parse.urljoin(final, href)
                if urllib.parse.urlparse(nxt).netloc == base_host:
                    queue.append(nxt)
    return phones, emails
