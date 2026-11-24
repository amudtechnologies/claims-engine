"""The detail page's "Publicaciones anteriores" list: one summary row per
publication, and, when one is opened, its five largest deposits followed by
a WhatsApp contact for the rest.

Built server-side per request from the visitor's query string (`pub`),
so the page never ships a party's whole history: a NIT with 1.400+
deposits still renders five rows. Deposit
numbers, judicial accounts and constitution dates (year only) are masked
exactly like the open-window
preview (preview.py, D29); the counterparty is never shown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from home.templatetags.home_extras import cop

from . import party_search, preview
from .party_search import Deposit

# Deposits listed per opened publication.
SAMPLE_SIZE = 5
# Publications listed; older ones only as a count behind "Contactar".
VISIBLE_PUBLICATIONS = 3

ROLE_LABELS = {"plaintiff": "Demandante", "defendant": "Demandado"}


@dataclass(frozen=True)
class PublicationGroup:
    period: str
    closes_on: date | None
    deposit_count: int
    court_count: int
    amount_cop: int


@dataclass(frozen=True)
class HistoryRow:
    court: str
    city: str
    deposit_no: str
    court_account: str
    constituted_on: str
    role: str
    # Shown: formatted, or masked on a natural person's page.
    amount: str
    # Only for sums, never rendered.
    amount_cop: int


def publication_groups(deposits: list[Deposit]) -> list[PublicationGroup]:
    """One group per publication, newest first. Deposits with no known
    period are left out of the list (they still count in the totals)."""
    by_period: dict[str, list[Deposit]] = {}
    for deposit in deposits:
        if deposit.period:
            by_period.setdefault(deposit.period, []).append(deposit)
    groups = []
    for period in sorted(by_period, reverse=True):
        members = by_period[period]
        window = party_search.claim_window(period)
        groups.append(
            PublicationGroup(
                period=period,
                closes_on=window.closes_on if window else None,
                deposit_count=len(members),
                court_count=len({d.court_account or d.court_office for d in members}),
                amount_cop=sum(d.amount_cop for d in members),
            )
        )
    return groups


def publication_sample(
    deposits: list[Deposit], period: str, masked: bool = False
) -> list[HistoryRow]:
    """A publication's SAMPLE_SIZE largest deposits, masked. `masked` (a
    natural person's page) cuts court, city and amount to two characters
    and masks the role."""
    members = sorted(
        (d for d in deposits if d.period == period),
        key=lambda d: (-d.amount_cop, d.constituted_on or date.max, d.claim_id),
    )
    return [
        HistoryRow(
            court=(
                preview.mask_text(preview.court_display_name(d.court_office))
                if masked
                else preview.court_display_name(d.court_office)
            ),
            city=(
                preview.mask_text(preview.city_display_name(d.city))
                if masked
                else preview.city_display_name(d.city)
            ),
            deposit_no=preview.mask_digits(d.deposit_no, preview.DEPOSIT_NO_VISIBLE),
            court_account=preview.mask_digits(d.court_account, preview.COURT_ACCOUNT_VISIBLE),
            constituted_on=preview.mask_date(d.constituted_on),
            role=preview.MASK * 10 if masked else ROLE_LABELS.get(d.procedural_role, "—"),
            amount=preview.mask_amount(d.amount_cop) if masked else cop(d.amount_cop),
            amount_cop=d.amount_cop,
        )
        for d in members[:SAMPLE_SIZE]
    ]
