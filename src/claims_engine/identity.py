"""Phase 3: canonical court offices and parties, deduplicated from staging.

Identity resolution (matching a raw ID or account number to a stable real-
world entity) is explicit core-layer work per CLAUDE.md's layer table,
distinct from the business inferences (economic role, deadline, priority)
rule 5 reserves for marts. `document_type_confidence` and
`document_type_rule_id` make that judgment auditable without needing a
separate marts inference table for this one field.
"""

from __future__ import annotations

import hashlib

import duckdb
import polars as pl
from unidecode import unidecode

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


def _normalize_declared_type(label: str | None) -> str | None:
    """2023-2 is the only period with a source-declared ID type, and even
    there it's inconsistent (9 raw label variants incl. typos like
    'CEDULA CUIDADANIA'). Anything starting with NIT is legal_entity;
    'Desconocido' and blanks fall through to the inferred heuristic rather
    than being trusted as a natural-person signal."""
    if label is None:
        return None
    normalized = unidecode(label).strip().upper()
    if not normalized or normalized == "DESCONOCIDO":
        return None
    if normalized.startswith("NIT"):
        return "legal_entity"
    return "natural_person"


def classify_party(
    document_number: str, declared_type: str | None
) -> tuple[str, str, float, str]:
    """Returns (canonical_document_number, document_type, confidence, rule_id).

    Source-declared type (2023-2 only) starts as a fact, confidence 1.0 -- but
    the source declaring "this is a company" says nothing about whether the
    number it printed still carries a check digit, so a declared legal_entity
    still gets the same check-digit strip as the inferred path whenever it
    validates (confirmed live against RUES: most of 2023-2's declared
    legal_entity parties were still 10-digit NIT+check-digit, causing
    systematic RUES lookup failures until stripped).

    A declared natural_person gets the same check-digit cross-check, not a
    free pass: confirmed at scale that 2023-2's declared type is genuinely
    unreliable for this (9 raw label variants incl. typos like "CEDULA
    CUIDADANIA"), and 2,513 of 17,726 length-9/10 declared-natural_person
    parties validate as a NIT anyway. A validating check digit is real
    structural evidence a cedula (never constructed to satisfy that formula)
    wouldn't produce by chance, so it overrides a contradicted declared
    label -- at the inferred path's confidence (0.85), not 1.0, since this is
    resolving a contradiction, not confirming agreement. A declared
    natural_person that *doesn't* validate is left alone at confidence 1.0:
    there's no contradicting evidence, and cedulas have no check-digit
    concept to strip.

    Everywhere the type isn't declared, length plus DIAN's public mod-11 NIT
    check-digit algorithm is the strongest available structural signal: real
    data showed NIT and cedula lengths overlap heavily (10 digits is the
    single largest length bucket in the whole dataset for both), so a bare
    length cutoff alone isn't reliable. A validating check digit is real
    evidence for legal_entity; a non-validating one is real (not certain)
    evidence for natural_person, since a genuine cedula was never constructed
    to satisfy that formula. Confidence values are calibration judgment, not
    a measured error rate -- there's no ground truth to measure against
    outside the one declared period.
    """
    declared = _normalize_declared_type(declared_type)
    if declared is not None:
        if len(document_number) in _NIT_CANDIDATE_LENGTHS:
            base, check = document_number[:-1], document_number[-1]
            if nit_check_digit(base) == check:
                if declared == "legal_entity":
                    return base, declared, 1.0, "source_declared"
                return base, "legal_entity", 0.85, "source_declared_overridden_by_check_digit"
        return document_number, declared, 1.0, "source_declared"

    if len(document_number) in _NIT_CANDIDATE_LENGTHS:
        base, check = document_number[:-1], document_number[-1]
        if nit_check_digit(base) == check:
            return base, "legal_entity", 0.85, "nit_check_digit_valid"
        return document_number, "natural_person", 0.6, "nit_check_digit_invalid"

    return document_number, "natural_person", 0.55, "length_default"


