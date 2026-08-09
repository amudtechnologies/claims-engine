import duckdb

from claims_engine.identity import build_courts_and_names, build_parties, classify_party


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


def test_classify_party_source_declared_wins():
    canonical, doc_type, confidence, rule_id = classify_party(
        "9001234561", "NIT (NRO.IDENTIF. TRIBUTARIA)"
    )
    assert (canonical, doc_type, confidence, rule_id) == (
        "9001234561",
        "legal_entity",
        1.0,
        "source_declared",
    )


def test_classify_party_source_declared_legal_entity_strips_valid_check_digit():
    # base 900123456 -> DIAN check digit 8 (verified worked example)
    canonical, doc_type, confidence, rule_id = classify_party(
        "9001234568", "NIT (NRO.IDENTIF. TRIBUTARIA)"
    )
    assert canonical == "900123456"
    assert doc_type == "legal_entity"
    assert confidence == 1.0
    assert rule_id == "source_declared"


def test_classify_party_source_declared_natural_person_overridden_by_valid_check_digit():
    # base 123456789 -> DIAN check digit 6 (verified worked example). A
    # validating check digit is real evidence the source's own 2023-2 label
    # got wrong -- confirmed at scale (2,513 of 17,726 such parties).
    canonical, doc_type, confidence, rule_id = classify_party("1234567896", "CEDULA CIUDADANIA")
    assert canonical == "123456789"
    assert doc_type == "legal_entity"
    assert confidence == 0.85
    assert rule_id == "source_declared_overridden_by_check_digit"


def test_classify_party_source_declared_natural_person_kept_when_check_digit_invalid():
    # No contradicting evidence here -- left alone, unstripped, at full
    # confidence. Cedulas have no check-digit concept.
    canonical, doc_type, confidence, rule_id = classify_party("1234567890", "CEDULA CIUDADANIA")
    assert canonical == "1234567890"
    assert doc_type == "natural_person"
    assert confidence == 1.0
    assert rule_id == "source_declared"


def test_classify_party_valid_nit_check_digit_strips_check_digit():
    # base 123456789 -> DIAN check digit 6 (verified worked example)
    canonical, doc_type, confidence, rule_id = classify_party("1234567896", None)
    assert canonical == "123456789"
    assert doc_type == "legal_entity"
    assert rule_id == "nit_check_digit_valid"
    assert confidence > 0.5


def test_classify_party_invalid_check_digit_falls_back_to_natural_person():
    canonical, doc_type, confidence, rule_id = classify_party("1234567890", None)
    assert doc_type == "natural_person"
    assert canonical == "1234567890"  # not stripped, we're not confident it's a NIT
    assert rule_id == "nit_check_digit_invalid"


def test_classify_party_short_id_defaults_natural_person():
    canonical, doc_type, confidence, rule_id = classify_party("80123456", None)
    assert doc_type == "natural_person"
    assert rule_id == "length_default"
    assert canonical == "80123456"


def test_build_parties_dedupes_and_prefers_declared_type():
    con = _connect_with_dep(
        [
            {"plaintiff_id": "80123456", "period": "2020-1"},
            {"defendant_id": "80123456", "period": "2021-1"},  # same id, no declared type here
            {
                "plaintiff_id": "80123456",
                "plaintiff_id_type": "CEDULA DE CIUDADANIA",
                "period": "2023-2",
            },
        ]
    )
    parties = build_parties(con)
    assert parties.height == 1
    row = parties.row(0, named=True)
    assert row["document_number"] == "80123456"
    assert row["document_type"] == "natural_person"
    assert row["document_type_rule_id"] == "source_declared"
    assert row["document_type_confidence"] == 1.0


def test_build_parties_majority_vote_beats_alphabetical_max():
    # NIT declared 3x, a differently-labeled natural-person-type declared
    # once. The old max(declared_type) would have picked "TARJETA..." purely
    # because it sorts alphabetically after "NIT..." -- majority vote must
    # pick NIT since it's the actually-dominant declaration.
    con = _connect_with_dep(
        [
            {
                "plaintiff_id": "9001234568",
                "plaintiff_id_type": "NIT (NRO.IDENTIF. TRIBUTARIA)",
                "period": "2023-2",
            },
            {
                "plaintiff_id": "9001234568",
                "plaintiff_id_type": "NIT (NRO.IDENTIF. TRIBUTARIA)",
                "period": "2023-2",
            },
            {
                "defendant_id": "9001234568",
                "defendant_id_type": "NIT (NRO.IDENTIF. TRIBUTARIA)",
                "period": "2023-2",
            },
            {
                "plaintiff_id": "9001234568",
                "plaintiff_id_type": "TARJETA DE IDENTIDAD",
                "period": "2023-2",
            },
        ]
    )
    parties = build_parties(con)
    assert parties.height == 1
    row = parties.row(0, named=True)
    assert row["document_number"] == "900123456"
    assert row["document_type"] == "legal_entity"
    assert row["document_type_rule_id"] == "source_declared"


def test_build_parties_collapses_check_digit_collision_keeping_higher_confidence():
    # "1234567896" strips to canonical "123456789" via a valid NIT check
    # digit; "123456789" already exists as its own raw id. Both must
    # collapse into one party row, keeping the higher-confidence one.
    con = _connect_with_dep(
        [
            {"plaintiff_id": "1234567896", "period": "2020-1"},
            {"defendant_id": "123456789", "period": "2020-1"},
        ]
    )
    parties = build_parties(con)
    assert parties.filter(parties["document_number"] == "123456789").height == 1


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
