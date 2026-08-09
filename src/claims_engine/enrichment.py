"""Phase 5: enrich core.party's legal_entity rows against RUES.

Never *queries* natural_person parties — enrichment is legal entities only,
full stop (rule 8; there is no code path here that could query one, since
`parties_to_enrich` filters on document_type at the SQL level). That's
about who issues the RUES request, not who the resulting row is about:
`_result_row` and `_ENRICHMENT_SCHEMA` are reused by document_type_check.py
to write a normal enrichment row for a party it just proved is a
legal_entity via a match it already fetched — one RUES call, not two,
without duplicating the response-shaping logic in two places.

`enrichment` is append-only and dated (D20): a party RUES genuinely reports
no match for (`status='not_found'`) is a valid, permanent state, not
something to retry automatically (D21) — same for a match (`status='found'`).
An `status='error'` row is different: it means we never got a real answer
from RUES (network failure, unexpected response shape, a blocked request),
so `parties_to_enrich` keeps retrying those. Re-enrichment of an already
*answered* party (e.g. RUES status may have changed) is a deliberate future
decision, not something this module does on its own.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import duckdb
import httpx
import polars as pl

from claims_engine.duckdb_utils import to_polars
from claims_engine.rues_client import get_company_detail, search_by_nit

SOURCE = "RUES"

_ENRICHMENT_SCHEMA = {
    "party_id": pl.Utf8,
    "source": pl.Utf8,
    "queried_at": pl.Datetime,
    "result": pl.Utf8,
    "name": pl.Utf8,
    "active": pl.Boolean,
    "attributes": pl.Utf8,
    "status": pl.Utf8,
}


def parties_to_enrich(con: duckdb.DuckDBPyConnection, limit: int) -> pl.DataFrame:
    """legal_entity parties from the `party` view with no completed RUES
    attempt yet recorded in the `enrichment` view (status 'found' or
    'not_found' -- a real answer from RUES). A party whose only prior
    attempts errored (status 'error') is still a target: an error means we
    never actually got RUES's answer, so it isn't the permanent state D21
    protects -- unlike a genuine 'not_found'.

    Batches written before the `status` column existed have it as NULL --
    and NULL does *not* mean "error". Some of those pre-column batches were
    genuine successful runs (real found/not_found answers), not just the
    handful that were infra failures. Since the column can't be trusted for
    them, fall back to content: every real RUES response (found or not)
    contains a `"registros"` key; a synthetic error row
    (`{"error": "<reason>"}`) never does. That's enough to tell a legacy
    answered row apart from a legacy error row without guessing.

    Both views must already be registered by the caller (see cli.py's
    enrich-parties command)."""
    return to_polars(
        con.execute(
            """
            SELECT p.party_id, p.document_number
            FROM party p
            WHERE p.document_type = 'legal_entity'
              AND NOT EXISTS (
                SELECT 1 FROM enrichment e
                WHERE e.party_id = p.party_id AND e.source = ?
                  AND (
                    e.status IN ('found', 'not_found')
                    OR (e.status IS NULL AND e.result LIKE '%"registros"%')
                  )
              )
            ORDER BY p.party_id
            LIMIT ?
            """,
            [SOURCE, limit],
        )
    )


def _result_row(
    party_id: str, queried_at: datetime, response: dict, detail: dict | None = None
) -> dict:
    registros = response.get("registros") or []
    match = registros[0] if registros else None
    if match is not None:
        name = match.get("razon_social")
        estado = (match.get("estado_matricula") or "").strip().upper()
        active = estado == "ACTIVA"
        attrs = {k: v for k, v in match.items() if k not in ("razon_social", "estado_matricula")}
        if detail is not None:
            attrs["detail"] = detail.get("registros")
        attributes = json.dumps(attrs)
    else:
        name, active, attributes = None, None, None
    return {
        "party_id": party_id,
        "source": SOURCE,
        "queried_at": queried_at,
        "result": json.dumps(response),
        "name": name,
        "active": active,
        "attributes": attributes,
        "status": "found" if match is not None else "not_found",
    }


def _error_row(party_id: str, queried_at: datetime, reason: str) -> dict:
    return {
        "party_id": party_id,
        "source": SOURCE,
        "queried_at": queried_at,
        "result": json.dumps({"error": reason}),
        "name": None,
        "active": None,
        "attributes": None,
        "status": "error",
    }


def enrich_parties(
    con: duckdb.DuckDBPyConnection,
    client: httpx.Client,
    limit: int,
    delay_seconds: float,
) -> pl.DataFrame:
    """Query RUES for up to `limit` not-yet-enriched legal_entity parties,
    pacing requests `delay_seconds` apart — a fixed, honest rate limit, not
    an attempt to look like a human clicking a button. Every attempt is
    recorded, including failures, so a re-run always makes forward progress
    on new parties instead of re-querying ones already resolved (or
    retrying failures forever).

    A match also costs one extra, equally-paced call for the company detail
    (address, contact info, economic activity, registration dates -- see
    `rues_client.get_company_detail`), folded into the same `attributes`. A
    failure at that second call fails the whole party as `status='error'`
    rather than keeping a detail-less `found` row, so a re-run retries the
    full pair instead of leaving the richer data permanently missing (the
    search itself is cheap to repeat)."""
    targets = parties_to_enrich(con, limit)
    rows = []
    made_a_call = False
    for party_id, document_number in targets.iter_rows():
        queried_at = datetime.now(UTC)
        try:
            if made_a_call:
                time.sleep(delay_seconds)
            made_a_call = True
            response = search_by_nit(client, int(document_number))
            detail = None
            registros = response.get("registros") or []
            if registros:
                time.sleep(delay_seconds)
                detail = get_company_detail(client, registros[0]["id_rm"])
            rows.append(_result_row(party_id, queried_at, response, detail))
        except Exception as e:
            rows.append(_error_row(party_id, queried_at, f"{type(e).__name__}: {e}"))
    return pl.DataFrame(rows, schema=_ENRICHMENT_SCHEMA)
