"""The detail page's "Publicaciones anteriores" list: one summary row per
publication, and one publication's deposits, ten at a time, when opened.

Built server-side per request from the visitor's query string (`pub`,
`page`, `todas`), so the page never ships a party's whole
history: a NIT with 1.400+ deposits still renders one page of ten. Deposit
numbers, judicial accounts and constitution dates (year only) are masked
exactly like the open-window
preview (preview.py, D29); the counterparty is never shown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import ceil

from . import party_search, preview
from .party_search import Deposit

PAGE_SIZE = 10
# Publications listed before "Ver N publicaciones más".
VISIBLE_PUBLICATIONS = 8

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
    amount_cop: int


@dataclass(frozen=True)
class PageInfo:
    page: int
    pages: int
    start: int
    end: int
    total: int
    # Page numbers to link, with None where the pager shows "…".
    links: list[int | None]


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


def _pager_links(page: int, pages: int) -> list[int | None]:
    """1 … 4 5 6 … 19: first, last, and the neighbours of the current page."""
    wanted = {1, pages, page - 1, page, page + 1}
    links: list[int | None] = []
    for number in range(1, pages + 1):
        if number in wanted:
            links.append(number)
        elif links and links[-1] is not None:
            links.append(None)
    return links


def publication_page(
    deposits: list[Deposit], period: str, page: int
) -> tuple[list[HistoryRow], PageInfo]:
    """One page of a publication's deposits, largest first."""
    members = sorted(
        (d for d in deposits if d.period == period),
        key=lambda d: (-d.amount_cop, d.constituted_on or date.max, d.claim_id),
    )
    total = len(members)
    pages = max(ceil(total / PAGE_SIZE), 1)
    page = min(max(page, 1), pages)
    start = (page - 1) * PAGE_SIZE
    rows = [
        HistoryRow(
            court=preview.court_display_name(d.court_office),
            city=preview.city_display_name(d.city),
            deposit_no=preview.mask_digits(d.deposit_no, preview.DEPOSIT_NO_VISIBLE),
            court_account=preview.mask_digits(d.court_account, preview.COURT_ACCOUNT_VISIBLE),
            constituted_on=preview.mask_date(d.constituted_on),
            role=ROLE_LABELS.get(d.procedural_role, "—"),
            amount_cop=d.amount_cop,
        )
        for d in members[start : start + PAGE_SIZE]
    ]
    info = PageInfo(
        page=page,
        pages=pages,
        start=start + 1 if total else 0,
        end=min(start + PAGE_SIZE, total),
        total=total,
        links=_pager_links(page, pages),
    )
    return rows, info