def resolve_document_numbers(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """One row per distinct *raw* ID seen as plaintiff or defendant (the
    `dep` view), with its classification and resulting `party_id` — not yet
    deduplicated by canonical form. `build_parties` dedupes this by
    `document_number` to build the `party` table; other callers
    (`lifecycle.py`, joining staging rows to a party) need the raw ->
    canonical mapping itself, since classification can change the ID (NIT
    check-digit stripping) and staging only ever has the raw form.

    Declared type is resolved per raw ID by a majority vote over every
    occurrence's normalized category (2023-2 declares types, every other
    period doesn't) — computed once here so every caller sees the same
    classification for the same raw ID, regardless of which period's
    occurrence they're looking at.

    Not a plain `max(declared_type)` over the raw label: that's a
    lexicographic string max, which silently prefers whichever label sorts
    alphabetically last regardless of how rarely it was actually declared.
    Confirmed live: 900 raw IDs carry genuinely conflicting NIT-vs-not
    declarations across their occurrences, and 414 of them (46%) had
    `max()` pick the *minority* label -- e.g. one ID declared NIT 566 times
    and a natural-person-type label only 44 times, but "TARJETA..." sorts
    after "NIT..." so the 44-vote label won. Ties (equal counts) fall back
    to `max()` over the tied labels, for determinism.
    """
    rows = to_polars(
        con.execute(
            """
            WITH occurrences AS (
                SELECT plaintiff_id AS document_number, plaintiff_id_type AS declared_type
                FROM dep WHERE plaintiff_id IS NOT NULL
                UNION ALL
                SELECT defendant_id, defendant_id_type
                FROM dep WHERE defendant_id IS NOT NULL
            ),
            all_ids AS (SELECT DISTINCT document_number FROM occurrences),
            categorized AS (
                SELECT document_number, declared_type,
                    CASE
                        WHEN declared_type IS NULL THEN NULL
                        WHEN upper(trim(declared_type)) IN ('', 'DESCONOCIDO') THEN NULL
                        WHEN upper(trim(declared_type)) LIKE 'NIT%' THEN 'legal_entity'
                        ELSE 'natural_person'
                    END AS category
                FROM occurrences
            ),
            votes AS (
                SELECT document_number, count(*) AS n, max(declared_type) AS sample_label
                FROM categorized
                WHERE category IS NOT NULL
                GROUP BY document_number, category
            ),
            ranked AS (
                SELECT document_number, sample_label,
                       row_number() OVER (
                           PARTITION BY document_number ORDER BY n DESC, sample_label DESC
                       ) AS rn
                FROM votes
            )
            SELECT a.document_number, r.sample_label AS declared_type
            FROM all_ids a
            LEFT JOIN ranked r ON r.document_number = a.document_number AND r.rn = 1
            """
        )
    )

    resolved = []
    for document_number, declared_type in rows.iter_rows():
        canonical, doc_type, confidence, rule_id = classify_party(document_number, declared_type)
        resolved.append(
            {
                "document_number_raw": document_number,
                "document_number": canonical,
                "document_type": doc_type,
                "document_type_confidence": confidence,
                "document_type_rule_id": rule_id,
            }
        )
    df = pl.DataFrame(
        resolved,
        schema={
            "document_number_raw": pl.Utf8,
            "document_number": pl.Utf8,
            "document_type": pl.Utf8,
            "document_type_confidence": pl.Float64,
            "document_type_rule_id": pl.Utf8,
        },
    )
    return df.with_columns(
        pl.col("document_number").map_elements(party_id, return_dtype=pl.Utf8).alias("party_id")
    )


def build_parties(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Deduplicate every distinct normalized ID seen as plaintiff or
    defendant across all ok staging rows into one party per canonical
    `document_number`."""
    df = resolve_document_numbers(con).drop("document_number_raw")

    # Two different raw IDs can canonicalize to the same document_number
    # (e.g. a NIT base colliding with an unrelated cedula-length ID) — keep
    # the highest-confidence classification for each.
    return df.sort("document_type_confidence", descending=True).unique(
        subset=["document_number"], keep="first"
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
