"""Collect raw candidate items from news (RSS) and social/web (search APIs)."""
import hashlib
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from . import config, http, search

_TAG = re.compile(r"<[^>]+>")


@dataclass
class Candidate:
    title: str
    snippet: str
    url: str
    channel: str  # e.g. "Instagram", "LinkedIn", "Google News: Khaleej Times"

    @property
    def key(self) -> str:
        return hashlib.sha1(self.url.split("?")[0].encode()).hexdigest()[:16]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", text or ""))).strip()


def _host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def listing_site(url: str) -> dict | None:
    h = _host(url)
    return next((s for s in config.LISTING_SITES if h == s["domain"] or h.endswith("." + s["domain"])), None)


def channel_for(url: str) -> str:
    host = _host(url)
    site = listing_site(url)
    if site:
        return site["name"]
    for dom, name in [("instagram.com", "Instagram"), ("linkedin.com", "LinkedIn"),
                      ("facebook.com", "Facebook"), ("x.com", "X"), ("twitter.com", "X"),
                      ("tiktok.com", "TikTok"), ("youtube.com", "YouTube")]:
        if host == dom or host.endswith("." + dom):
            return name
    return host or "web"


# ---- Google News RSS (free, no key) -----------------------------------------
def google_news(query: str, lang: str = "en") -> list[Candidate]:
    q = urllib.parse.quote(f"{query} when:{config.NEWS_WINDOW}")
    hl = "en-AE" if lang == "en" else lang
    url = f"https://news.google.com/rss/search?q={q}&hl={hl}&gl=AE&ceid=AE:{lang}"
    _, xml_text = http.throttled_get(url, delay=1.5)
    return parse_google_news(xml_text)


def parse_google_news(xml_text: str) -> list[Candidate]:
    out = []
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        title = clean(item.findtext("title", ""))
        link = (item.findtext("link") or "").strip()
        desc = clean(item.findtext("description", ""))
        publisher = clean(item.findtext("source", "")) or "news"
        if title and link:
            out.append(Candidate(title, desc, link, f"Google News: {publisher}"))
    return out


# ---- Listing sites (Time Out Dubai / Abu Dhabi) -----------------------------------
OPENING_RE = re.compile(r"\b(new|opens?|opening|opened|now open|launch(es|ed)?|debuts?|coming soon|"
                        r"arriv(es|ing)|soft[- ]opening|first look|unveils?)\b", re.I)
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


def parse_rss(xml_text: str, channel: str) -> list[Candidate]:
    """Generic RSS 2.0 (e.g. WordPress) - keeps only items that look like openings."""
    out = []
    for item in ET.fromstring(xml_text).iter("item"):
        title = clean(item.findtext("title", ""))
        link = (item.findtext("link") or "").strip()
        body = clean(item.findtext(_CONTENT, "") or item.findtext("description", ""))
        if title and link and OPENING_RE.search(title):
            out.append(Candidate(title, body[: config.FULLTEXT_CHARS], link, channel))
    return out


def site_feeds() -> list[Candidate]:
    out = []
    for site in config.LISTING_SITES:
        for feed in site["feeds"]:
            try:
                res = http.polite_get(feed, timeout=20)
            except Exception as e:
                print(f"[site] {feed}: {e}")
                continue
            if res is None:
                print(f"[site] {feed}: disallowed by robots.txt - using search routes only")
                continue
            try:
                out += parse_rss(res[1], site["name"])
            except ET.ParseError:
                print(f"[site] {feed}: not an RSS feed")
    return out


def article_text(page_html: str) -> str:
    """Main text of an article page: <article> if present, else <body>; scripts/nav removed."""
    page_html = re.sub(r"(?is)<(script|style|nav|header|footer|aside|form)\b.*?</\1>", " ", page_html)
    m = re.search(r"(?is)<article\b.*?</article>", page_html) or re.search(r"(?is)<body\b.*?</body>", page_html)
    return clean(m.group(0) if m else page_html)


def expand_listing_articles(cands: list[Candidate]) -> int:
    """Replace short snippets of listing-site opening articles with the article's full text,
    so every business named in a round-up gets extracted. Returns how many were expanded."""
    n = 0
    for c in cands:
        if not listing_site(c.url) or not OPENING_RE.search(c.title):
            continue
        if len(c.snippet) >= 1500:          # feed already gave full content
            continue
        try:
            res = http.polite_get(c.url, timeout=20)
        except Exception as e:
            print(f"[site] {c.url}: {e}")
            continue
        if res:
            text = article_text(res[1])
            if len(text) > len(c.snippet):
                c.snippet = text[: config.FULLTEXT_CHARS]
                n += 1
    return n


# ---- Search APIs for social + open web (last 24h) ----------------------------
def web(query: str) -> list[Candidate]:
    """Recent results from the configured search API (Brave preferred, Serper fallback)."""
    return [Candidate(clean(r["title"]), clean(r["description"]), r["url"], channel_for(r["url"]))
            for r in search.web_search(query, count=20, freshness=config.WEB_FRESHNESS)]


def collect() -> list[Candidate]:
    # Order matters for de-duplication: routes with the publisher's real URL (site feeds,
    # search APIs) come before Google News, whose links are redirects that can't be read in full.
    items: list[Candidate] = site_feeds()
    print(f"[site] {len(items)} opening articles from listing-site feeds")

    # Brave is an official search API, so it's preferred when both keys exist
    if search.available():
        n_err = 0
        for q in config.WEB_QUERIES:
            try:
                items += web(q)
            except Exception as e:
                n_err += 1
                print(f"[web] {q!r}: {e}")
                if n_err >= 3 and n_err == config.WEB_QUERIES.index(q) + 1:
                    print("[web] first 3 searches all failed - stopping web searches for this run")
                    break
    else:
        print("[web] no SERPER_API_KEY / BRAVE_API_KEY set - social channels skipped")

    for q, lang in [(q, "en") for q in config.NEWS_QUERIES] + [(q, "ar") for q in config.NEWS_QUERIES_AR]:
        try:
            items += google_news(q, lang)
        except Exception as e:  # one bad feed shouldn't kill the run
            print(f"[news] {q!r}: {e}")

    # de-duplicate by URL and by near-identical headline (same story, many outlets)
    seen_keys, seen_titles, unique = set(), set(), []
    for c in items:
        t = re.sub(r"\W+", "", re.split(r" [-|] ", c.title.lower())[0])[:60]
        if c.key in seen_keys or (t and t in seen_titles):
            continue
        seen_keys.add(c.key)
        seen_titles.add(t)
        unique.append(c)
    return unique
