import duckdb
import polars as pl

from claims_engine.duckdb_utils import to_polars


def test_to_polars_types_all_null_column_by_duckdb_type_not_by_value():
    # A column that's entirely NULL in every row has no non-null value to
    # hint its type -- must still come back as the declared VARCHAR/BIGINT
    # type, not polars' `Null` dtype (which fails downstream pandera
    # contracts that expect String/Int64).
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a VARCHAR, b BIGINT)")
    con.execute("INSERT INTO t VALUES (NULL, NULL), (NULL, NULL)")

    df = to_polars(con.execute("SELECT a, b FROM t"))

    assert df.schema["a"] == pl.Utf8
    assert df.schema["b"] == pl.Int64
    assert df.height == 2


def test_to_polars_preserves_real_values():
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a VARCHAR, b BIGINT)")
    con.execute("INSERT INTO t VALUES ('x', 1), (NULL, 2)")

    df = to_polars(con.execute("SELECT a, b FROM t"))

    assert df["a"].to_list() == ["x", None]
    assert df["b"].to_list() == [1, 2]
