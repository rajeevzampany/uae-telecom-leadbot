"""Use Claude to qualify raw items and pull structured lead fields."""
import json
import os
import re

from . import config, http
from .sources import Candidate

SYSTEM = """You track companies ENTERING OR EXPANDING IN THE UAE MARKET for a B2B telecom provider (business internet and landlines). Every new premises needs connectivity, so the goal is to spot them as early as possible - announced and coming-soon openings are the most valuable.

You receive numbered news / social-media items (English or Arabic) from the last few days. Identify every business that has ANNOUNCED, is ABOUT TO OPEN, or has JUST OPENED a physical premises anywhere in the UAE - all seven emirates (Abu Dhabi incl. Al Ain, Dubai, Sharjah, Ajman, Ras Al Khaimah, Fujairah, Umm Al Quwain). Premises include offices, regional HQs, restaurants, cafes, retail stores, showrooms, malls, clinics, hospitals, schools, hotels, gyms, salons, co-working spaces, warehouses, factories and plants. New branches of existing brands count; a foreign company's first UAE location is the most important case.

FREE ZONES count: a company opening an office, HQ, branch, facility or warehouse in any UAE free zone (DMCC/JLT, DIFC, ADGM, JAFZA, DAFZ, Dubai Silicon Oasis, Dubai Internet/Media City, Dubai South, Meydan, IFZA, DWTC, Dubai Healthcare City, KEZAD, Masdar City, twofour54, SAIF Zone, Hamriyah, Shams, Ajman Free Zone, RAKEZ, Fujairah Creative City, UAQ FTZ, etc.), including "X joins DMCC" / "X sets up in ADGM" / "DIFC welcomes X".

Exclude: residential real-estate launches, product/app/menu launches with no new premises, events and festivals, closures, openings outside the UAE, government facilities (parks, roads, government offices), dining deals, brunch offers, and reviews/awards of venues that are not new. A listicle ("10 new restaurants", "openings this month") is fine - extract each named business separately.

Use ONLY facts in the item text. Never guess - use "" when absent. Give company names in English (Latin script) when the item provides them; otherwise keep the Arabic name.

Reply with ONLY a JSON array (no prose). Each element:
{"item": <item number>, "company_name": "...", "sector": "short description, e.g. 'Restaurant - Japanese', 'Retail - jewellery', 'Financial services office', 'Logistics warehouse'", "business_type": "restaurant|cafe|office|retail|clinic|hotel|school|industrial|other", "stage": "Announced|Opening soon|Recently opened", "expected_opening": "date or period if stated, e.g. 'Q1 2027', 'November 2026', else ''", "new_to_uae": "Yes if this is the company's first UAE presence, No if it already operates in the UAE, else Unknown", "origin": "home country / HQ city if stated, else ''", "emirate": "one of the seven emirates, or ''", "location": "area, emirate", "free_zone": "zone name or ''", "website": "", "phone": "", "email": "", "confidence": <0.0-1.0 that this is a genuine new UAE premises>}
Return [] if nothing qualifies."""


def norm_stage(v) -> str:
    v = str(v or "").lower()
    if "announc" in v or "plan" in v:
        return "Announced"
    if "soon" in v or "upcoming" in v:
        return "Opening soon"
    if "open" in v:
        return "Recently opened"
    return ""


def norm_yes_no(v) -> str:
    v = str(v or "").strip().lower()
    return "Yes" if v.startswith("y") else "No" if v.startswith("n") else "Unknown"


def norm_emirate(v) -> str:
    v = str(v or "").lower()
    if "ain" in v.split() or "al ain" in v:
        return "Abu Dhabi"
    for e in config.EMIRATES:
        if e.lower() in v or e.lower().replace(" ", "") in v.replace(" ", ""):
            return e
    for alias, e in (("rak", "Ras Al Khaimah"), ("uaq", "Umm Al Quwain"), ("abudhabi", "Abu Dhabi")):
        if alias in v.replace(" ", ""):
            return e
    return ""


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
{"location": "most specific address/area + emirate, e.g. 'Gate Village 3, DIFC, Dubai' or ''", "emirate": "", "free_zone": "UAE free zone name if the premises is in one, else ''", "stage": "Announced|Opening soon|Recently opened or ''", "expected_opening": "", "new_to_uae": "Yes|No|''", "origin": "", "sector": "", "website": "", "phone": "", "email": ""}"""


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
                "sector": str(r.get("sector", "")).strip(),
                "stage": norm_stage(r.get("stage", "")),
                "expected_opening": str(r.get("expected_opening", "")).strip(),
                "new_to_uae": norm_yes_no(r.get("new_to_uae", "")),
                "origin": str(r.get("origin", "")).strip(),
                "emirate": norm_emirate(r.get("emirate", "")),
                "location": str(r.get("location", "")).strip(),
                "free_zone_hint": str(r.get("free_zone", "")).strip(),
                "website": str(r.get("website", "")).strip(),
                "phone": str(r.get("phone", "")).strip(),
                "email": str(r.get("email", "")).strip(),
                "confidence": conf,
                "source": src,
            })
    return leads
