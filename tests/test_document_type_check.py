import json

import duckdb
import httpx

from claims_engine.document_type_check import check_document_types, parties_needing_check
from claims_engine.rues_client import DETAIL_URL, decrypt


def _connect(party_rows: list[dict], check_rows: list[dict] | None = None):
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE party (
            party_id VARCHAR, document_number VARCHAR, document_type VARCHAR,
            document_type_rule_id VARCHAR
        )
        """
    )
    for row in party_rows:
        con.execute(
            "INSERT INTO party VALUES ($party_id, $document_number, $document_type, "
            "$document_type_rule_id)",
            row,
        )

    con.execute(
        """
        CREATE TABLE document_type_check (
            party_id VARCHAR, source VARCHAR, queried_at TIMESTAMP,
            result VARCHAR, name VARCHAR, status VARCHAR
        )
        """
    )
    for row in check_rows or []:
        con.execute(
            "INSERT INTO document_type_check VALUES "
            "($party_id, $source, $queried_at, $result, $name, $status)",
            row,
        )
    return con


def test_parties_needing_check_only_targets_exhausted_signal_natural_person():
    con = _connect(
        [
            {
                "party_id": "p1",
                "document_number": "806001951",
                "document_type": "natural_person",
                "document_type_rule_id": "nit_check_digit_invalid",
            },
            # Not NIT-candidate length -- real company NITs are essentially
            # always 9-10 digits, so a shorter ID is already fair internal
            # evidence of a natural person. Not genuinely ambiguous, must
            # never be a target (confirmed live: including it would have
            # made the target population 1,038,779 parties instead of
            # 189,213).
            {
                "party_id": "p2",
                "document_number": "1234567",
                "document_type": "natural_person",
                "document_type_rule_id": "length_default",
            },
            # Declared natural_person, uncontradicted -- real source evidence,
            # not an exhausted-signal case. Must never be a target.
            {
                "party_id": "p3",
                "document_number": "1234567891",
                "document_type": "natural_person",
                "document_type_rule_id": "source_declared",
            },
            # A legal_entity party -- enrichment.py's territory, not this module's.
            {
                "party_id": "p4",
                "document_number": "900111111",
                "document_type": "legal_entity",
                "document_type_rule_id": "nit_check_digit_valid",
            },
        ]
    )
    targets = parties_needing_check(con, limit=10)
    assert targets["party_id"].to_list() == ["p1"]


def test_parties_needing_check_skips_already_checked():
    con = _connect(
        [
            {
                "party_id": "p1",
                "document_number": "806001951",
                "document_type": "natural_person",
                "document_type_rule_id": "nit_check_digit_invalid",
            },
        ],
        check_rows=[
            {
                "party_id": "p1",
                "source": "RUES",
                "queried_at": "2026-01-01 00:00:00",
                "result": "{}",
                "name": None,
                "status": "not_found",
            }
        ],
    )
    targets = parties_needing_check(con, limit=10)
    assert targets.height == 0


def test_check_document_types_records_found_match_and_writes_enrichment_row():
    con = _connect(
        [
            {
                "party_id": "p1",
                "document_number": "806001951",
                "document_type": "natural_person",
                "document_type_rule_id": "nit_check_digit_invalid",
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payload = json.loads(decrypt(body["dataBody"]))
        if str(request.url) == DETAIL_URL:
            assert payload["id"] == "40000019772"
            return httpx.Response(200, json={"registros": {"dir_comercial": "CL 1 # 2-3"}})
        if payload["Nit"] == 806001951:
            return httpx.Response(
                200,
                json={
                    "registros": [
                        {
                            "razon_social": "TRANSPORTES EL SOL S.A.S",
                            "estado_matricula": "ACTIVA",
                            "id_rm": "40000019772",
                        }
                    ],
                    "cant_registros": 1,
                },
            )
        return httpx.Response(200, json={"registros": [], "cant_registros": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result, enrichment_result = check_document_types(con, client, limit=10, delay_seconds=0)

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["name"] == "TRANSPORTES EL SOL S.A.S"
    assert row["status"] == "found"

    # A found match also produces a normal enrichment-shaped row, one RUES
    # call instead of two -- enrich-parties never needs to re-query this
    # party (it wouldn't select it anyway, since party.document_type is
    # never rewritten).
    assert enrichment_result.height == 1
    erow = enrichment_result.row(0, named=True)
    assert erow["party_id"] == "p1"
    assert erow["name"] == "TRANSPORTES EL SOL S.A.S"
    assert erow["active"] is True
    assert erow["status"] == "found"
    assert json.loads(erow["attributes"])["detail"]["dir_comercial"] == "CL 1 # 2-3"


def test_check_document_types_falls_back_to_stripped_base_candidate():
    # Nothing matches the number as stored, but the base (last digit
    # dropped) does -- the source apparently just omitted the check digit.
    con = _connect(
        [
            {
                "party_id": "p1",
                "document_number": "806001951",
                "document_type": "natural_person",
                "document_type_rule_id": "nit_check_digit_invalid",
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payload = json.loads(decrypt(body["dataBody"]))
        if str(request.url) == DETAIL_URL:
            return httpx.Response(200, json={"registros": {}})
        if payload["Nit"] == 80600195:
            return httpx.Response(
                200,
                json={
                    "registros": [{"razon_social": "BASE MATCH SAS", "id_rm": "999"}],
                    "cant_registros": 1,
                },
            )
        return httpx.Response(200, json={"registros": [], "cant_registros": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result, enrichment_result = check_document_types(con, client, limit=10, delay_seconds=0)

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["name"] == "BASE MATCH SAS"
    assert row["status"] == "found"
    assert enrichment_result.height == 1
    assert enrichment_result.row(0, named=True)["name"] == "BASE MATCH SAS"


def test_check_document_types_not_found_leaves_party_unresolved_and_unenriched():
    con = _connect(
        [
            {
                "party_id": "p1",
                "document_number": "1234567890",
                "document_type": "natural_person",
                "document_type_rule_id": "nit_check_digit_invalid",
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"registros": [], "cant_registros": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result, enrichment_result = check_document_types(con, client, limit=10, delay_seconds=0)

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["name"] is None
    assert row["status"] == "not_found"
    # Nothing confirmed -- rule 8 still applies, no enrichment row.
    assert enrichment_result.height == 0


def test_check_document_types_records_error_row_on_failure_instead_of_crashing():
    con = _connect(
        [
            {
                "party_id": "p1",
                "document_number": "1234567890",
                "document_type": "natural_person",
                "document_type_rule_id": "nit_check_digit_invalid",
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result, enrichment_result = check_document_types(con, client, limit=10, delay_seconds=0)

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["status"] == "error"
    assert "404" in row["result"]
    assert enrichment_result.height == 0


def test_check_document_types_returns_empty_frames_with_correct_schema():
    con = _connect([])
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    result, enrichment_result = check_document_types(con, client, limit=10, delay_seconds=0)
    assert result.height == 0
    assert result.columns == ["party_id", "source", "queried_at", "result", "name", "status"]
    assert enrichment_result.height == 0
    assert enrichment_result.columns == [
        "party_id",
        "source",
        "queried_at",
        "result",
        "name",
        "active",
        "attributes",
        "status",
    ]


def test_check_document_types_reports_progress_every_n_and_on_the_last_one():
    con = _connect(
        [
            {
                "party_id": f"p{i}",
                "document_number": f"80000000{i}",
                "document_type": "natural_person",
                "document_type_rule_id": "nit_check_digit_invalid",
            }
            for i in range(5)
        ]
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"registros": [], "cant_registros": 0})
        )
    )
    calls: list[tuple[int, int]] = []
    result, _ = check_document_types(
        con,
        client,
        limit=10,
        delay_seconds=0,
        progress_every=2,
        on_progress=lambda done, total: calls.append((done, total)),
    )

    assert result.height == 5
    assert calls == [(2, 5), (4, 5), (5, 5)]
