"""Google Sheets output (service account), dedupe keys, opt-outs and retention."""
import json
import os
import re
import urllib.parse
from datetime import date, timedelta

from . import config, freezones

_SUFFIX = re.compile(r"\b(the|and|llc|l l c|fze|fzco|fz llc|fzc|dmcc|est|establishment|co|company|ltd|limited|"
                     r"trading|group|uae|dubai|abu dhabi|sharjah)\b")


def norm_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    n = _SUFFIX.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def norm_site(url: str) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    # social profile URLs aren't a company identity
    return "" if any(s in host for s in ("instagram.", "facebook.", "linkedin.", "tiktok.", "x.com")) else host


# ---- opt-out list ----------------------------------------------------------------
def load_optouts(path: str | None = None) -> set[str]:
    """Lines may be company names, domains, phone numbers or emails. '#' starts a comment."""
    out = set()
    try:
        with open(path or config.OPTOUT_FILE, encoding="utf-8") as f:
            for line in f:
                v = line.split("#", 1)[0].strip()
                if v:
                    out |= {v.lower(), norm_name(v), norm_site(v), re.sub(r"\D", "", v)[-9:]}
    except FileNotFoundError:
        pass
    return out - {""}


def is_opted_out(lead: dict, optouts: set[str]) -> bool:
    if not optouts:
        return False
    keys = {norm_name(lead["company_name"]), norm_site(lead["website"]), lead["email"].lower()}
    keys |= {re.sub(r"\D", "", p)[-9:] for p in lead["phone"].split(",") if p.strip()}
    return bool((keys - {""}) & optouts)


# ---- Google Sheets ---------------------------------------------------------------
def open_worksheet():
    import gspread  # imported lazily so --dry-run works without it

    creds = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = gspread.service_account_from_dict(creds)
    sh = gc.open_by_key(config.SHEET_ID)
    try:
        ws = sh.worksheet(config.WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        first = sh.sheet1
        head = first.row_values(1)
        if not head or head == config.HEADERS[:len(head)]:
            ws = first                      # adopt the empty / header-only first tab
            ws.update_title(config.WORKSHEET_NAME)
        else:
            ws = sh.add_worksheet(config.WORKSHEET_NAME, rows=1000, cols=len(config.HEADERS))

    head = ws.row_values(1)
    if head != config.HEADERS and (not head or head == config.HEADERS[:len(head)]):
        # new sheet, or an older header missing newer columns (e.g. FREE ZONE) -> write full header
        if ws.col_count < len(config.HEADERS):
            ws.add_cols(len(config.HEADERS) - ws.col_count)
        ws.update(range_name="A1", values=[config.HEADERS])
        ws.freeze(rows=1)

    ensure_reference_tab(sh, gspread)
    return ws


def ensure_reference_tab(sh, gspread):
    """A static tab listing each free zone and its official register for manual verification."""
    rows = freezones.reference_rows()
    try:
        ref = sh.worksheet(config.REFERENCE_TAB)
        if ref.row_values(1) == rows[0] and len(ref.col_values(1)) == len(rows):
            return
        ref.clear()
    except gspread.WorksheetNotFound:
        ref = sh.add_worksheet(config.REFERENCE_TAB, rows=len(rows) + 5, cols=len(rows[0]))
    ref.update(range_name="A1", values=rows, value_input_option="RAW")
    ref.freeze(rows=1)


def existing_keys(ws) -> tuple[set, set]:
    rows = ws.get_all_values()[1:]
    names = {norm_name(r[1]) for r in rows if len(r) > 1 and r[1]}
    sites = {norm_site(r[5]) for r in rows if len(r) > 5 and r[5]} - {""}
    return names, sites


def append(ws, rows: list[list[str]]):
    if rows:
        # RAW keeps "+971 ..." as text instead of Sheets parsing it as a formula/number
        ws.append_rows(rows, value_input_option="RAW", insert_data_option="INSERT_ROWS")


def rows_to_expire(values: list[list[str]], days: int, today: date) -> list[int]:
    """1-based sheet row numbers whose DATE is older than `days` (header excluded)."""
    if days <= 0:
        return []
    cutoff = (today - timedelta(days=days)).isoformat()
    return [i for i, r in enumerate(values[1:], start=2) if r and r[0] and r[0] < cutoff]


def apply_retention(ws, today: date) -> int:
    old = rows_to_expire(ws.get_all_values(), config.RETENTION_DAYS, today)
    # group into contiguous blocks and delete bottom-up so indices stay valid
    blocks, start = [], None
    for i, r in enumerate(old):
        if start is None:
            start = r
        if i + 1 == len(old) or old[i + 1] != r + 1:
            blocks.append((start, r))
            start = None
    for a, b in reversed(blocks):
        ws.delete_rows(a, b)
    return len(old)
