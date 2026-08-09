"""A RUES lookup for natural_person parties whose document_type has no
internal evidence either way: no declared type ever seen (2023-2 is the
only source of one), and NIT-candidate length (9-10 digits, the same range
real NITs use) with a check digit that doesn't validate
(`document_type_rule_id` 'nit_check_digit_invalid'). A RUES match is
definitive proof of legal_entity status — RUES is Colombia's authoritative
company registry, stronger evidence than a self-reported source label or
check-digit math alone.

Deliberately excludes 'length_default' (any length other than 9-10 digits):
that's not actually ambiguous. Real company NITs are essentially always
9-10 digits, so a shorter or longer ID is already fair internal evidence of
a natural person — confirmed live: including it would have made this
module's target population 1,038,779 parties instead of 189,213, mostly
short cedulas with no real ambiguity to resolve.

Deliberately a separate module from identity.py and enrichment.py:

- `classify_party` (Phase 3, core) stays a pure function of the raw file
  (rule 2) — RUES's live state changes over time (registrations happen and
  lapse), so wiring it into classification would make reprocessing from raw
  non-reproducible: the same raw file could classify differently depending
  on *when* build-identity happened to run.
- enrichment.py's contract is legal_entity parties only, full stop (rule 8),
  and its own docstring asserts "there is no code path here that could
  query [a natural_person party]" as a tested invariant. This module exists
  specifically to query the population enrichment.py must never touch —
  keeping it separate keeps that invariant airtight.

Scoped narrowly on purpose (rule 8 / D23): only the exhausted-signal subset,
never the full natural_person population. Most natural_person parties
genuinely are natural persons — querying RUES for all of them would mean
sending real citizens' cedula numbers to an external system purely to test
them, which is exactly what rule 8 exists to prevent.

Results land in their own append-only, dated table (`document_type_check`,
same core/ layer and shape as `enrichment` — D20's append-only/dated
pattern, matching how the project already reasons about
`party.document_type` itself: identity resolution is core-layer work, not a
business inference reserved for marts). `party.document_type` in
core/party/current.parquet is never rewritten by this module — callers join
`document_type_check.status = 'found'` at query time to treat a party as a
confirmed legal_entity, the same way `enrichment` is joined to `party`
rather than mutating it.

A `found` match also writes a normal `enrichment` row directly (reusing
`enrichment._result_row`/`_ENRICHMENT_SCHEMA`, the exact shape
`enrich_parties` would have produced, including the extra company-detail
call folded into `attributes` -- see that function's docstring), so
`enrich-parties` never needs a second RUES call to pick these parties up --
it wouldn't select them anyway (its query filters on
`party.document_type = 'legal_entity'`, which this module never changes),
and re-querying RUES for a match we already fetched would just be wasted
traffic. `not_found`/`error` results only ever land in
`document_type_check` -- nothing confirmed, so nothing to enrich, and rule 8
still applies: still-presumed-natural_person parties never get an
enrichment row.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime

import duckdb
import httpx
import polars as pl

from claims_engine.duckdb_utils import to_polars
from claims_engine.enrichment import _ENRICHMENT_SCHEMA
from claims_engine.enrichment import _result_row as _enrichment_result_row
from claims_engine.rues_client import get_company_detail, search_by_nit

SOURCE = "RUES"

_RESULT_SCHEMA = {
    "party_id": pl.Utf8,
    "source": pl.Utf8,
    "queried_at": pl.Datetime,
    "result": pl.Utf8,
    "name": pl.Utf8,
    "status": pl.Utf8,
}

_EXHAUSTED_SIGNAL_RULE_ID = "nit_check_digit_invalid"


def parties_needing_check(con: duckdb.DuckDBPyConnection, limit: int) -> pl.DataFrame:
    """natural_person parties with no internal evidence either way, and no
    completed RUES identity check yet recorded in `document_type_check`."""
    return to_polars(
        con.execute(
            """
            SELECT p.party_id, p.document_number
            FROM party p
            WHERE p.document_type = 'natural_person'
              AND p.document_type_rule_id = ?
              AND NOT EXISTS (
                SELECT 1 FROM document_type_check c
                WHERE c.party_id = p.party_id AND c.source = ?
                  AND c.status IN ('found', 'not_found')
              )
            ORDER BY p.party_id
            LIMIT ?
            """,
            [_EXHAUSTED_SIGNAL_RULE_ID, SOURCE, limit],
        )
    )


def _candidate_nits(document_number: str) -> list[int]:
    """What to actually try against RUES for a number with no validated
    check digit: the number as stored, and — if it's NIT-candidate length —
    its base with the last digit dropped too, since a failed check-digit
    validation doesn't rule out the number being a NIT; it just means the
    last digit doesn't satisfy the mod-11 formula, which also happens when a
    source row omits the check digit entirely rather than mis-recording it."""
    candidates = [int(document_number)]
    if len(document_number) in (9, 10):
        base = int(document_number[:-1])
        if base not in candidates:
            candidates.append(base)
    return candidates


def _result_row(party_id: str, queried_at: datetime, response: dict) -> dict:
    registros = response.get("registros") or []
    match = registros[0] if registros else None
    return {
        "party_id": party_id,
        "source": SOURCE,
        "queried_at": queried_at,
        "result": json.dumps(response),
        "name": match.get("razon_social") if match else None,
        "status": "found" if match is not None else "not_found",
    }


def _error_row(party_id: str, queried_at: datetime, reason: str) -> dict:
    return {
        "party_id": party_id,
        "source": SOURCE,
        "queried_at": queried_at,
        "result": json.dumps({"error": reason}),
        "name": None,
        "status": "error",
    }


def check_document_types(
    con: duckdb.DuckDBPyConnection,
    client: httpx.Client,
    limit: int,
    delay_seconds: float,
    progress_every: int = 100,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Query RUES for up to `limit` unchecked exhausted-signal natural_person
    parties. Tries each of a party's candidate NIT forms (see
    `_candidate_nits`) in turn, stopping at the first that finds a match —
    one recorded attempt per party either way. Every actual RUES call
    (including a second candidate for the same party) is paced
    `delay_seconds` apart, a fixed honest rate limit.

    Returns (check_rows, enrichment_rows) -- the second frame holds one row
    per confirmed match, in `enrichment`'s own shape (see module docstring),
    and is empty when nothing matched this run. A match also costs one more
    paced call for the company detail (see `enrichment.enrich_parties`'s
    docstring) folded into that enrichment row's `attributes`; a failure
    there fails the whole party as a `document_type_check` error row (so it
    stays a target next run) rather than writing a detail-less match.

    `on_progress`, if given, is called with (done, total) every
    `progress_every` parties and once more on the final one -- same reason
    as `enrichment.enrich_parties`: a large `limit` at a paced
    `delay_seconds` can run long with no other visible output."""
    targets = parties_needing_check(con, limit)
    total = targets.height
    check_rows = []
    enrichment_rows = []
    made_a_call = False
    for i, (party_id, document_number) in enumerate(targets.iter_rows(), start=1):
        queried_at = datetime.now(UTC)
        try:
            response: dict = {}
            for nit in _candidate_nits(document_number):
                if made_a_call:
                    time.sleep(delay_seconds)
                made_a_call = True
                response = search_by_nit(client, nit)
                if response.get("registros"):
                    break
            detail = None
            if response.get("registros"):
                time.sleep(delay_seconds)
                detail = get_company_detail(client, response["registros"][0]["id_rm"])
            check_rows.append(_result_row(party_id, queried_at, response))
            if response.get("registros"):
                enrichment_rows.append(
                    _enrichment_result_row(party_id, queried_at, response, detail)
                )
        except Exception as e:
            check_rows.append(_error_row(party_id, queried_at, f"{type(e).__name__}: {e}"))
        if on_progress is not None and (i % progress_every == 0 or i == total):
            on_progress(i, total)
    return (
        pl.DataFrame(check_rows, schema=_RESULT_SCHEMA),
        pl.DataFrame(enrichment_rows, schema=_ENRICHMENT_SCHEMA),
    )
