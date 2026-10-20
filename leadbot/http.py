"""Tiny stdlib HTTP helpers with retries."""
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

UA = "Mozilla/5.0 (compatible; UAETelecomLeadBot/1.0)"


def _read(resp) -> bytes:
    data = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        data = gzip.decompress(data)
    return data


def get(url: str, headers: dict | None = None, timeout: int = 20, max_bytes: int = 2_000_000):
    """Return (final_url, text). Raises on network errors."""
    h = {"User-Agent": UA, "Accept-Language": "en-AE,en;q=0.9", "Accept-Encoding": "gzip"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = _read(resp)[:max_bytes]
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.geturl(), raw.decode(charset, errors="replace")


_last_hit: dict[str, float] = {}
_robots: dict[str, object] = {}
ROBOTS_UA = "UAETelecomLeadBot"


def throttled_get(url: str, delay: float = 2.0, **kw):
    """GET with a minimum gap between requests to the same host."""
    host = urllib.parse.urlparse(url).netloc
    wait = _last_hit.get(host, 0) + delay - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return get(url, **kw)
    finally:
        _last_hit[host] = time.monotonic()


def allowed_by_robots(url: str) -> bool:
    """Check robots.txt (cached per host). Unreachable / 401 / 403 robots => don't crawl."""
    p = urllib.parse.urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    rp = _robots.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            _, text = get(base + "/robots.txt", timeout=10)
            rp.parse(text.splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                rp.disallow_all = True
            else:                       # 404 etc. -> no robots rules
                rp.allow_all = True
        except Exception:
            rp.disallow_all = True      # can't reach it -> be conservative
        _robots[base] = rp
    return rp.can_fetch(ROBOTS_UA, url)


def polite_get(url: str, delay: float = 2.0, **kw):
    """robots.txt-respecting, rate-limited GET for crawling third-party web pages.
    Returns (final_url, text) or None when the site disallows bots."""
    if not allowed_by_robots(url):
        return None
    return throttled_get(url, delay, **kw)


def get_json(url: str, headers: dict | None = None, timeout: int = 20) -> dict:
    _, text = get(url, {"Accept": "application/json", **(headers or {})}, timeout)
    return json.loads(text)


def post_json(url: str, payload: dict, headers: dict | None = None,
              timeout: int = 90, retries: int = 3) -> dict:
    body = json.dumps(payload).encode()
    h = {"Content-Type": "application/json", "User-Agent": UA}
    h.update(headers or {})
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(_read(resp).decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < retries:
                time.sleep(2 ** attempt * 3)
                continue
            detail = e.read().decode(errors="replace")[:500]
            raise RuntimeError(f"POST {url} -> HTTP {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries:
                time.sleep(2 ** attempt * 3)
                continue
            raise
    raise RuntimeError("unreachable")
