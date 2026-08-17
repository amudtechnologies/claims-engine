import json

import duckdb
import httpx
import polars as pl

from claims_engine.enrichment import enrich_parties, parties_to_enrich
from claims_engine.rues_client import DETAIL_URL, decrypt


def _connect(party_rows: list[dict], enrichment_rows: list[dict] | None = None):
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE party (party_id VARCHAR, document_number VARCHAR, document_type VARCHAR)"
    )
    for row in party_rows:
        con.execute(
            "INSERT INTO party VALUES ($party_id, $document_number, $document_type)", row
        )

    con.execute(
        """
        CREATE TABLE enrichment (
            party_id VARCHAR, source VARCHAR, queried_at TIMESTAMP,
            result VARCHAR, name VARCHAR, active BOOLEAN, attributes VARCHAR,
            status VARCHAR, document_type VARCHAR,
            document_type_confidence DOUBLE, document_type_rule_id VARCHAR
        )
        """
    )
    for row in enrichment_rows or []:
        con.execute(
            """INSERT INTO enrichment VALUES
            ($party_id, $source, $queried_at, $result, $name, $active, $attributes, $status,
             $document_type, $document_type_confidence, $document_type_rule_id)""",
            {
                "document_type": None,
                "document_type_confidence": None,
                "document_type_rule_id": None,
                **row,
            },
        )
    return con


def test_parties_to_enrich_includes_every_document_type_excluding_already_enriched():
    # D26: no document_type pre-filter -- p1/p2 are both targets regardless
    # of their (still-null, pre-lookup) document_type. p3 is excluded only
    # because it already has a completed RUES attempt.
    con = _connect(
        [
            {"party_id": "p1", "document_number": "900111111", "document_type": None},
            {"party_id": "p2", "document_number": "80111111", "document_type": None},
            {"party_id": "p3", "document_number": "900222222", "document_type": None},
        ],
        enrichment_rows=[
            {
                "party_id": "p3",
                "source": "RUES",
                "queried_at": "2026-01-01 00:00:00",
                "result": "{}",
                "name": None,
                "active": None,
                "attributes": None,
                "status": "not_found",
            }
        ],
    )
    targets = parties_to_enrich(con, limit=10)
    assert set(targets["party_id"].to_list()) == {"p1", "p2"}


def test_parties_to_enrich_retries_a_party_whose_only_attempt_errored():
    con = _connect(
        [
            {"party_id": "p1", "document_number": "900111111", "document_type": "legal_entity"},
            {"party_id": "p2", "document_number": "900222222", "document_type": "legal_entity"},
        ],
        enrichment_rows=[
            {
                "party_id": "p1",
                "source": "RUES",
                "queried_at": "2026-01-01 00:00:00",
                "result": '{"error": "HTTPStatusError: 403"}',
                "name": None,
                "active": None,
                "attributes": None,
                "status": "error",
            },
            # Pre-`status`-column legacy row: NULL status, and its `result`
            # has no "registros" key -- a genuine legacy error, retryable.
            {
                "party_id": "p2",
                "source": "RUES",
                "queried_at": "2026-01-01 00:00:00",
                "result": '{"error": "HTTPStatusError: 403"}',
                "name": None,
                "active": None,
                "attributes": None,
                "status": None,
            },
        ],
    )
    targets = parties_to_enrich(con, limit=10)
    assert set(targets["party_id"].to_list()) == {"p1", "p2"}


def test_parties_to_enrich_does_not_retry_a_legacy_answered_row():
    """A pre-`status`-column batch could be a genuine successful run, not
    just an error -- NULL status alone must not imply retryable."""
    con = _connect(
        [
            {"party_id": "p1", "document_number": "900111111", "document_type": "legal_entity"},
        ],
        enrichment_rows=[
            {
                "party_id": "p1",
                "source": "RUES",
                "queried_at": "2026-01-01 00:00:00",
                "result": '{"registros": [], "cant_registros": 0}',
                "name": None,
                "active": None,
                "attributes": None,
                "status": None,
            },
        ],
    )
    targets = parties_to_enrich(con, limit=10)
    assert targets.height == 0


