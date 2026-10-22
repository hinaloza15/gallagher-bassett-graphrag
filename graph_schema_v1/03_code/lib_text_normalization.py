"""
lib_text_normalization.py

Helper functions shared by the graph builder:
  * parse_dates_in_text()  - finds dates written in many formats and returns ISO dates
  * normalize_name()       - one canonical spelling for matching (case, '&' vs 'and', punctuation)
  * name_variants()        - spelling variants used in the notes (e.g. 'Occ' for 'Occupational')
  * fuzzy_equal()          - tolerant comparison for misspelled names (used only inside one claim)
  * slug()                 - safe ID fragment

No project data is stored here. Only standard-library code.
"""
import re
import datetime as dt
from difflib import SequenceMatcher

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

# Order matters: longer / more specific patterns first.
DATE_PATTERNS = [
    ("iso", re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b")),
    ("ddmonyy", re.compile(r"\b(\d{1,2})(" + _MON + r")(\d{2})\b", re.I)),          # 09DEC25
    ("mdy", re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")),                 # 12/9/25, 12-9-2025
    ("mon_d_y", re.compile(r"\b(" + _MON + r")\.? (\d{1,2})(?:st|nd|rd|th)?,? (20\d\d)\b", re.I)),
    ("mon_d", re.compile(r"\b(" + _MON + r")\.? (\d{1,2})(?:st|nd|rd|th)?\b(?!\s*(?:lbs|days|hrs|wks))", re.I)),
    ("md", re.compile(r"(?<![\d/$.])\b(\d{1,2})/(\d{1,2})\b(?![/\d])(?!\s*(?:lbs|\s*pain))")),  # 1/12 (not 6/10 pain)
]


def _safe_date(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def _infer_year(m, d, ref, prefer):
    """Choose the year for a month/day with no year, relative to the note date `ref`.
    prefer='past'   -> latest date on or before ref (for injury dates, events reported)
    prefer='future' -> earliest date on or after ref (for appointments, hearings)
    prefer='nearest'-> closest date either side."""
    cands = [c for c in (_safe_date(ref.year + k, m, d) for k in (-1, 0, 1)) if c]
    if not cands:
        return None
    if prefer == "past":
        past = [c for c in cands if c <= ref]
        return max(past) if past else min(cands)
    if prefer == "future":
        fut = [c for c in cands if c >= ref]
        return min(fut) if fut else max(cands)
    return min(cands, key=lambda c: abs((c - ref).days))


_NOT_DATES = [
    re.compile(r"(?i)pain(?: was| about| level| is| at| rated)?\s*(?:that day was about\s*)?\d{1,2}/10"),
    re.compile(r"(?i)\d{1,2}/10\s*(?:per|pre-tx|after|today|at the last)"),
    re.compile(r"(?i)(?:visit|session)\s*#?\d{1,2}/\d{1,2}"),
    re.compile(r"(?i)(?:strength|grip)\s*\d[+-]?/5"),
    re.compile(r"\b\d[+-]/5\b"),
    re.compile(r"(?i)\b24/7\b"),
]


def _mask_non_dates(text):
    """Blank out pain scores (6/10), PT visit counts (2/6) and strength grades (4/5)
    so they are not read as dates. Keeps string length so offsets stay valid."""
    for p in _NOT_DATES:
        text = p.sub(lambda m: " " * len(m.group(0)), text)
    return text


def parse_dates_in_text(text, ref_date, prefer="nearest"):
    """Return a list of (iso_date, start, end, raw_text, had_year) for every date found.
    ref_date: datetime.date of the note (used when the year is missing)."""
    found, taken = [], []
    original = text
    text = _mask_non_dates(text)
    for kind, pat in DATE_PATTERNS:
        for m in pat.finditer(text):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            g = m.groups()
            date, had_year = None, True
            if kind == "iso":
                date = _safe_date(g[0], g[1], g[2])
            elif kind == "ddmonyy":
                date = _safe_date(2000 + int(g[2]), MONTHS[g[1].lower()[:3] if g[1].lower()[:4] != "sept" else "sep"], g[0])
            elif kind == "mdy":
                y = int(g[2]); y = y + 2000 if y < 100 else y
                date = _safe_date(y, g[0], g[1])
            elif kind == "mon_d_y":
                date = _safe_date(g[2], MONTHS[g[0].lower().rstrip('.')[:3] if not g[0].lower().startswith('sept') else 'sep'], g[1])
            elif kind == "mon_d":
                had_year = False
                mon = MONTHS[g[0].lower().rstrip('.')[:3] if not g[0].lower().startswith('sept') else 'sep']
                date = _infer_year(mon, int(g[1]), ref_date, prefer)
            elif kind == "md":
                had_year = False
                mo, d = int(g[0]), int(g[1])
                if mo > 12:
                    continue
                date = _infer_year(mo, d, ref_date, prefer)
            if date:
                found.append((date.isoformat(), s, e, original[s:e], had_year))
                taken.append((s, e))
    found.sort(key=lambda x: x[1])
    return found


def first_date(text, ref_date, prefer="nearest"):
    r = parse_dates_in_text(text, ref_date, prefer)
    return r[0][0] if r else None


def normalize_name(s):
    """Canonical form for matching names of people and organizations."""
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\bocc\b", "occupational", s)
    s = re.sub(r"\bins\b", "insurance", s)
    s = re.sub(r"\bdept\b", "department", s)
    s = re.sub(r"\bphysical therapy\b", "pt", s)
    s = re.sub(r"\b(dr|rn)\b\.?", "", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def name_variants(name):
    """Spelling variants that appear in the notes for organization names."""
    v = {name, name.replace("&", "and"), name.replace(" and ", " & ")}
    v |= {x.replace("Occupational", "Occ") for x in list(v)}
    v |= {x.replace("Department", "Dept") for x in list(v)}
    v |= {x.upper() for x in list(v)} | {x.title() for x in list(v)}
    return sorted(v)


def fuzzy_equal(a, b, threshold=0.86):
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio() >= threshold


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", normalize_name(s)).strip("-")


def money_values(text):
    """All dollar amounts in text as floats."""
    return [float(x.replace(",", "")) for x in re.findall(r"\$\s?([\d,]+(?:\.\d+)?)", text)]


def split_history_paragraph(text):
    """Many notes repeat a copied claim history after the main entry, starting with 'DOI ...'
    on a new line. Returns (main_text, history_text, history_offset)."""
    m = re.search(r"\n(DOI\b)", text)
    if not m:
        return text, "", None
    return text[:m.start()], text[m.start() + 1:], m.start() + 1
