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
            status VARCHAR
        )
        """
    )
    for row in enrichment_rows or []:
        con.execute(
            """INSERT INTO enrichment VALUES
            ($party_id, $source, $queried_at, $result, $name, $active, $attributes, $status)""",
            row,
        )
    return con


def test_parties_to_enrich_filters_legal_entity_and_already_enriched():
    con = _connect(
        [
            {"party_id": "p1", "document_number": "900111111", "document_type": "legal_entity"},
            {"party_id": "p2", "document_number": "80111111", "document_type": "natural_person"},
            {"party_id": "p3", "document_number": "900222222", "document_type": "legal_entity"},
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
    assert targets["party_id"].to_list() == ["p1"]


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
    assert found_attrs["detail"]["dir_comercial"] == "CL 100 # 10-20"

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
