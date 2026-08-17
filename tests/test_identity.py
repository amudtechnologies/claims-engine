import duckdb
import polars as pl

from claims_engine.identity import (
    apply_rues_classification,
    build_courts_and_names,
    build_parties,
    canonical_document_number,
)


def _connect_with_dep(rows: list[dict]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE dep (
            plaintiff_id VARCHAR, plaintiff_id_type VARCHAR,
            defendant_id VARCHAR, defendant_id_type VARCHAR,
            court_account VARCHAR, court_name VARCHAR,
            seccional VARCHAR, department VARCHAR, city VARCHAR,
            judicial_district VARCHAR, period VARCHAR
        )
        """
    )
    for row in rows:
        con.execute(
            """
            INSERT INTO dep VALUES
            ($plaintiff_id, $plaintiff_id_type, $defendant_id, $defendant_id_type,
             $court_account, $court_name, $seccional, $department, $city,
             $judicial_district, $period)
            """,
            {
                "plaintiff_id": None,
                "plaintiff_id_type": None,
                "defendant_id": None,
                "defendant_id_type": None,
                "court_account": None,
                "court_name": None,
                "seccional": None,
                "department": None,
                "city": None,
                "judicial_district": None,
                "period": None,
                **row,
            },
        )
    con.execute("CREATE VIEW placeholder AS SELECT 1")  # keep linters happy about unused con
    return con


def test_canonical_document_number_strips_valid_check_digit():
    # base 123456789 -> DIAN check digit 6 (verified worked example)
    assert canonical_document_number("1234567896") == "123456789"


def test_canonical_document_number_leaves_invalid_check_digit_unstripped():
    assert canonical_document_number("1234567890") == "1234567890"


def test_canonical_document_number_leaves_non_nit_length_unstripped():
    assert canonical_document_number("80123456") == "80123456"


def test_build_parties_dedupes_raw_ids_with_document_type_left_null():
    # document_type is no longer decided here (D26) -- it's null until
    # enrich_parties has actually queried RUES.
    con = _connect_with_dep(
        [
            {"plaintiff_id": "80123456", "period": "2020-1"},
            {"defendant_id": "80123456", "period": "2021-1"},
        ]
    )
    parties = build_parties(con)
    assert parties.height == 1
    row = parties.row(0, named=True)
    assert row["document_number"] == "80123456"
    assert row["document_type"] is None
    assert row["document_type_confidence"] is None
    assert row["document_type_rule_id"] is None


def test_build_parties_collapses_check_digit_collision():
    # "1234567896" strips to canonical "123456789" via a valid NIT check
    # digit; "123456789" already exists as its own raw id. Both must
    # collapse into one party row.
    con = _connect_with_dep(
        [
            {"plaintiff_id": "1234567896", "period": "2020-1"},
            {"defendant_id": "123456789", "period": "2020-1"},
        ]
    )
    parties = build_parties(con)
    assert parties.filter(parties["document_number"] == "123456789").height == 1


def test_apply_rues_classification_backfills_only_classified_parties():
    parties = pl.DataFrame(
        {
            "party_id": ["p1", "p2", "p3"],
            "document_number": ["900111111", "80111111", "900222222"],
            "document_type": [None, None, None],
            "document_type_confidence": [None, None, None],
            "document_type_rule_id": [None, None, None],
        }
    )
    classification = pl.DataFrame(
        {
            "party_id": ["p1"],
            "document_type": ["legal_entity"],
            "document_type_confidence": [1.0],
            "document_type_rule_id": ["rues_categoria"],
        }
    )
    result = apply_rues_classification(parties, classification)
    by_id = {row["party_id"]: row for row in result.iter_rows(named=True)}
    assert by_id["p1"]["document_type"] == "legal_entity"
    assert by_id["p1"]["document_type_rule_id"] == "rues_categoria"
    assert by_id["p2"]["document_type"] is None
    assert by_id["p3"]["document_type"] is None


def test_build_courts_and_names_pads_and_dedupes_valid_accounts():
    con = _connect_with_dep(
        [
            {
                "court_account": "58092044001",  # 11 digits
                "court_name": "Juzgado 1 Civil",
                "city": "Bogota",
                "period": "2020-1",
            },
            {
                "court_account": "058092044001",  # same real account, 12 digits
                "court_name": "Juzgado 1 Civil",
                "city": "Bogota",
                "period": "2021-1",
            },
            {
                "court_account": "058092044001",
                "court_name": "Juzgado Primero Civil",  # renamed later
                "city": "Bogota",
                "period": "2022-1",
            },
        ]
    )
    courts, court_names = build_courts_and_names(con)
    assert courts.height == 1
    assert courts.row(0, named=True)["court_account"] == "058092044001"

    names_for_court = court_names.sort("first_period")
    assert names_for_court["name"].to_list() == ["Juzgado 1 Civil", "Juzgado Primero Civil"]
    first_row = names_for_court.row(0, named=True)
    assert first_row["first_period"] == "2020-1"
    assert first_row["last_period"] == "2021-1"


def test_build_courts_and_names_excludes_corrupted_and_null_accounts():
    con = _connect_with_dep(
        [
            {"court_account": "5", "court_name": "Corrupted", "period": "2020-1"},
            {"court_account": None, "court_name": "No account column", "period": "2017-1"},
            {
                "court_account": "058092044001",
                "court_name": "Juzgado 1 Civil",
                "period": "2020-1",
            },
        ]
    )
    courts, court_names = build_courts_and_names(con)
    assert courts.height == 1
    assert courts.row(0, named=True)["court_account"] == "058092044001"
