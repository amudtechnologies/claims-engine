"""Tiny shared helper for modules that run SQL through an in-process duckdb
connection and want the result as a polars DataFrame."""

from __future__ import annotations

import duckdb
import polars as pl

# DuckDB's declared result type, per column, wins over polars' own value-based
# inference below. A column that's entirely NULL in every returned row (a real
# case: a single despacho's per-court aggregate for a field like `seccional`
# it never populates) has no non-null value anywhere to hint the intended
# dtype, so bare value-based inference silently produces polars' `Null` dtype
# instead of the column's real type -- passing pandera's contract validation
# right up until the one query whose result happens to be all-NULL end to
# end. Falling back to `None` (inferred) for a duckdb type not listed here
# preserves the old value-based behavior for anything exotic.
_DUCKDB_TO_POLARS = {
    "VARCHAR": pl.Utf8,
    "BIGINT": pl.Int64,
    "INTEGER": pl.Int64,
    "SMALLINT": pl.Int64,
    "TINYINT": pl.Int64,
    "HUGEINT": pl.Int64,
    "DOUBLE": pl.Float64,
    "FLOAT": pl.Float64,
    "BOOLEAN": pl.Boolean,
    "DATE": pl.Date,
    "TIMESTAMP": pl.Datetime,
}


def to_polars(relation: duckdb.DuckDBPyRelation) -> pl.DataFrame:
    """duckdb's own `.pl()` needs pyarrow, which isn't in this project's
    dependency set — fetch as plain rows instead, no extra dependency.

    `infer_schema_length=None` scans every row before picking a dtype for any
    column duckdb's own type doesn't resolve above — real staging data is
    null-heavy enough in some columns (`origin_date`, `classification`...)
    that polars' default 100-row sample can lock in the wrong dtype and then
    choke on a later row."""
    columns = [d[0] for d in relation.description]
    duckdb_types = [str(d[1]) for d in relation.description]
    rows = relation.fetchall()
    schema = {name: _DUCKDB_TO_POLARS.get(t) for name, t in zip(columns, duckdb_types, strict=True)}
    return pl.DataFrame(rows, schema=schema, orient="row", infer_schema_length=None)
