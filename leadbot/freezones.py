"""UAE free zones: detection, search queries and official verification links.

No UAE free zone publishes a feed/API of newly registered companies, and directory terms
(e.g. DMCC's) prohibit copying listings or using them for marketing. So the bot DISCOVERS
free-zone openings from news / social posts, TAGS each lead with its zone, and gives the
sales team the official register link to VERIFY manually. It never scrapes the directories.
"""
import re
from dataclasses import dataclass, field

NER_URL = ("https://u.ae/en/information-and-services/business/important-digital-services/"
           "national-economic-register")


@dataclass
class Zone:
    code: str
    name: str
    emirate: str
    aliases: list[str] = field(default_factory=list)   # names, acronyms, areas inside the zone
    directory: str = ""                                 # official public directory / register

    @property
    def verify_url(self) -> str:
        return self.directory or NER_URL


ZONES = [
    # ---- Dubai
    Zone("DMCC", "DMCC Free Zone", "Dubai",
         ["DMCC", "Dubai Multi Commodities Centre", "Jumeirah Lakes Towers", "JLT", "Uptown Dubai", "Almas Tower"],
         "https://dmcc.ae/business-directory"),
    Zone("DIFC", "Dubai International Financial Centre", "Dubai",
         ["DIFC", "Dubai International Financial Centre", "Gate Village", "ICD Brookfield"],
         "https://www.difc.com/business/public-register"),
    Zone("JAFZA", "Jebel Ali Free Zone", "Dubai", ["JAFZA", "Jafza", "Jebel Ali Free Zone"]),
    Zone("DAFZ", "Dubai Airport Freezone", "Dubai",
         ["DAFZ", "DAFZA", "Dubai Airport Freezone", "Dubai Airport Free Zone"]),
    Zone("DSO", "Dubai Silicon Oasis", "Dubai", ["Dubai Silicon Oasis", "DSO", "DTEC"]),
    Zone("DIC", "Dubai Internet City", "Dubai", ["Dubai Internet City", "in5"],
         "https://dic.ae/the-community/community-directory"),
    Zone("DMC", "Dubai Media City", "Dubai", ["Dubai Media City"],
         "https://dic.ae/the-community/community-directory"),
    Zone("DKP", "Dubai Knowledge Park", "Dubai", ["Dubai Knowledge Park"]),
    Zone("DIAC", "Dubai International Academic City", "Dubai", ["Dubai International Academic City"]),
    Zone("D3", "Dubai Design District", "Dubai", ["Dubai Design District"]),
    Zone("DPC", "Dubai Production City", "Dubai", ["Dubai Production City"]),
    Zone("DSC", "Dubai Studio City", "Dubai", ["Dubai Studio City"]),
    Zone("DSP", "Dubai Science Park", "Dubai", ["Dubai Science Park"]),
    Zone("DOC", "Dubai Outsource City", "Dubai", ["Dubai Outsource City"]),
    Zone("DIC-IND", "Dubai Industrial City", "Dubai", ["Dubai Industrial City"]),
    Zone("DS", "Dubai South", "Dubai", ["Dubai South", "Dubai World Central", "DWC Logistics District"]),
    Zone("EXPO", "Expo City Dubai", "Dubai", ["Expo City Dubai", "Expo City"]),
    Zone("MFZ", "Meydan Free Zone", "Dubai", ["Meydan Free Zone"]),
    Zone("IFZA", "IFZA Dubai", "Dubai", ["IFZA", "International Free Zone Authority", "Dubai Digital Park"]),
    Zone("DWTC", "DWTC Free Zone", "Dubai",
         ["DWTC Free Zone", "Dubai World Trade Centre Free Zone", "One Central"]),
    Zone("DHCC", "Dubai Healthcare City", "Dubai", ["Dubai Healthcare City", "DHCC"]),
    Zone("DCC", "Dubai CommerCity", "Dubai", ["Dubai CommerCity"]),
    Zone("DMAC", "Dubai Maritime City", "Dubai", ["Dubai Maritime City"]),
    # ---- Abu Dhabi
    Zone("ADGM", "Abu Dhabi Global Market", "Abu Dhabi",
         ["ADGM", "Abu Dhabi Global Market", "Al Maryah Island", "Al Reem Island", "Hub71"],
         "https://adgm.com/public-registers"),
    Zone("KEZAD", "KEZAD (Khalifa Economic Zones)", "Abu Dhabi",
         ["KEZAD", "KIZAD", "Khalifa Economic Zones", "Khalifa Industrial Zone"]),
    Zone("MASDAR", "Masdar City Free Zone", "Abu Dhabi", ["Masdar City"]),
    Zone("TWOFOUR54", "twofour54", "Abu Dhabi", ["twofour54", "Yas Creative Hub"]),
    Zone("ADAFZ", "Abu Dhabi Airport Free Zone", "Abu Dhabi", ["Abu Dhabi Airport Free Zone", "ADAFZ"]),
    # ---- Sharjah
    Zone("SAIF", "SAIF Zone", "Sharjah", ["SAIF Zone", "Sharjah Airport International Free Zone"]),
    Zone("HFZA", "Hamriyah Free Zone", "Sharjah", ["Hamriyah Free Zone", "HFZA"]),
    Zone("SHAMS", "Sharjah Media City (Shams)", "Sharjah", ["Sharjah Media City", "SHAMS"]),
    Zone("SPC", "Sharjah Publishing City", "Sharjah", ["Sharjah Publishing City"]),
    Zone("SRTIP", "Sharjah Research Technology & Innovation Park", "Sharjah",
         ["Sharjah Research, Technology and Innovation Park", "Sharjah Research Technology and Innovation Park",
          "SRTI Park", "SRTIP"]),
    # ---- Northern Emirates
    Zone("AFZ", "Ajman Free Zone", "Ajman", ["Ajman Free Zone", "AFZA"]),
    Zone("AMC", "Ajman Media City Free Zone", "Ajman", ["Ajman Media City"]),
    Zone("RAKEZ", "RAKEZ", "Ras Al Khaimah", ["RAKEZ", "Ras Al Khaimah Economic Zone", "Al Hamra Industrial Zone"]),
    Zone("FCC", "Fujairah Creative City", "Fujairah", ["Fujairah Creative City"]),
    Zone("FFZ", "Fujairah Free Zone", "Fujairah", ["Fujairah Free Zone"]),
    Zone("UAQFTZ", "Umm Al Quwain Free Trade Zone", "Umm Al Quwain",
         ["Umm Al Quwain Free Trade Zone", "UAQ FTZ", "UAQ Free Trade Zone"]),
]


