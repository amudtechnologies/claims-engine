"""Phase 3: canonical court offices and parties, deduplicated from staging.

Identity resolution (matching a raw ID or account number to a stable real-
world entity) is explicit core-layer work per CLAUDE.md's layer table,
distinct from the business inferences (economic role, deadline, priority)
rule 5 reserves for marts.

`document_type` is not decided here (D26, 2026-08-17). The old approach --
guessing legal_entity vs natural_person from the DIAN NIT check-digit
algorithm before ever querying RUES -- assumed only legal entities carry a
NIT, which is false for comerciante natural persons. RUES's own `Categoria`
field is now the sole source of truth, filled in by `enrichment.py` once a
party has actually been queried, with no discrimination by presumed type.
`build_parties` here only produces identity (`party_id`, `document_number`);
`document_type`/`document_type_confidence`/`document_type_rule_id` start
null and are backfilled by `build_identity` (cli.py) from the accumulated
`core/enrichment/` history on every rebuild -- otherwise a party already
classified would lose that classification every time core/party (a full
rebuilt-in-place snapshot, D07) gets recomputed from staging alone.
"""

from __future__ import annotations

import hashlib

import duckdb
import polars as pl

from claims_engine.duckdb_utils import to_polars
from claims_engine.parsing import nit_check_digit

_NIT_CANDIDATE_LENGTHS = (9, 10)


def party_id(document_number: str) -> str:
    return hashlib.sha256(document_number.encode()).hexdigest()[:16]


def court_id(court_account: str) -> str:
    return hashlib.sha256(court_account.encode()).hexdigest()[:16]


def canonical_court_account(raw: str | None) -> str | None:
    """Python twin of the SQL canonicalization in `build_courts_and_names`
    (strip non-digits, require a clean 11-12 digit result, left-pad to 12).
    Kept as SQL there for aggregation speed over millions of rows; exposed
    here too because `lifecycle.py` needs the identical rule per-row to
    compute `claim.court_id` without a second, possibly-diverging
    implementation. If this rule ever changes, both places need it."""
    if raw is None:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) not in (11, 12):
        return None
    return digits.rjust(12, "0")


def canonical_document_number(raw: str) -> str:
    """Strip a validated DIAN check digit from a 9-10 digit ID. Pure
    structural normalization -- a validating check digit is a deterministic
    property of the digit string itself (rule 3/D7: reprocessing from raw
    always produces the same party_id), not a claim about whether the ID
    belongs to a company. That claim (`document_type`) is decided downstream
    by RUES per D26, not here. Stripping the check digit is what collapses a
    NIT printed with and without it into one party, and produces the form
    CLAUDE.md's conventions say RUES joins actually need."""
    if len(raw) in _NIT_CANDIDATE_LENGTHS:
        base, check = raw[:-1], raw[-1]
        if nit_check_digit(base) == check:
            return base
    return raw


