"""Aggregate charts for the detail page's "Histórico completo" block.

Every aggregation happens here, server-side, over one party's deposits; the
template and the browser only ever receive the per-group totals in `Chart`
— never individual deposits, and never a court office's name (the per-court
detail is part of the paid service). Each chart is a full partition of the
deposits it was given: every deposit lands in exactly one bar, so each
chart's counts and amounts add up to the historical totals. A deposit
missing the field a chart groups by goes to "Sin dato", never dropped.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from django.conf import settings

from .party_search import Deposit

NO_DATA = "Sin dato"
OTHERS = "Otros"

# Below this many historical deposits the chart section isn't shown at all.
# Override with `JD_CHARTS_MIN_FINDINGS` in settings.
DEFAULT_MIN_FINDINGS = 10

TOP_DEPARTMENTS = 10

# (label, lower bound inclusive, upper bound exclusive), in COP.
AMOUNT_RANGES = [
    ("< $1M", 0, 1_000_000),
    ("$1M–$10M", 1_000_000, 10_000_000),
    ("$10M–$100M", 10_000_000, 100_000_000),
    ("≥ $100M", 100_000_000, None),
]

# DANE department codes — the first two digits of a court's `court_account`
# (its first five are the municipality's DANE code). Preferred over
# `core/court.department`, a free-text column with dozens of spellings and
# city names mixed in ("VALLE", "Valle Del Cauca", "CALI", "Nari¥o", ...).
DANE_DEPARTMENTS = {
    "05": "Antioquia",
    "08": "Atlántico",
    "11": "Bogotá D.C.",
    "13": "Bolívar",
    "15": "Boyacá",
    "17": "Caldas",
    "18": "Caquetá",
    "19": "Cauca",
    "20": "Cesar",
    "23": "Córdoba",
    "25": "Cundinamarca",
    "27": "Chocó",
    "41": "Huila",
    "44": "La Guajira",
    "47": "Magdalena",
    "50": "Meta",
    "52": "Nariño",
    "54": "Norte de Santander",
    "63": "Quindío",
    "66": "Risaralda",
    "68": "Santander",
    "70": "Sucre",
    "73": "Tolima",
    "76": "Valle del Cauca",
    "81": "Arauca",
    "85": "Casanare",
    "86": "Putumayo",
    "88": "San Andrés y Providencia",
    "91": "Amazonas",
    "94": "Guainía",
    "95": "Guaviare",
    "97": "Vaupés",
    "99": "Vichada",
}

@dataclass(frozen=True)
class Bar:
    label: str
    count: int
    amount_cop: int
    highlight: bool = False


@dataclass(frozen=True)
class Chart:
    slug: str
    title: str
    # Header of the label column in the chart's data table.
    dimension: str
    # What the bar length encodes: "count" or "amount".
    measure: str
    orientation: str  # "vertical" | "horizontal"
    bars: list[Bar]
    summary: str = ""

    @property
    def highlighted(self) -> str | None:
        """The label of the highlighted bar (a publication period), if any."""
        return next((bar.label for bar in self.bars if bar.highlight), None)

    @property
    def total_count(self) -> int:
        return sum(bar.count for bar in self.bars)

    @property
    def total_amount_cop(self) -> int:
        return sum(bar.amount_cop for bar in self.bars)


def min_findings() -> int:
    return getattr(settings, "JD_CHARTS_MIN_FINDINGS", DEFAULT_MIN_FINDINGS)


def department(court_account: str | None) -> str:
    if not court_account or not court_account.isdigit() or len(court_account) < 5:
        return NO_DATA
    return DANE_DEPARTMENTS.get(court_account[:2], NO_DATA)


def amount_range(amount_cop: int) -> str:
    for label, low, high in AMOUNT_RANGES:
        if amount_cop >= low and (high is None or amount_cop < high):
            return label
    # Negative amounts never come out of the pipeline; still never drop one.
    return AMOUNT_RANGES[0][0]


def _totals(deposits: Iterable[Deposit], key) -> dict[str, tuple[int, int]]:
    totals: dict[str, tuple[int, int]] = {}
    for deposit in deposits:
        label = key(deposit)
        count, amount = totals.get(label, (0, 0))
        totals[label] = (count + 1, amount + deposit.amount_cop)
    return totals


def by_period(deposits: list[Deposit], periods: list[str], current_period: str | None) -> Chart:
    """One column per publication, oldest first, including the ones the
    party doesn't appear in (count 0) so recurrence is visible."""
    totals = _totals(deposits, lambda d: d.period or NO_DATA)
    labels = list(periods)
    # Periods only the party's deposits carry (or none at all) still count.
    labels += sorted(label for label in totals if label not in periods and label != NO_DATA)
    if NO_DATA in totals:
        labels.append(NO_DATA)
    bars = [
        Bar(label, *totals.get(label, (0, 0)), highlight=label == current_period)
        for label in labels
    ]
    appearances = sum(1 for bar in bars if bar.count and bar.label != NO_DATA)
    publications = sum(1 for bar in bars if bar.label != NO_DATA)
    return Chart(
        slug="period",
        dimension="Publicación",
        title="Evolución por publicación",
        measure="count",
        orientation="vertical",
        bars=bars,
        summary=f"Aparece en {appearances} de {publications} publicaciones",
    )