def _pattern(alias: str) -> re.Pattern:
    # Short ALL-CAPS acronyms match case-sensitively to avoid noise ("dso", "shams" as a word)
    flags = 0 if (alias.isupper() and len(alias) <= 7) or alias == "in5" else re.I
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])", flags)


_MATCHERS = [(z, _pattern(a)) for z in ZONES for a in [z.name, *z.aliases]]
_BY_CODE = {z.code: z for z in ZONES}


def detect(*texts: str) -> Zone | None:
    """Return the first free zone mentioned in the given texts (checked in order)."""
    for text in texts:
        if not text:
            continue
        for zone, pat in _MATCHERS:
            if pat.search(text):
                return zone
    return None


def by_code(code: str) -> Zone | None:
    return _BY_CODE.get((code or "").strip().upper())


# ---- Search queries --------------------------------------------------------------
_OPEN_TERMS = 'opens OR "new office" OR welcomes OR "sets up" OR inaugurates OR "regional headquarters" OR "now open"'


def news_queries() -> list[str]:
    """One Google News query per zone (Google's OR binds tighter than AND)."""
    return [f'"{z.aliases[0] if z.aliases else z.name}" {_OPEN_TERMS}' for z in ZONES]


def web_queries() -> list[str]:
    """Social / web queries grouped by emirate to keep paid search calls low."""
    groups: dict[str, list[str]] = {}
    for z in ZONES:
        groups.setdefault(z.emirate, []).append(f'"{z.aliases[0] if z.aliases else z.name}"')
    out = []
    for emirate, names in groups.items():
        for i in range(0, len(names), 8):          # keep each query short enough for search engines
            zone_or = " OR ".join(names[i:i + 8])
            out.append(f'site:linkedin.com/posts ("new office" OR "opened" OR "licensed") ({zone_or})')
            out.append(f'site:instagram.com ("now open" OR "opening soon" OR "new office") ({zone_or})')
    return out


def reference_rows() -> list[list[str]]:
    """Rows for the 'Free Zone Directories' reference tab."""
    rows = [["CODE", "FREE ZONE", "EMIRATE", "AREAS / KEYWORDS", "VERIFY HERE (official)", "NOTE"]]
    for z in ZONES:
        note = ("Public directory - manual lookup only; DMCC terms prohibit copying or marketing use"
                if z.code == "DMCC" else
                "Public register - manual lookup" if z.directory else
                "No public directory - verify licence on the National Economic Register")
        rows.append([z.code, z.name, z.emirate, ", ".join(z.aliases), z.verify_url, note])
    return rows
