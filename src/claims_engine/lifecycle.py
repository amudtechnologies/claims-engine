"""Phase 4: claim identity across periods, plus the observation and
claim_party bridges.

Real findings this design is grounded in (see the phase-4 plan for the full
data): cross-period persistence of the same claim is small (~0.1-1.7% per
half-year step) and that's the correct answer, not a matching bug — it
matches the "eviction notice, not a watchlist" framing in
`docs/project-context.md` §2. Within-period duplicate rows are real source
re-publication (verified against real data: identical content, not a
different deposit colliding on the same number), so they become multiple
`observation`s of one claim rather than being deduped away. 2017-1 has no
reliable claim key at all (the grain mismatch established in Phase 1 — its
rows are case actions, not deposits) and is excluded entirely.
"""

from __future__ import annotations

import hashlib
import json

import duckdb
import polars as pl

from claims_engine.duckdb_utils import to_polars
from claims_engine.identity import canonical_court_account, court_id, resolve_document_numbers

_NO_COURT_ACCOUNT_SENTINEL = "no_court_account"


def claim_key(court_account: str | None, deposit_no: str) -> str:
    """Canonical court_account when resolvable; otherwise a fixed sentinel
    namespace, so 2018-1/2018-2 (no court_account column at all) and
    2020-1's corrupted values can't accidentally collide with a court-keyed
    claim that happens to share a deposit_no. deposit_no alone was verified
    reliable for 2018-1/2018-2 (near 1:1 to rows) before relying on this."""
    canon = canonical_court_account(court_account)
    prefix = canon if canon is not None else _NO_COURT_ACCOUNT_SENTINEL
    return f"{prefix}:{deposit_no}"


def claim_id(court_account: str | None, deposit_no: str) -> str:
    return hashlib.sha256(claim_key(court_account, deposit_no).encode()).hexdigest()[:16]


def _with_claim_id(rows: pl.DataFrame) -> pl.DataFrame:
    return rows.with_columns(
        pl.struct(["court_account", "deposit_no"])
        .map_elements(
            lambda s: claim_id(s["court_account"], s["deposit_no"]), return_dtype=pl.Utf8
        )
        .alias("claim_id")
    )


def _claim_rows(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Shared base query: every ok staging row outside 2017-1 (excluded
    entirely — see module docstring) with a non-null deposit_no, plus
    claim_id computed per row."""
    rows = to_polars(
        con.execute(
            """
            SELECT capture_id, sheet, source_row, period, court_account, deposit_no,
                   deposit_type, amount_cop, origin_date, classification, source_extra
            FROM dep
            WHERE period <> '2017-1' AND deposit_no IS NOT NULL
            """
        )
    )
    return _with_claim_id(rows)


def build_claims(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """One row per real deposit (best current knowledge), deduplicated
    across every period it was published in. amount_cop/origin_date/
    deposit_type are the most recent observation's values — genuinely
    conflicting observations of the same claim (rare, see the phase-4 plan)
    aren't reconciled here; they stay fully recoverable via
    observation -> capture -> file lineage."""
    rows = _claim_rows(con)
    latest = rows.sort(["period", "source_row"], descending=[True, True]).unique(
        subset=["claim_id"], keep="first"
    )

    def _court_id_for(account: str | None) -> str | None:
        canon = canonical_court_account(account)
        return court_id(canon) if canon is not None else None

    latest = latest.with_columns(
        pl.col("court_account")
        .map_elements(_court_id_for, return_dtype=pl.Utf8)
        .alias("court_id"),
        pl.struct(["classification", "source_extra"])
        .map_elements(
            lambda s: json.dumps(
                {"classification": s["classification"], "source_extra": s["source_extra"]}
            ),
            return_dtype=pl.Utf8,
        )
        .alias("attributes"),
        pl.lit(None, dtype=pl.Utf8).alias("case_number"),
        pl.lit(None, dtype=pl.Utf8).alias("legal_basis"),
        pl.lit(None, dtype=pl.Utf8).alias("claim_route"),
        pl.lit("judicial_deposit", dtype=pl.Utf8).alias("type"),
    )
    return latest.select(
        [
            "claim_id",
            "type",
            "court_id",
            "deposit_no",
            "deposit_type",
            "amount_cop",
            "origin_date",
            "case_number",
            "legal_basis",
            "claim_route",
            "attributes",
        ]
    )


def build_observations(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """One row per ok staging row that has a resolvable claim key — every
    duplicate/colliding row from the same capture still gets its own
    observation, pointing at the same claim_id (phase-4 plan, Decision 2)."""
    rows = _claim_rows(con)
    return rows.select(["capture_id", "sheet", "source_row", "claim_id"])


def build_claim_parties(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Distinct (claim_id, party_id, procedural_role) across every capture.
    Party lookup reuses identity.resolve_document_numbers so a legal-entity
    ID's check-digit-stripped canonical form matches core.party exactly the
    way Phase 3 built it, instead of a second classification pass that could
    silently diverge from it."""
    resolved = resolve_document_numbers(con).select(["document_number_raw", "party_id"])

    parties = to_polars(
        con.execute(
            """
            SELECT court_account, deposit_no, plaintiff_id AS document_number_raw,
                   'plaintiff' AS procedural_role
            FROM dep
            WHERE period <> '2017-1' AND deposit_no IS NOT NULL AND plaintiff_id IS NOT NULL
            UNION ALL
            SELECT court_account, deposit_no, defendant_id, 'defendant'
            FROM dep
            WHERE period <> '2017-1' AND deposit_no IS NOT NULL AND defendant_id IS NOT NULL
            """
        )
    )
    parties = _with_claim_id(parties)
    joined = parties.join(resolved, on="document_number_raw", how="inner")
    return (
        joined.select(["claim_id", "party_id", "procedural_role"])
        .unique()
        .with_columns(pl.lit(None, dtype=pl.Utf8).alias("attributes"))
    )


def measure_persistence(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """The phase's actual exit criterion: for each pair of consecutive
    periods, how many distinct claims from the earlier period are still
    present in the later one. Real measured answer: 0.0-1.7% per half-year
    step (phase-4 plan, Finding 1) — expected under the "eviction notice,
    not a watchlist" reading of the law (docs/project-context.md §2), not a
    sign the key is wrong."""
    rows = _with_claim_id(
        to_polars(
            con.execute(
                """
                SELECT DISTINCT period, court_account, deposit_no
                FROM dep WHERE period <> '2017-1' AND deposit_no IS NOT NULL
                """
            )
        )
    )
    periods = sorted(rows["period"].unique().to_list())
    by_period = {p: set(rows.filter(pl.col("period") == p)["claim_id"].to_list()) for p in periods}

    stats = []
    for prev_p, cur_p in zip(periods, periods[1:], strict=False):
        prev_ids, cur_ids = by_period[prev_p], by_period[cur_p]
        overlap = len(prev_ids & cur_ids)
        stats.append(
            {
                "prev_period": prev_p,
                "period": cur_p,
                "prev_count": len(prev_ids),
                "count": len(cur_ids),
                "overlap": overlap,
                "overlap_pct": round(overlap / len(prev_ids) * 100, 2) if prev_ids else None,
            }
        )
    return pl.DataFrame(
        stats,
        schema={
            "prev_period": pl.Utf8,
            "period": pl.Utf8,
            "prev_count": pl.Int64,
            "count": pl.Int64,
            "overlap": pl.Int64,
            "overlap_pct": pl.Float64,
        },
    )