def by_amount_range(deposits: list[Deposit]) -> Chart:
    totals = _totals(deposits, lambda d: amount_range(d.amount_cop))
    return Chart(
        slug="amount-range",
        dimension="Rango de valor",
        title="Distribución por rango de valor",
        measure="count",
        orientation="horizontal",
        bars=[Bar(label, *totals.get(label, (0, 0))) for label, _, _ in AMOUNT_RANGES],
    )


def _ranked(totals: dict[str, tuple[int, int]], top: int) -> list[Bar]:
    """Bars by amount, largest first; past `top`, the rest fold into
    "Otros". "Sin dato" is never ranked or folded — it always closes the
    list, so missing data stays visible on its own."""
    no_data = totals.pop(NO_DATA, None)
    ranked = sorted(totals.items(), key=lambda item: (-item[1][1], -item[1][0], item[0]))
    bars = [Bar(label, count, amount) for label, (count, amount) in ranked]
    if len(bars) > top:
        rest = bars[top:]
        bars = bars[:top] + [
            Bar(OTHERS, sum(bar.count for bar in rest), sum(bar.amount_cop for bar in rest))
        ]
    if no_data:
        bars.append(Bar(NO_DATA, *no_data))
    return bars


def by_department(deposits: list[Deposit]) -> Chart:
    totals = _totals(deposits, lambda d: department(d.court_account))
    return Chart(
        slug="department",
        dimension="Departamento",
        title="Por departamento",
        measure="amount",
        orientation="horizontal",
        bars=_ranked(totals, top=TOP_DEPARTMENTS),
    )


def _change(current: int, previous: int) -> str:
    """Signed percent change in es-CO ("+12,3 %", "−45,7 %")."""
    change = (current - previous) / previous * 100
    sign = "+" if change >= 0 else "−"
    return f"{sign}{abs(change):.1f}".replace(".", ",") + " %"


def by_previous_period(
    deposits: list[Deposit], periods: list[str], current_period: str
) -> Chart | None:
    """The latest publication next to the one right before it in the corpus
    (not the party's own previous appearance), sliced from `by_period`. Bars
    measure value; counts ride the labels and the summary, never a second
    axis. None when there is no earlier publication."""
    if current_period not in periods or periods.index(current_period) == 0:
        return None
    previous_period = periods[periods.index(current_period) - 1]
    by_label = {
        bar.label: bar
        for bar in by_period(deposits, [previous_period, current_period], current_period).bars
    }
    previous, current = by_label[previous_period], by_label[current_period]
    if previous.count:
        summary = (
            f"Frente a {previous_period}: valor {_change(current.amount_cop, previous.amount_cop)}"
            f", depósitos {_change(current.count, previous.count)}"
        )
    else:
        summary = f"No aparecía en {previous_period}"
    return Chart(
        slug="previous-period",
        dimension="Publicación",
        title="Comparación con la publicación anterior",
        measure="amount",
        orientation="horizontal",
        bars=[previous, current],
        summary=summary,
    )


def current_publication_charts(
    deposits: list[Deposit], periods: list[str], current_period: str
) -> list[Chart] | None:
    """The compact charts for the "Última publicación" block. `deposits` is
    the party's full history: the comparison needs the previous publication;
    every other chart is the history's own aggregation over the latest
    publication only. Same threshold, on the latest publication's count."""
    current_deposits = [deposit for deposit in deposits if deposit.period == current_period]
    if len(current_deposits) < min_findings():
        return None
    comparison = by_previous_period(deposits, periods, current_period)
    return [
        *([comparison] if comparison else []),
        by_department(current_deposits),
        by_amount_range(current_deposits),
    ]


def history_charts(
    deposits: list[Deposit], periods: list[str], current_period: str | None
) -> list[Chart] | None:
    """The history's charts, or None below `min_findings()` deposits — the
    caller then renders no chart section at all."""
    if len(deposits) < min_findings():
        return None
    return [
        by_period(deposits, periods, current_period),
        by_amount_range(deposits),
        by_department(deposits),
    ]