def resolve_document_numbers(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """One row per distinct *raw* ID seen as plaintiff or defendant (the
    `dep` view), with its canonical `document_number` and resulting
    `party_id` — not yet deduplicated by canonical form. `build_parties`
    dedupes this by `document_number` to build the `party` table; other
    callers (`lifecycle.py`, joining staging rows to a party) need the raw ->
    canonical mapping itself, since canonicalization can change the ID (NIT
    check-digit stripping) and staging only ever has the raw form."""
    rows = to_polars(
        con.execute(
            """
            SELECT DISTINCT document_number FROM (
                SELECT plaintiff_id AS document_number FROM dep WHERE plaintiff_id IS NOT NULL
                UNION
                SELECT defendant_id AS document_number FROM dep WHERE defendant_id IS NOT NULL
            )
            """
        )
    )
    df = rows.rename({"document_number": "document_number_raw"}).with_columns(
        pl.col("document_number_raw")
        .map_elements(canonical_document_number, return_dtype=pl.Utf8)
        .alias("document_number")
    )
    return df.with_columns(
        pl.col("document_number").map_elements(party_id, return_dtype=pl.Utf8).alias("party_id")
    )


def build_parties(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Deduplicate every distinct canonical `document_number` seen as
    plaintiff or defendant across all ok staging rows into one party row.
    `document_type`/`document_type_confidence`/`document_type_rule_id` start
    null (D26) -- `build_identity` (cli.py) backfills them from RUES lookup
    history after this returns; see `apply_rues_classification`."""
    df = resolve_document_numbers(con).drop("document_number_raw")
    parties = df.unique(subset=["document_number"], keep="first")
    return parties.with_columns(
        pl.lit(None, dtype=pl.Utf8).alias("document_type"),
        pl.lit(None, dtype=pl.Float64).alias("document_type_confidence"),
        pl.lit(None, dtype=pl.Utf8).alias("document_type_rule_id"),
    )


def latest_rues_classification(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Most recent classified RUES attempt per party, from an `enrichment`
    view the caller must already have registered (see cli.py's
    build-identity command). `document_type IS NOT NULL` selects only a
    genuine found/not_found answer (see enrichment.py's `_result_row`), never
    a bare network error, which carries no classification signal."""
    return to_polars(
        con.execute(
            """
            SELECT party_id, document_type, document_type_confidence, document_type_rule_id
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY party_id ORDER BY queried_at DESC
                ) AS rn
                FROM enrichment
                WHERE source = 'RUES' AND document_type IS NOT NULL
            )
            WHERE rn = 1
            """
        )
    )


def apply_rues_classification(parties: pl.DataFrame, classification: pl.DataFrame) -> pl.DataFrame:
    """Backfill party.document_type/_confidence/_rule_id from a prior RUES
    lookup (see `latest_rues_classification`), so core/party -- a full
    rebuilt-in-place snapshot (D07) recomputed from staging alone -- doesn't
    lose a classification `enrich_parties` already earned just because
    build-identity reran. A party with no matching row keeps the nulls
    `build_parties` set (never queried yet, or every attempt errored)."""
    joined = parties.join(classification, on="party_id", how="left", suffix="_rues")
    filled = joined.with_columns(
        pl.coalesce(["document_type_rues", "document_type"]).alias("document_type"),
        pl.coalesce(["document_type_confidence_rues", "document_type_confidence"]).alias(
            "document_type_confidence"
        ),
        pl.coalesce(["document_type_rule_id_rues", "document_type_rule_id"]).alias(
            "document_type_rule_id"
        ),
    )
    return filled.drop(
        ["document_type_rues", "document_type_confidence_rues", "document_type_rule_id_rues"]
    )


def build_courts_and_names(con: duckdb.DuckDBPyConnection) -> tuple[pl.DataFrame, pl.DataFrame]:
    """`court` (one row per canonical court_account) and `court_name` (name
    history with a period validity range) from the `dep` view.

    A court_account is canonical only once it's a clean 11-12 digit number
    after stripping non-digit characters — the real 2020-1 corruption
    pattern (lengths from 1 to 15 digits, not seen in any other period)
    fails that check and is treated as "court unknown" for that row rather
    than minted as a bogus court. Rows with no court_account at all
    (2017-1/2018-1/2018-2, no such column in the source) are excluded the
    same way — a permanent, documented gap, not a bug.
    """
    canon_cte = """
        WITH cleaned AS (
            SELECT
                regexp_replace(court_account, '[^0-9]', '', 'g') AS digits,
                court_name, seccional, department, city, judicial_district, period
            FROM dep
            WHERE court_account IS NOT NULL
        ),
        canon AS (
            SELECT
                CASE WHEN length(digits) IN (11, 12)
                     THEN lpad(digits, 12, '0') END AS court_account,
                court_name, seccional, department, city, judicial_district, period
            FROM cleaned
            WHERE digits <> ''
        )
    """

    courts = to_polars(
        con.execute(
            canon_cte
            + """
            SELECT
                court_account,
                mode(seccional) AS seccional,
                mode(department) AS department,
                mode(city) AS city,
                mode(judicial_district) AS judicial_district,
                count(*) AS row_count
            FROM canon
            WHERE court_account IS NOT NULL
            GROUP BY court_account
            """
        )
    )

    court_names = to_polars(
        con.execute(
            canon_cte
            + """
            SELECT
                court_account,
                court_name AS name,
                min(period) AS first_period,
                max(period) AS last_period,
                count(*) AS row_count
            FROM canon
            WHERE court_account IS NOT NULL AND court_name IS NOT NULL
            GROUP BY court_account, court_name
            """
        )
    )

    courts = courts.with_columns(
        pl.col("court_account").map_elements(court_id, return_dtype=pl.Utf8).alias("court_id")
    )
    court_names = court_names.with_columns(
        pl.col("court_account").map_elements(court_id, return_dtype=pl.Utf8).alias("court_id")
    )
    return courts, court_names
