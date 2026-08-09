"""Tiny shared helper for modules that run SQL through an in-process duckdb
connection and want the result as a polars DataFrame."""

from __future__ import annotations

import duckdb
import polars as pl


def to_polars(relation: duckdb.DuckDBPyRelation) -> pl.DataFrame:
    """duckdb's own `.pl()` needs pyarrow, which isn't in this project's
    dependency set — fetch as plain rows instead, no extra dependency.

    `infer_schema_length=None` scans every row before picking a dtype per
    column — real staging data is null-heavy enough in some columns
    (`origin_date`, `classification`...) that polars' default 100-row
    sample can lock in the wrong dtype and then choke on a later row."""
    columns = [d[0] for d in relation.description]
    rows = relation.fetchall()
    return pl.DataFrame(rows, schema=columns, orient="row", infer_schema_length=None)
