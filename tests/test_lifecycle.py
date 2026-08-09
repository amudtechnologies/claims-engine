import duckdb

from claims_engine.lifecycle import (
    build_claim_parties,
    build_claims,
    build_observations,
    claim_id,
    measure_persistence,
)

_COLUMNS = [
    "capture_id",
    "sheet",
    "source_row",
    "period",
    "court_account",
    "deposit_no",
    "deposit_type",
    "amount_cop",
    "origin_date",
    "classification",
    "source_extra",
    "plaintiff_id",
    "plaintiff_id_type",
    "defendant_id",
    "defendant_id_type",
]


def _connect_with_dep(rows: list[dict]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE dep (
            capture_id VARCHAR, sheet VARCHAR, source_row INTEGER, period VARCHAR,
            court_account VARCHAR, deposit_no VARCHAR, deposit_type VARCHAR,
            amount_cop BIGINT, origin_date DATE, classification VARCHAR, source_extra VARCHAR,
            plaintiff_id VARCHAR, plaintiff_id_type VARCHAR,
            defendant_id VARCHAR, defendant_id_type VARCHAR
        )
        """
    )
    for i, row in enumerate(rows):
        defaults = {c: None for c in _COLUMNS}
        defaults.update(sheet="Busqueda", source_row=i, capture_id=f"cap-{row.get('period')}")
        defaults.update(row)
        placeholders = ", ".join(f"${c}" for c in _COLUMNS)
        con.execute(f"INSERT INTO dep VALUES ({placeholders})", defaults)
    return con


def test_build_claims_collapses_exact_duplicate_rows_into_one_claim():
    con = _connect_with_dep(
        [
            {
                "period": "2020-1",
                "court_account": "058092044001",
                "deposit_no": "12345",
                "amount_cop": 500000,
                "source_row": 0,
            },
            {
                "period": "2020-1",
                "court_account": "058092044001",
                "deposit_no": "12345",
                "amount_cop": 500000,
                "source_row": 1,
            },
        ]
    )
    claims = build_claims(con)
    observations = build_observations(con)

    assert claims.height == 1
    assert observations.height == 2
    assert observations["claim_id"].to_list() == [claims.row(0, named=True)["claim_id"]] * 2


def test_build_claims_genuine_collision_uses_most_recent_observation():
    con = _connect_with_dep(
        [
            {
                "period": "2019-1",
                "court_account": "058092044001",
                "deposit_no": "999",
                "amount_cop": 100000,
                "source_row": 0,
            },
            {
                "period": "2020-1",
                "court_account": "058092044001",
                "deposit_no": "999",
                "amount_cop": 200000,
                "source_row": 0,
            },
        ]
    )
    claims = build_claims(con)
    assert claims.height == 1
    assert claims.row(0, named=True)["amount_cop"] == 200000  # 2020-1 is more recent


def test_build_claims_no_court_account_fallback_matches_across_periods():
    # 2018-1/2018-2 style: no court_account column at all, deposit_no alone
    # is the verified-reliable key for those two periods.
    con = _connect_with_dep(
        [
            {"period": "2018-1", "court_account": None, "deposit_no": "555", "amount_cop": 1},
            {"period": "2018-2", "court_account": None, "deposit_no": "555", "amount_cop": 2},
        ]
    )
    claims = build_claims(con)
    assert claims.height == 1
    assert claims.row(0, named=True)["court_id"] is None


def test_build_observations_excludes_2017_1_entirely():
    con = _connect_with_dep(
        [
            {"period": "2017-1", "court_account": None, "deposit_no": "1", "amount_cop": 1},
            {
                "period": "2020-1",
                "court_account": "058092044001",
                "deposit_no": "2",
                "amount_cop": 1,
            },
        ]
    )
    observations = build_observations(con)
    assert observations.height == 1
    claims = build_claims(con)
    assert claims.height == 1


def test_build_claim_parties_links_plaintiff_and_defendant():
    con = _connect_with_dep(
        [
            {
                "period": "2020-1",
                "court_account": "058092044001",
                "deposit_no": "1",
                "plaintiff_id": "900123456",
                "defendant_id": "80123456",
            }
        ]
    )
    claim_parties = build_claim_parties(con)
    assert set(claim_parties["procedural_role"].to_list()) == {"plaintiff", "defendant"}


def test_measure_persistence_reports_overlap_between_consecutive_periods():
    con = _connect_with_dep(
        [
            {"period": "2020-1", "court_account": "058092044001", "deposit_no": "1"},
            {"period": "2020-1", "court_account": "058092044001", "deposit_no": "2"},
            {"period": "2020-2", "court_account": "058092044001", "deposit_no": "1"},
        ]
    )
    stats = measure_persistence(con)
    assert stats.height == 1
    row = stats.row(0, named=True)
    assert row["prev_period"] == "2020-1"
    assert row["period"] == "2020-2"
    assert row["prev_count"] == 2
    assert row["overlap"] == 1
    assert row["overlap_pct"] == 50.0


def test_claim_id_is_deterministic_and_namespace_separated():
    assert claim_id("058092044001", "1") == claim_id("058092044001", "1")
    assert claim_id("058092044001", "1") != claim_id(None, "1")
