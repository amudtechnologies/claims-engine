"""The detail page's deposit preview: one readable row, the rest faded out.

Everything a visitor must not read is masked HERE, server-side. The faded
rows reach the browser already as placeholders ("46001••••••••••",
"$ ••.•••.•••"); hiding real values with CSS blur would protect nothing,
since anyone can read them from the page source. The readable row still
masks its deposit number, judicial account and the day and month of the
constitution date: the full detail is what the
"Contactar" call to action offers.

Never shows the counterparty: a deposit's other party (often a cédula) is
not this visitor's data.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from home.templatetags.home_extras import cop, mask_cop

from .party_search import Deposit

MASK = "•"
# Faded rows under the readable one; each is dimmer than the one above.
FADED_ROWS = 3
# Leading digits left visible in a masked deposit number / judicial account.
DEPOSIT_NO_VISIBLE = 5
COURT_ACCOUNT_VISIBLE = 4

# Words kept lower case inside a court name ("Juzgado de Ejecución...").
_SMALL_WORDS = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "para"}
# A court name often starts with its code: "680014303000-OFICINA...",
# "080014003004 Juz 004...", "8 Juz 008...".
_LEADING_CODE = re.compile(r"^\s*\d+\s*-?\s*(?=\D)")


@dataclass(frozen=True)
class PreviewRow:
    court: str
    city: str
    deposit_no: str
    court_account: str
    constituted_on: str
    amount: str


@dataclass(frozen=True)
class DepositPreview:
    visible: PreviewRow
    faded: list[PreviewRow]
    remaining_count: int
    remaining_amount_cop: int


def mask_digits(value: str | None, visible: int) -> str:
    """Keep the first `visible` characters, mask the rest; "—" when unknown."""
    if not value:
        return "—"
    value = value.strip()
    return value[:visible] + MASK * max(len(value) - visible, 0)


def mask_date(value: date | None) -> str:
    """Constitution date with day and month masked: "••/••/2023"."""
    if not value:
        return "—"
    return f"{MASK * 2}/{MASK * 2}/{value.year}"


def court_display_name(raw: str | None) -> str:
    """"680014303000-OFICINA EJECU CIVIL MPAL BUCARAMANGA" ->
    "Oficina Ejecu Civil Mpal Bucaramanga". Drops the leading code and fixes
    the casing; the source's own abbreviations stay as published."""
    if not raw or not raw.strip():
        return "Despacho sin nombre"
    # "410014189005-005 MUN PEQ..." keeps its court number: "005 Mun Peq...".
    name = _LEADING_CODE.sub("", raw).strip().lstrip("-").strip() or raw.strip()
    words = []
    for index, word in enumerate(name.split()):
        lower = word.lower()
        if any(character.isdigit() for character in word):
            words.append(word)
        elif index and lower in _SMALL_WORDS:
            words.append(lower)
        else:
            words.append(lower[:1].upper() + lower[1:])
    return " ".join(words)


def city_display_name(raw: str | None) -> str:
    """One spelling per city: the source writes "Bogota", "BOGOTA",
    "Bogotá, D.C."... Bogotá gets its accent and "D.C."; other cities are
    title-cased as published (accents the source omits stay omitted)."""
    if not raw or not raw.strip():
        return "—"
    name = " ".join(raw.replace(",", " ").split()).strip(" .")
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)
    ).lower()
    if folded.startswith("bogota"):
        return "Bogotá D.C."
    return court_display_name(name)


def _readable(deposit: Deposit) -> PreviewRow:
    return PreviewRow(
        court=court_display_name(deposit.court_office),
        city=city_display_name(deposit.city),
        deposit_no=mask_digits(deposit.deposit_no, DEPOSIT_NO_VISIBLE),
        court_account=mask_digits(deposit.court_account, COURT_ACCOUNT_VISIBLE),
        constituted_on=mask_date(deposit.constituted_on),
        amount=cop(deposit.amount_cop),
    )


MASKED_CITY = MASK * 10
# A natural person's page: court, city and amount keep only this many
# leading letters / digits.
NATURAL_PERSON_VISIBLE = 2


def mask_text(value: str, visible: int = NATURAL_PERSON_VISIBLE) -> str:
    """"Juz 006 Civil Municipal Pereira" -> "Ju••••••••••••"."""
    return value[:visible] + MASK * 12 if value and value != "—" else value


def mask_amount(amount_cop: int) -> str:
    """A natural person's amount: "$ 36.161.788" -> "$ 36.•••.•••"."""
    return mask_cop(amount_cop, NATURAL_PERSON_VISIBLE)
MASKED_AMOUNT = f"$ {MASK * 2}.{MASK * 3}.{MASK * 3}"


def masked_court(raw: str | None) -> str:
    """A court reduced to its first word: "Juz ••••••••••••••"."""
    return f"{court_display_name(raw).split()[0]} {MASK * 14}"


def _masked_row(deposit: Deposit, hide_amount: bool = True) -> PreviewRow:
    """Two leading letters / digits of court, city and amount; the numbers
    and date as in any other row. A natural person's rows, and a lone
    deposit's (one readable row would be the whole finding), which keeps
    its amount in clear unless it belongs to a natural person."""
    return PreviewRow(
        court=mask_text(court_display_name(deposit.court_office)),
        city=mask_text(city_display_name(deposit.city)),
        deposit_no=mask_digits(deposit.deposit_no, DEPOSIT_NO_VISIBLE),
        court_account=mask_digits(deposit.court_account, COURT_ACCOUNT_VISIBLE),
        constituted_on=mask_date(deposit.constituted_on),
        amount=mask_amount(deposit.amount_cop) if hide_amount else cop(deposit.amount_cop),
    )


def _faded(deposit: Deposit) -> PreviewRow:
    """A placeholder row: only its shape and a few leading characters."""
    return PreviewRow(
        court=masked_court(deposit.court_office),
        city=MASKED_CITY,
        deposit_no=mask_digits(deposit.deposit_no, DEPOSIT_NO_VISIBLE),
        court_account=mask_digits(deposit.court_account, COURT_ACCOUNT_VISIBLE),
        constituted_on=mask_date(deposit.constituted_on),
        amount=MASKED_AMOUNT,
    )


def build_preview(deposits: list[Deposit], masked: bool = False) -> DepositPreview | None:
    """Largest deposit first (ties: oldest, then by id, so the same party
    always shows the same row), then up to FADED_ROWS placeholders.
    `masked` (a natural person's page) builds every row, the first one
    included, with court, city and amount cut to two characters. A single
    deposit gets court and city masked whatever the party's type."""
    if not deposits:
        return None
    ordered = sorted(
        deposits,
        key=lambda d: (-d.amount_cop, d.constituted_on or date.max, d.claim_id),
    )
    first, rest = ordered[0], ordered[1:]
    if not rest:
        # A single deposit is the whole finding: court and city masked; the
        # amount too only on a natural person's page.
        visible = _masked_row(first, hide_amount=masked)
    else:
        visible = _masked_row(first) if masked else _readable(first)
    return DepositPreview(
        visible=visible,
        faded=[
            _masked_row(deposit) if masked else _faded(deposit)
            for deposit in rest[:FADED_ROWS]
        ],
        remaining_count=len(rest),
        remaining_amount_cop=sum(deposit.amount_cop for deposit in rest),
    )
