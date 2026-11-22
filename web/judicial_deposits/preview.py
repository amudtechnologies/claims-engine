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

from home.templatetags.home_extras import cop

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
    name = _LEADING_CODE.sub("", raw).strip() or raw.strip()
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


def _faded(deposit: Deposit) -> PreviewRow:
    """A placeholder row: only its shape and a few leading characters."""
    first_word = court_display_name(deposit.court_office).split()[0]
    return PreviewRow(
        court=f"{first_word} {MASK * 14}",
        city=MASK * 10,
        deposit_no=mask_digits(deposit.deposit_no, DEPOSIT_NO_VISIBLE),
        court_account=mask_digits(deposit.court_account, COURT_ACCOUNT_VISIBLE),
        constituted_on=mask_date(deposit.constituted_on),
        amount=f"$ {MASK * 2}.{MASK * 3}.{MASK * 3}",
    )


def build_preview(deposits: list[Deposit]) -> DepositPreview | None:
    """Largest deposit first (ties: oldest, then by id, so the same party
    always shows the same row), then up to FADED_ROWS placeholders."""
    if not deposits:
        return None
    ordered = sorted(
        deposits,
        key=lambda d: (-d.amount_cop, d.constituted_on or date.max, d.claim_id),
    )
    first, rest = ordered[0], ordered[1:]
    return DepositPreview(
        visible=_readable(first),
        faded=[_faded(deposit) for deposit in rest[:FADED_ROWS]],
        remaining_count=len(rest),
        remaining_amount_cop=sum(deposit.amount_cop for deposit in rest),
    )
