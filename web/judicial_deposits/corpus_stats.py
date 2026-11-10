"""Corpus-wide charts for the landing's "Estadísticas" section.

The same `insights.Chart` shapes the detail page draws for one party, here
over every deposit in `core/claim`. Aggregation runs in DuckDB against the
local cache (millions of rows never reach Python); only a few hundred
(year, department, amount range) totals come back, and every chart is a full
partition of them — each chart adds up to the landing's "valor total de los
depósitos identificados" (`party_search.total_claim_amount_cop`).

A deposit counts once, in the year of its latest publication — the same
"latest observation" rule the detail page uses to place a deposit in one
period. 2017-1 never yields claims (its rows are case actions, not
deposits; project-context.md §7, Phase 4), so the series starts in 2018.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import duckdb

from . import core_cache, insights
from .insights import AMOUNT_RANGES, DANE_DEPARTMENTS, NO_DATA, Bar, Chart

_TABLES = ("claim", "observation", "capture", "file", "court")


@dataclass(frozen=True)
class Slice:
    year: str | None
    department_code: str | None
    amount_range: str
    count: int
    amount_cop: int


def _amount_range_sql() -> tuple[str, list[str]]:
    """`insights.amount_range` as a SQL CASE, labels passed as parameters.
    A deposit with no amount (a handful in the corpus) goes to "Sin dato"."""
    whens = " ".join("WHEN c.amount_cop < ? THEN ?" for _ in AMOUNT_RANGES[:-1])
    whens = f"WHEN c.amount_cop IS NULL THEN ? {whens}"
    params: list = [NO_DATA]
    for label, _, high in AMOUNT_RANGES[:-1]:
        params += [high, label]
    params.append(AMOUNT_RANGES[-1][0])
    return f"CASE {whens} ELSE ? END", params


def _fetch_slices() -> list[Slice]:
    path = core_cache.table_path
    amount_range, params = _amount_range_sql()
    rows = duckdb.connect().execute(
        f"""
        WITH latest AS (
            SELECT o.claim_id, f.period
            FROM read_parquet('{path('observation')}') o
            JOIN read_parquet('{path('capture')}') USING (capture_id)
            JOIN read_parquet('{path('file')}') f USING (file_id)
            QUALIFY ROW_NUMBER() OVER (PARTITION BY o.claim_id ORDER BY f.period DESC) = 1
        )
        SELECT
            LEFT(latest.period, 4) AS year,
            -- Same validation as `insights.department`: a court account's
            -- first two digits are its DANE department code.
            CASE WHEN regexp_full_match(court.court_account, '[0-9]{{5,}}')
                 THEN LEFT(court.court_account, 2) END AS department_code,
            {amount_range} AS amount_range,
            COUNT(*),
            COALESCE(SUM(c.amount_cop), 0)
        FROM read_parquet('{path('claim')}') c
        LEFT JOIN latest USING (claim_id)
        LEFT JOIN read_parquet('{path('court')}') court USING (court_id)
        GROUP BY ALL
        """,
        params,
    ).fetchall()
    return [Slice(*row) for row in rows]


@lru_cache(maxsize=1)
def _cached_slices(_version: tuple[float, ...]) -> list[Slice]:
    return _fetch_slices()


def slices() -> list[Slice]:
    """Recomputed only when `sync_core_cache` replaces a table it reads."""
    version = tuple(core_cache.table_path(table).stat().st_mtime for table in _TABLES)
    return _cached_slices(version)


def _totals(rows: list[Slice], key) -> dict[str, tuple[int, int]]:
    totals: dict[str, tuple[int, int]] = {}
    for row in rows:
        label = key(row)
        count, amount = totals.get(label, (0, 0))
        totals[label] = (count + row.count, amount + row.amount_cop)
    return totals


def _by_year_bars(rows: list[Slice]) -> list[Bar]:
    totals = _totals(rows, lambda row: row.year or NO_DATA)
    years = sorted(label for label in totals if label != NO_DATA)
    if NO_DATA in totals:
        years.append(NO_DATA)
    return [Bar(year, *totals[year]) for year in years]


def charts(rows: list[Slice]) -> list[Chart]:
    year_bars = _by_year_bars(rows)
    department_totals = _totals(
        rows, lambda row: DANE_DEPARTMENTS.get(row.department_code or "", NO_DATA)
    )
    range_totals = _totals(rows, lambda row: row.amount_range)
    return [
        Chart(
            slug="year-count",
            dimension="Año",
            title="Evolución histórica por año: cantidad de depósitos",
            measure="count",
            orientation="vertical",
            bars=year_bars,
        ),
        Chart(
            slug="year-amount",
            dimension="Año",
            title="Evolución anual: valor de los depósitos",
            measure="amount",
            orientation="vertical",
            bars=year_bars,
        ),
        Chart(
            slug="department",
            dimension="Departamento",
            title="Distribución geográfica por departamento",
            measure="amount",
            orientation="horizontal",
            bars=insights._ranked(department_totals, top=insights.TOP_DEPARTMENTS),
            summary="Valor y cantidad de depósitos según el departamento del despacho",
        ),
        Chart(
            slug="amount-range",
            dimension="Rango de valor",
            title="Distribución por rangos de valor",
            measure="count",
            orientation="horizontal",
            bars=[Bar(label, *range_totals.get(label, (0, 0))) for label, _, _ in AMOUNT_RANGES]
            + ([Bar(NO_DATA, *range_totals[NO_DATA])] if NO_DATA in range_totals else []),
        ),
    ]


def corpus_charts() -> list[Chart] | None:
    """The landing's four charts, or None when the cache isn't synced."""
    if not core_cache.is_synced():
        return None
    return charts(slices())