def test_parties_to_enrich_respects_limit():
    con = _connect(
        [
            {
                "party_id": f"p{i}",
                "document_number": f"90000000{i}",
                "document_type": "legal_entity",
            }
            for i in range(5)
        ]
    )
    targets = parties_to_enrich(con, limit=2)
    assert targets.height == 2


def test_enrich_parties_builds_found_and_not_found_rows():
    con = _connect(
        [
            {"party_id": "p1", "document_number": "901484254", "document_type": "legal_entity"},
            {"party_id": "p2", "document_number": "900000000", "document_type": "legal_entity"},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payload = json.loads(decrypt(body["dataBody"]))
        if str(request.url) == DETAIL_URL:
            assert payload["id"] == "40000019772"
            return httpx.Response(
                200,
                json={"registros": {"dir_comercial": "CL 100 # 10-20", "estado": "ACTIVA"}},
            )
        if payload["Nit"] == 901484254:
            return httpx.Response(
                200,
                json={
                    "registros": [
                        {
                            "razon_social": "DECKARD COLOMBIA S.A.S",
                            "estado_matricula": "ACTIVA",
                            "nit": "901484254",
                            "dv": "9",
                            "id_rm": "40000019772",
                        }
                    ],
                    "cant_registros": 1,
                },
            )
        return httpx.Response(200, json={"registros": [], "cant_registros": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = enrich_parties(con, client, limit=10, delay_seconds=0)

    assert result.height == 2
    found = result.filter(pl.col("party_id") == "p1").row(0, named=True)
    assert found["name"] == "DECKARD COLOMBIA S.A.S"
    assert found["active"] is True
    assert found["status"] == "found"
    found_attrs = json.loads(found["attributes"])
    assert found_attrs["dv"] == "9"
    # The whole detail response is kept, not just its "registros" key -- so
    # nothing RUES's detail endpoint returns is silently dropped.
    assert found_attrs["detail"] == {
        "registros": {"dir_comercial": "CL 100 # 10-20", "estado": "ACTIVA"}
    }

    not_found = result.filter(pl.col("party_id") == "p2").row(0, named=True)
    assert not_found["name"] is None
    assert not_found["active"] is None
    assert not_found["status"] == "not_found"


def test_enrich_parties_records_error_row_on_failure_instead_of_crashing():
    con = _connect(
        [{"party_id": "p1", "document_number": "900000000", "document_type": "legal_entity"}]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = enrich_parties(con, client, limit=10, delay_seconds=0)

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["name"] is None
    assert row["status"] == "error"
    assert "404" in row["result"]


def test_enrich_parties_reports_progress_every_n_and_on_the_last_one():
    con = _connect(
        [
            {"party_id": f"p{i}", "document_number": "900000000", "document_type": "legal_entity"}
            for i in range(5)
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"registros": [], "cant_registros": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    calls: list[tuple[int, int]] = []
    result = enrich_parties(
        con,
        client,
        limit=10,
        delay_seconds=0,
        progress_every=2,
        on_progress=lambda done, total: calls.append((done, total)),
    )

    assert result.height == 5
    assert calls == [(2, 5), (4, 5), (5, 5)]


def test_enrich_parties_classifies_from_categoria_regardless_of_document_type():
    # D26: RUES's own Categoria is authoritative, for any party -- p1 here
    # would have been excluded entirely under the old legal_entity-only
    # filter, but a natural-person comerciante has a real RUES record too.
    con = _connect([{"party_id": "p1", "document_number": "80111111", "document_type": None}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "registros": [
                    {
                        "razon_social": "JUAN PEREZ",
                        "estado_matricula": "ACTIVA",
                        "categoria": "Persona Natural",
                        "id_rm": "1",
                    }
                ],
                "cant_registros": 1,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = enrich_parties(con, client, limit=10, delay_seconds=0)

    row = result.row(0, named=True)
    assert row["status"] == "found"
    assert row["categoria"] == "Persona Natural"
    assert row["document_type"] == "natural_person"
    assert row["document_type_rule_id"] == "rues_categoria"
    assert row["document_type_confidence"] == 1.0


def test_enrich_parties_matches_categoria_variant_not_in_a_fixed_whitelist():
    # A real-world variant this project has never hardcoded ("PERSONA
    # JURIDICA NACIONAL" vs. the plain "PERSONA JURIDICA" used elsewhere)
    # must still classify correctly via substring matching, not fail open
    # to unrecognized just because it isn't an exact string match.
    con = _connect([{"party_id": "p1", "document_number": "900111111", "document_type": None}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "registros": [
                    {
                        "razon_social": "ACME SAS",
                        "estado_matricula": "ACTIVA",
                        "categoria": "PERSONA JURIDICA NACIONAL",
                        "id_rm": "1",
                    }
                ],
                "cant_registros": 1,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = enrich_parties(con, client, limit=10, delay_seconds=0)

    row = result.row(0, named=True)
    assert row["categoria"] == "PERSONA JURIDICA NACIONAL"
    assert row["document_type"] == "legal_entity"
    assert row["document_type_rule_id"] == "rues_categoria"


def test_enrich_parties_stores_unrecognized_categoria_verbatim_but_enriches_anyway():
    # A Categoria this project genuinely can't map (not a persona
    # natural/juridica label at all) must still fully enrich the party --
    # only the derived document_type stays null. The raw value itself is
    # never lost.
    con = _connect([{"party_id": "p1", "document_number": "900111111", "document_type": None}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "registros": [
                    {
                        "razon_social": "CONSORCIO OBRAS DEL NORTE",
                        "estado_matricula": "ACTIVA",
                        "categoria": "ESTABLECIMIENTO DE COMERCIO",
                        "id_rm": "1",
                    }
                ],
                "cant_registros": 1,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = enrich_parties(con, client, limit=10, delay_seconds=0)

    row = result.row(0, named=True)
    assert row["status"] == "found"
    assert row["name"] == "CONSORCIO OBRAS DEL NORTE"
    assert row["active"] is True
    assert row["categoria"] == "ESTABLECIMIENTO DE COMERCIO"
    assert row["document_type"] is None
    assert row["document_type_rule_id"] == "rues_categoria_unrecognized"


def test_enrich_parties_not_found_carries_no_classification():
    # A clean miss is genuinely ambiguous (could be a real legal entity
    # missed on both candidate numbers tried) -- not evidence of
    # natural_person. document_type/confidence stay null; rule_id records
    # that an attempt was made and came back empty.
    con = _connect([{"party_id": "p1", "document_number": "900000000", "document_type": None}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"registros": [], "cant_registros": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = enrich_parties(con, client, limit=10, delay_seconds=0)

    row = result.row(0, named=True)
    assert row["status"] == "not_found"
    assert row["document_type"] is None
    assert row["document_type_rule_id"] == "rues_not_found"
    assert row["document_type_confidence"] is None


def test_enrich_parties_error_row_carries_no_classification():
    con = _connect([{"party_id": "p1", "document_number": "900000000", "document_type": None}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = enrich_parties(con, client, limit=10, delay_seconds=0)

    row = result.row(0, named=True)
    assert row["status"] == "error"
    assert row["document_type"] is None
    assert row["document_type_rule_id"] is None


def test_enrich_parties_falls_back_to_check_digit_stripped_candidate():
    # "1234567896" (9 digits) doesn't match as-is; RUES only knows the
    # check-digit-stripped base "123456789" -- the second candidate.
    con = _connect([{"party_id": "p1", "document_number": "1234567896", "document_type": None}])
    seen_nits = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payload = json.loads(decrypt(body["dataBody"]))
        if str(request.url) == DETAIL_URL:
            return httpx.Response(200, json={"registros": {}})
        seen_nits.append(payload["Nit"])
        if payload["Nit"] == 123456789:
            return httpx.Response(
                200,
                json={
                    "registros": [
                        {"razon_social": "ACME SAS", "estado_matricula": "ACTIVA", "id_rm": "1"}
                    ],
                    "cant_registros": 1,
                },
            )
        return httpx.Response(200, json={"registros": [], "cant_registros": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = enrich_parties(con, client, limit=10, delay_seconds=0)

    row = result.row(0, named=True)
    assert row["status"] == "found"
    assert seen_nits == [1234567896, 123456789]
