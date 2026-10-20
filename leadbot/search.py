"""Web search via official APIs (Brave preferred, Serper fallback) + a per-run query budget."""
import os
import time
import urllib.parse

from . import http


class Budget:
    """Caps paid search calls used for enrichment in a single run."""

    def __init__(self, limit: int):
        self.left = limit

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        return True


def available() -> bool:
    return bool(os.getenv("BRAVE_API_KEY") or os.getenv("SERPER_API_KEY"))


def web_search(query: str, count: int = 10, freshness: str | None = None) -> list[dict]:
    """Return [{'title','url','description'}]. freshness: 'pd' (day), 'pw' (week) or None."""
    brave_key, serper_key = os.getenv("BRAVE_API_KEY"), os.getenv("SERPER_API_KEY")
    if brave_key:
        # No "country": Brave doesn't support AE (422 error). Queries name the UAE place instead.
        params = {"q": query, "count": min(count, 20), "search_lang": "en"}
        if freshness:
            params["freshness"] = freshness
        data = http.get_json("https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(params),
                             {"X-Subscription-Token": brave_key})
        time.sleep(1.1)                       # stay under 1 request / second
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
                for r in data.get("web", {}).get("results", []) if r.get("url")]
    if serper_key:
        body = {"q": query, "gl": "ae", "hl": "en", "num": count}
        if freshness:
            body["tbs"] = {"pd": "qdr:d", "pw": "qdr:w"}.get(freshness, "")
        data = http.post_json("https://google.serper.dev/search", body, {"X-API-KEY": serper_key},
                              timeout=30, retries=1)
        return [{"title": r.get("title", ""), "url": r.get("link", ""), "description": r.get("snippet", "")}
                for r in data.get("organic", []) if r.get("link")]
    return []
