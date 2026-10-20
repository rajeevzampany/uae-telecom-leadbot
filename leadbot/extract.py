"""Use Claude to qualify raw items and pull structured lead fields."""
import json
import os
import re

from . import config, http
from .sources import Candidate

SYSTEM = """You qualify sales leads for a UAE B2B telecom provider selling business internet and fixed landlines.

You receive numbered news / social-media items from the last 24 hours. Identify every business that is NEWLY OPENING, OPENING SOON, or has JUST OPENED a physical premises in the UAE - e.g. offices, regional HQs, restaurants, cafes, retail stores, clinics, salons, gyms, hotels, schools, co-working spaces, warehouses, showrooms. New branches of existing brands count.

FREE ZONES matter: a company opening an office, HQ, branch, facility or warehouse in any UAE free zone (DMCC/JLT, DIFC, ADGM, JAFZA, DAFZ, Dubai Silicon Oasis, Dubai Internet/Media City, Dubai South, Meydan, IFZA, DWTC, Dubai Healthcare City, KEZAD, Masdar City, twofour54, SAIF Zone, Hamriyah, Shams, Ajman Free Zone, RAKEZ, Fujairah Creative City, UAQ FTZ, etc.) counts, including "X joins DMCC" / "X sets up in ADGM" / "DIFC welcomes X". Name the zone in "free_zone".

Exclude: residential real-estate launches, product/app/menu launches with no new premises, events and festivals, closures, openings outside the UAE, and government announcements that name no business. A listicle ("10 new restaurants in Dubai", Time Out "new openings this month") is fine - extract each named business separately with its own location. Exclude dining deals, brunch offers, and reviews/awards of venues that are not newly opened.

Use ONLY facts in the item text. Never guess phone numbers, emails or websites - use "" when absent.

Reply with ONLY a JSON array (no prose). Each element:
{"item": <item number>, "company_name": "...", "business_type": "restaurant|cafe|office|retail|clinic|hotel|other", "location": "area, emirate", "free_zone": "zone name or empty", "website": "", "phone": "", "email": "", "confidence": <0.0-1.0 that this is a genuine new UAE premises>}
Return [] if nothing qualifies."""


def parse_json_array(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)]


DETAIL_SYSTEM = """You read one news article and extract facts about ONE named UAE business from it.
Use ONLY what the article states about that business - never guess, never use the publisher's or another venue's details.
Reply with ONLY a JSON object:
{"location": "most specific address/area + emirate, e.g. 'Gate Village 3, DIFC, Dubai' or ''", "free_zone": "UAE free zone name if the premises is in one, else ''", "website": "", "phone": "", "email": ""}"""


def details_from_article(company: str, article: str) -> dict:
    try:
        text = _call_claude(f"Business: {company}\n\nArticle:\n{article}", system=DETAIL_SYSTEM, max_tokens=400)
    except Exception as e:
        print(f"[ai] details for {company} failed: {e}")
        return {}
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}
    return {k: str(v).strip() for k, v in d.items() if isinstance(v, (str, int, float)) and str(v).strip()} \
        if isinstance(d, dict) else {}


def _call_claude(user_text: str, system: str = SYSTEM, max_tokens: int = 4000) -> str:
    resp = http.post_json(
        "https://api.anthropic.com/v1/messages",
        {"model": config.ANTHROPIC_MODEL, "max_tokens": max_tokens, "system": system,
         "messages": [{"role": "user", "content": user_text}]},
        {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
    )
    return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")


def extract_leads(cands: list[Candidate]) -> list[dict]:
    leads = []
    for start in range(0, len(cands), config.BATCH_SIZE):
        batch = cands[start:start + config.BATCH_SIZE]
        prompt = "\n\n".join(
            f"[{i}] ({c.channel}) {c.title}\n{c.snippet}\nURL: {c.url}"
            for i, c in enumerate(batch, 1)
        )
        try:
            rows = parse_json_array(_call_claude(prompt))
        except Exception as e:
            print(f"[ai] batch {start // config.BATCH_SIZE + 1} failed: {e}")
            continue
        for r in rows:
            try:
                idx = int(r.get("item", 0))
                conf = float(r.get("confidence", 0))
            except (TypeError, ValueError):
                continue
            if not (1 <= idx <= len(batch)) or conf < config.MIN_CONFIDENCE:
                continue
            name = str(r.get("company_name", "")).strip()
            if not name:
                continue
            src = batch[idx - 1]
            leads.append({
                "company_name": name,
                "business_type": str(r.get("business_type", "")),
                "location": str(r.get("location", "")).strip(),
                "free_zone_hint": str(r.get("free_zone", "")).strip(),
                "website": str(r.get("website", "")).strip(),
                "phone": str(r.get("phone", "")).strip(),
                "email": str(r.get("email", "")).strip(),
                "confidence": conf,
                "source": src,
            })
    return leads
