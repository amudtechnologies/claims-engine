"""Field parsers for judicial-deposit staging rows.

Every rule here was derived from real values pulled from S3 during Phase 2 planning
(see docs/phase0_schema_matrix.csv and the plan), not written from assumption. Each
returns None on anything it can't confidently parse — the caller rejects the row
rather than guessing (rule 4: no silent row loss, nothing silently wrong either).
"""

from __future__ import annotations

import re
from datetime import date, datetime

_TRAILING_OO = re.compile(r"[.,]+\s*[oO]{2}\s*$")
_VALID_CURRENCY_CHARS = re.compile(r"^-?\d[\d.,]*$")
_SEPARATOR = re.compile(r"[.,]")

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DMY_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_YYYYMMDD = re.compile(r"^(\d{4})(\d{2})(\d{2})$")

_DIGITS = re.compile(r"\d+")

# DIAN's published mod-11 weights, applied right-to-left to the NIT base
# (the NIT without its own check digit).
_NIT_WEIGHTS = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]


def parse_currency_cop(raw: object) -> int | None:
    """Colombian peso amount -> integer COP (currency stored as integer, never
    floats — cents are truncated, COP has no real sub-unit in practice).

    Handles: native numbers (most periods); thousands/decimal-ambiguous text
    (2017-1, 2018-2's real detail sheet) resolved by counting digits after the
    *last* separator (2 -> decimal, 3 -> thousands grouping); currency symbols and
    stray whitespace including non-breaking space; the handwritten "oo" cents
    marker instead of "00"; and plain float-precision noise
    (e.g. "9044965.199999999") when there's only one separator and the trailing
    digit count is neither 2 nor 3, since that's not the ambiguous case at all.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return round(raw)
    if not isinstance(raw, str):
        return None

    s = raw.replace("\xa0", " ").strip()
    s = s.replace("$", "").strip()
    s = _TRAILING_OO.sub(",00", s)
    s = s.replace(" ", "")
    if not s or not _VALID_CURRENCY_CHARS.match(s):
        return None

    negative = s.startswith("-")
    if negative:
        s = s[1:]

    separators = [m.start() for m in _SEPARATOR.finditer(s)]
    if not separators:
        value = int(s)
    else:
        last_sep = separators[-1]
        trailing = s[last_sep + 1 :]
        if len(trailing) == 2:
            integer_part = _SEPARATOR.sub("", s[:last_sep])
            if not integer_part:
                return None
            value = int(integer_part)
        elif len(trailing) == 3:
            value = int(_SEPARATOR.sub("", s))
        elif len(separators) == 1 and s[last_sep] == ".":
            try:
                value = round(float(s))
            except ValueError:
                return None
        else:
            return None

    return -value if negative else value


def parse_deposit_date(raw: object) -> date | None:
    """Deposit date -> date, regardless of which of the real shapes it arrives in:
    native Datetime (most recent periods), ISO-ish string possibly with a trailing
    00:00:00 (2018-1, 2022-1), DD/MM/YYYY string (2017-1's header states this
    format explicitly; also 2018-1, 2020-2, 2021-2, 2022-2), bare YYYYMMDD string
    (2018-2, 2019-1), or YYYYMMDD encoded as a float (2020-1 — confirmed empirically
    to be date-as-number, not an Excel date serial). 2018-1 mixes the ISO and
    DD/MM/YYYY shapes within the same column; since the three shapes are mutually
    distinguishable by pattern alone, one parser handles every period without a
    per-period format config.
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, (int, float)):
        match = _YYYYMMDD.match(str(int(raw)))
        return _safe_date(*match.groups()) if match else None
    if isinstance(raw, str):
        s = raw.strip()
        match = _ISO_DATE.match(s)
        if match:
            return _safe_date(*match.groups())
        match = _DMY_DATE.match(s)
        if match:
            day, month, year = match.groups()
            return _safe_date(year, month, day)
        match = _YYYYMMDD.match(s)
        if match:
            return _safe_date(*match.groups())
        return None
    return None


def _safe_date(year: str, month: str, day: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def normalize_id(raw: object) -> str | None:
    """Digits-only twin of a raw identifier (party ID or deposit number). A value
    with no digits at all (e.g. the literal "Desconocido" seen in 2018-2 for an
    untraceable defendant) naturally normalizes to None rather than an empty
    string or a fabricated ID — it means the source doesn't know it, not zero.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        raw = str(int(raw))
    if not isinstance(raw, str):
        return None
    digits = "".join(_DIGITS.findall(raw))
    return digits or None


def nit_check_digit(base: str) -> str:
    """DIAN's mod-11 check digit for a NIT base number (the NIT without its
    own check digit). Weights apply right-to-left; verified against DIAN's
    published worked example (base 123456789 -> check digit 6)."""
    total = sum(int(d) * w for d, w in zip(reversed(base), _NIT_WEIGHTS, strict=False))
    remainder = total % 11
    return str(remainder if remainder in (0, 1) else 11 - remainder)
