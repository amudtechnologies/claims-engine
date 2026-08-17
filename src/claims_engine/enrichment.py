"""Phase 5: query RUES for every core.party row and enrich whatever it finds.

D26 (2026-08-17) retired the old legal_entity-only design: the assumption
that only legal entities carry a NIT and appear in RUES is false -- a
natural person registered as a comerciante gets a NIT derived from their
cedula and has a RUES record like any company. There is no document_type
pre-filter here anymore (`parties_to_enrich` queries every party with no
completed attempt yet), and every match is enriched -- name, status,
`attributes` -- regardless of what RUES's `Categoria` field says the party
is. RUES's `Categoria` is now also the sole source of `document_type`
itself: `_result_row` reads it off a match and stamps
`document_type`/`document_type_confidence`/`document_type_rule_id` on the
enrichment row, which `build_identity` (cli.py) later joins back onto
core/party (see identity.apply_rues_classification).

This still touches Law 1581 the moment a national ID is joined to a name --
see CLAUDE.md rule 8 and D23/D24 (restricted-access storage for cedula-keyed
records, self-lookup-only serving) for the privacy posture this doesn't
change.

`enrichment` is append-only and dated (D20): a party RUES genuinely reports
no match for (`status='not_found'`) is a valid, permanent state, not
something to retry automatically (D21) -- same for a match (`status='found'`).
A `status='error'` row is different: it means we never got a real answer
from RUES (network failure, unexpected response shape, a blocked request),
so `parties_to_enrich` keeps retrying those. Re-enrichment of an already
*answered* party (e.g. RUES status may have changed) is a deliberate future
decision, not something this module does on its own.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime

import duckdb
import httpx
import polars as pl
from unidecode import unidecode

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
    "categoria": pl.Utf8,
    "document_type": pl.Utf8,
    "document_type_confidence": pl.Float64,
    "document_type_rule_id": pl.Utf8,
}


def _classify_from_categoria(categoria: str | None) -> tuple[str | None, float | None, str | None]:
    """Maps whatever Categoria RUES actually returns, not a closed
    two-string whitelist: a plain substring check on the normalized value
    (accent- and case-insensitive) catches real variants this project has
    never seen a live example of yet -- "PERSONA JURIDICA NACIONAL",
    "PERSONA JURIDICA EXTRANJERA", "PERSONA NATURAL COMERCIANTE", etc. --
    without needing to enumerate every one up front. `categoria` itself is
    always stored verbatim on the enrichment row regardless of whether this
    function can map it (see `_result_row`), so a genuinely different
    Categoria taxonomy this doesn't recognize (e.g. a record that isn't a
    persona classification at all) never loses information -- only the
    derived binary document_type stays null for it, honestly, rather than
    guessing which side it falls on."""
    if categoria is None:
        return None, None, "rues_categoria_missing"
    normalized = unidecode(categoria).strip().upper()
    if "JURIDICA" in normalized:
        return "legal_entity", 1.0, "rues_categoria"
    if "NATURAL" in normalized:
        return "natural_person", 1.0, "rues_categoria"
    return None, None, "rues_categoria_unrecognized"


def parties_to_enrich(con: duckdb.DuckDBPyConnection, limit: int) -> pl.DataFrame:
    """Every party from the `party` view with no completed RUES attempt yet
    recorded in the `enrichment` view (status 'found' or 'not_found' -- a
    real answer from RUES). No document_type filter (D26): a party whose
    document_type is still null (never queried) is exactly as much a target
    as one the old code would have called natural_person. A party whose only
    prior attempts errored (status 'error') is still a target too: an error
    means we never actually got RUES's answer, so it isn't the permanent
    state D21 protects -- unlike a genuine 'not_found'.

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
            WHERE NOT EXISTS (
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


def _candidate_document_numbers(document_number: str) -> list[int]:
    """What to actually try against RUES for one party: the stored
    document_number, and -- if it's NIT-candidate length -- its base with
    the last digit dropped too. `identity.canonical_document_number` only
    strips a check digit that validates; plenty of real NITs are recorded
    without one ever attached (a source row that just omitted it), so trying
    the stripped form too recovers real matches a single query would miss --
    and costs nothing extra when the first candidate already matches, since
    the caller stops at the first hit."""
    candidates = [int(document_number)]
    if len(document_number) in (9, 10):
        base = int(document_number[:-1])
        if base not in candidates:
            candidates.append(base)
    return candidates


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
            # The whole detail response, not just its "registros" key -- an
            # earlier version cherry-picked that one key and silently
            # dropped anything else RUES's detail endpoint returned.
            attrs["detail"] = detail
        attributes = json.dumps(attrs)
        categoria = match.get("categoria")
        document_type, confidence, rule_id = _classify_from_categoria(categoria)
    else:
        categoria = None
        name, active, attributes = None, None, None
        # No RUES record for any candidate tried: genuinely ambiguous, not
        # evidence of natural_person. Only two candidate numbers are ever
        # tried (see _candidate_document_numbers), so a real legal entity
        # can miss here for reasons that have nothing to do with what it
        # is -- a NIT outside those two forms, a lapsed/restructured
        # registration RUES's search doesn't surface, timing. There's no
        # measured error rate to calibrate a confident guess either way,
        # and guessing from absence is exactly the unfalsifiable-heuristic
        # problem D26 retired the DIAN check-digit approach for -- so this
        # carries no classification. The party stays unclassified, same
        # permanent-valid-state treatment D21 already gives a party with no
        # enrichment at all.
        document_type, confidence, rule_id = None, None, "rues_not_found"
    return {
        "party_id": party_id,
        "source": SOURCE,
        "queried_at": queried_at,
        "result": json.dumps(response),
        "name": name,
        "active": active,
        "attributes": attributes,
        "status": "found" if match is not None else "not_found",
        "categoria": categoria,
        "document_type": document_type,
        "document_type_confidence": confidence,
        "document_type_rule_id": rule_id,
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
        "categoria": None,
        # No document_type: an error means we never got RUES's answer, so
        # there's no classification signal to record either.
        "document_type": None,
        "document_type_confidence": None,
        "document_type_rule_id": None,
    }


def enrich_parties(
    con: duckdb.DuckDBPyConnection,
    client: httpx.Client,
    limit: int,
    delay_seconds: float,
    progress_every: int = 100,
    on_progress: Callable[[int, int], None] | None = None,
) -> pl.DataFrame:
    """Query RUES for up to `limit` not-yet-enriched parties of any
    document_type (D26), pacing requests `delay_seconds` apart — a fixed,
    honest rate limit, not an attempt to look like a human clicking a
    button. Every attempt is recorded, including failures, so a re-run
    always makes forward progress on new parties instead of re-querying ones
    already resolved (or retrying failures forever).

    Tries each of a party's candidate numbers (see
    `_candidate_document_numbers`) in turn, stopping at the first that finds
    a match -- one recorded attempt per party either way, each actual RUES
    call paced `delay_seconds` apart same as everything else here.

    A match also costs one extra, equally-paced call for the company detail
    (address, contact info, economic activity, registration dates -- see
    `rues_client.get_company_detail`), folded into the same `attributes`. A
    failure at that second call fails the whole party as `status='error'`
    rather than keeping a detail-less `found` row, so a re-run retries the
    full pair instead of leaving the richer data permanently missing (the
    search itself is cheap to repeat).

    `on_progress`, if given, is called with (done, total) every
    `progress_every` parties and once more on the final one -- e.g. a limit
    of 1000 at delay_seconds=3 takes ~50+ minutes end to end, so a caller
    (the CLI) needs a way to report progress instead of going silent until
    the very end."""
    targets = parties_to_enrich(con, limit)
    total = targets.height
    rows = []
    made_a_call = False
    for i, (party_id, document_number) in enumerate(targets.iter_rows(), start=1):
        queried_at = datetime.now(UTC)
        try:
            response: dict = {}
            for candidate in _candidate_document_numbers(document_number):
                if made_a_call:
                    time.sleep(delay_seconds)
                made_a_call = True
                response = search_by_nit(client, candidate)
                if response.get("registros"):
                    break
            detail = None
            registros = response.get("registros") or []
            if registros:
                time.sleep(delay_seconds)
                detail = get_company_detail(client, registros[0]["id_rm"])
            rows.append(_result_row(party_id, queried_at, response, detail))
        except Exception as e:
            rows.append(_error_row(party_id, queried_at, f"{type(e).__name__}: {e}"))
        if on_progress is not None and (i % progress_every == 0 or i == total):
            on_progress(i, total)
    return pl.DataFrame(rows, schema=_ENRICHMENT_SCHEMA)
