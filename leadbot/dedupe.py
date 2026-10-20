"""Duplicate detection and merging.

Two leads are the same company when ANY of these match:
  - normalised name (exact, or fuzzy: "ROKA" = "Roka Dubai", "Cafe Bateel" = "Bateel")
  - website domain
  - email address
  - phone number (last 9 digits)
Duplicates found in the same run are MERGED into one row (blank fields filled from the
others, extra sources listed). Leads matching a row already in the sheet are dropped.
"""
import difflib
import re

from .contacts import normalize_phone
from .sheet import norm_name, norm_site

GENERIC = {
    "al", "el", "de", "la", "le", "by", "of", "new", "restaurant", "restaurants", "cafe", "coffee", "kitchen",
    "bar", "grill", "lounge", "bistro", "eatery", "bakery", "store", "shop", "boutique", "clinic", "medical",
    "centre", "center", "hotel", "resort", "gym", "fitness", "studio", "salon", "spa", "beauty", "academy",
    "school", "office", "gold", "diamonds", "diamond", "jewellery", "jewelry", "jewellers", "securities",
    "capital", "bank", "international", "global", "middle", "east", "mena", "gulf", "holding", "holdings",
    "solutions", "services", "technologies", "technology", "tech", "digital", "properties", "real", "estate",
    "partners", "consulting", "investments", "investment", "ventures", "logistics", "branch", "flagship",
}


def phone_keys(phone_field: str) -> set[str]:
    """'+971 4 321 7788', '04 321 7788' and '00971 4 3217788' all give the same key."""
    keys = set()
    for p in (phone_field or "").split(","):
        p = p.split("(")[0]                               # drop "(mobile - may be personal)"
        norm = normalize_phone(p)
        d = re.sub(r"\D", "", norm or p)
        if len(d) >= 7:
            keys.add(d[-9:] if norm else d[-8:])
    return keys


def distinctive_tokens(norm: str) -> set[str]:
    return {t for t in norm.split() if len(t) >= 3 and t not in GENERIC}


def same_name(a: str, b: str) -> bool:
    """a, b are already norm_name()'d."""
    if not a or not b:
        return False
    if a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.88:
        return True
    ta, tb = set(a.split()), set(b.split())
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    # every word of the shorter name appears in the longer one, and it has a distinctive word
    return short <= long_ and bool(distinctive_tokens(" ".join(short)))


class Index:
    """Lookup of known companies -> an id (row index in the run, or -1 for sheet rows)."""

    def __init__(self):
        self.names: list[tuple[str, int]] = []
        self.sites: dict[str, int] = {}
        self.emails: dict[str, int] = {}
        self.phones: dict[str, int] = {}

    def add(self, name: str, website: str = "", email: str = "", phone: str = "", ident: int = -1):
        n = norm_name(name)
        if n:
            self.names.append((n, ident))
        if s := norm_site(website):
            self.sites.setdefault(s, ident)
        if email:
            self.emails.setdefault(email.lower().strip(), ident)
        for k in phone_keys(phone):
            self.phones.setdefault(k, ident)

    def add_lead(self, lead: dict, ident: int = -1):
        self.add(lead["company_name"], lead.get("website", ""), lead.get("email", ""), lead.get("phone", ""), ident)

    def add_sheet_row(self, row: list[str], header: list[str]):
        """Index a sheet row by column NAME, so older and newer sheet layouts both work."""
        def col(name):
            i = header.index(name) if name in header else -1
            return row[i] if 0 <= i < len(row) else ""
        self.add(col("COMPANY NAME"), col("WEBSITE"), col("EMAIL"), col("CONTACT NUMBER"))

    def match(self, lead: dict) -> int | None:
        if (s := norm_site(lead.get("website", ""))) and s in self.sites:
            return self.sites[s]
        if (e := lead.get("email", "").lower().strip()) and e in self.emails:
            return self.emails[e]
        for k in phone_keys(lead.get("phone", "")):
            if k in self.phones:
                return self.phones[k]
        n = norm_name(lead["company_name"])
        for other, ident in self.names:
            if same_name(n, other):
                return ident
        return None


def merge_into(keep: dict, dup: dict):
    """Fill keep's blank fields from dup and remember dup's source."""
    for f in ("phone", "email", "website", "location", "free_zone_hint", "business_type", "sector", "stage",
              "expected_opening", "origin", "emirate"):
        if not keep.get(f) and dup.get(f):
            keep[f] = dup[f]
    if keep.get("new_to_uae", "Unknown") == "Unknown" and dup.get("new_to_uae") in ("Yes", "No"):
        keep["new_to_uae"] = dup["new_to_uae"]
    if len(dup.get("location", "")) > len(keep.get("location", "")) and "," in dup.get("location", ""):
        keep["location"] = dup["location"]          # more specific location wins
    keep.setdefault("extra_sources", [])
    for s in [dup["source"], *dup.get("extra_sources", [])]:
        if s.url != keep["source"].url and all(s.url != x.url for x in keep["extra_sources"]):
            keep["extra_sources"].append(s)


def merge_within(leads: list[dict]) -> list[dict]:
    """Collapse duplicates inside one batch (highest-confidence lead is kept)."""
    out, idx = [], Index()
    for lead in sorted(leads, key=lambda l: -l.get("confidence", 0)):
        m = idx.match(lead)
        if m is None:
            idx.add_lead(lead, len(out))
            out.append(lead)
        else:
            merge_into(out[m], lead)
    return out
