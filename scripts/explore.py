"""Ad-hoc querying against the S3 data lake with DuckDB.

    AWS_PROFILE=amud-technologies uv run python
    >>> from scripts.explore import connect
    >>> con = connect()
    >>> con.execute("SELECT count(*) FROM claim").pl()

`.pl()` returns a polars DataFrame, which prints as a table -- use it instead
of `.fetchall()` (raw tuples) whenever you want to eyeball results.

`connect()` registers every core table as a DuckDB view (named after the
table, e.g. `claim`, `party`, `enrichment`) so queries don't need the full
s3:// path spelled out each time.
"""

from __future__ import annotations

import duckdb

BUCKET = "amud-technologies"

_CORE_TABLES = [
    "party",
    "court",
    "court_name",
    "claim",
    "observation",
    "claim_party",
    "file",
    "capture",
]


def connect() -> duckdb.DuckDBPyConnection:
    """A DuckDB connection with S3 access configured and every core table
    (plus RUES enrichment) registered as a view, ready to query."""
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(
        "CREATE SECRET aws_amud (TYPE S3, PROVIDER CREDENTIAL_CHAIN, PROFILE 'amud-technologies');"
    )
    for table in _CORE_TABLES:
        con.execute(
            f"CREATE VIEW {table} AS "
            f"SELECT * FROM read_parquet('s3://{BUCKET}/core/{table}/current.parquet')"
        )
    # Batches accumulate over time and older ones may lack newer columns
    # (e.g. `status`, added after the first few RUES batches) -- union_by_name
    # fills those in as NULL instead of erroring.
    con.execute(
        "CREATE VIEW enrichment AS "
        f"SELECT * FROM read_parquet('s3://{BUCKET}/core/enrichment/source=RUES/*.parquet', "
        "union_by_name=true)"
    )
    return con


def example_query(con: duckdb.DuckDBPyConnection):
    """Placeholder -- replace with a real query."""
    return con.execute("SELECT count(*) FROM claim").pl()


def top_plaintiffs_by_value(con: duckdb.DuckDBPyConnection, period: str, limit: int = 100):
    """Top plaintiffs by total claim value in one publication period. period lives
    on `file`, not `claim`, so it has to come in through observation/capture/file.
    procedural_role is a fact from the source (rule 6) -- this is not a claim
    about who the money belongs to.

    party_name comes from the latest RUES enrichment row per party (append-only,
    D20 -- never overwritten, so the most recent `queried_at` wins). Enrichment
    only exists for legal entities (rule 8), so natural persons show NULL here --
    that is the expected, permanent state (D21), not missing data."""
    return con.execute(
        f"""
        WITH period_claims AS (
            SELECT DISTINCT o.claim_id
            FROM observation o
            JOIN capture c USING (capture_id)
            JOIN file f USING (file_id)
            WHERE f.period = $period
        ),
        latest_enrichment AS (
            SELECT party_id, name
            FROM enrichment
            QUALIFY row_number() OVER (PARTITION BY party_id ORDER BY queried_at DESC) = 1
        )
        SELECT p.document_number, p.document_type, le.name AS party_name,
            count(*) AS n_claims, sum(cl.amount_cop) AS total_cop, count(*) * 5000000
        FROM period_claims pc
        JOIN claim cl ON cl.claim_id = pc.claim_id
        JOIN claim_party cp ON cp.claim_id = cl.claim_id
        JOIN party p USING (party_id)
        LEFT JOIN latest_enrichment le USING (party_id)
        WHERE cp.procedural_role = 'plaintiff'
            AND p.document_type = 'legal_entity'
        GROUP BY 1, 2, 3
        HAVING sum(cl.amount_cop) >= count(*) * 5000000
        ORDER BY total_cop ASC
        LIMIT {limit}
        """,
        {"period": period},
    ).pl()


def claims_detail(
    con: duckdb.DuckDBPyConnection,
    period: str,
    min_amount_cop: int = 5_000_000,
    limit: int = 100,
):
    """Per-claim detail for one period: both parties (with enrichment name where
    available -- legal entities only, rule 8) and court information. Two separate
    claim_party joins because it's an N:M bridge disambiguated only by
    procedural_role, a fact from the source (rule 6) -- plaintiff/defendant here is
    not a claim about who the money belongs to (that's the deferred economic-role
    inference, see docs/project-context.md Phase 6)."""
    return con.execute(
        f"""
        WITH period_claims AS (
            SELECT DISTINCT o.claim_id
            FROM observation o
            JOIN capture c USING (capture_id)
            JOIN file f USING (file_id)
            WHERE f.period = $period
        ),
        latest_enrichment AS (
            SELECT party_id, name
            FROM enrichment
            QUALIFY row_number() OVER (PARTITION BY party_id ORDER BY queried_at DESC) = 1
        ),
        period_court_name AS (
            SELECT court_id, name
            FROM court_name
            WHERE $period BETWEEN first_period AND last_period
            QUALIFY row_number() OVER (PARTITION BY court_id ORDER BY last_period DESC) = 1
        )
        SELECT
            plaintiff.document_number AS plaintiff_document_number,
            plaintiff_enrichment.name AS plaintiff_name,
            defendant.document_number AS defendant_document_number,
            defendant_enrichment.name AS defendant_name,
            cn.name AS court_name,
            co.city AS court_city,
            co.judicial_district,
            cl.case_number,
            cl.amount_cop,
        FROM period_claims pc
        JOIN claim cl ON cl.claim_id = pc.claim_id
        JOIN claim_party plaintiff_cp
            ON plaintiff_cp.claim_id = cl.claim_id AND plaintiff_cp.procedural_role = 'plaintiff'
        JOIN party plaintiff ON plaintiff.party_id = plaintiff_cp.party_id
        LEFT JOIN latest_enrichment plaintiff_enrichment
            ON plaintiff_enrichment.party_id = plaintiff.party_id
        JOIN claim_party defendant_cp
            ON defendant_cp.claim_id = cl.claim_id AND defendant_cp.procedural_role = 'defendant'
        JOIN party defendant ON defendant.party_id = defendant_cp.party_id
        LEFT JOIN latest_enrichment defendant_enrichment
            ON defendant_enrichment.party_id = defendant.party_id
        LEFT JOIN court co ON co.court_id = cl.court_id
        LEFT JOIN period_court_name cn ON cn.court_id = co.court_id
        WHERE cl.amount_cop > $min_amount_cop 
              AND plaintiff.document_type = 'legal_entity'
        ORDER BY cl.amount_cop ASC
        LIMIT {limit}
        """,
        {"period": period, "min_amount_cop": min_amount_cop},
    ).pl()


def main() -> None:
    con = connect()
    # print(example_query(con))
    # print(top_plaintiffs_by_value(con, "2026-1"))
    print(claims_detail(con, "2026-1"))


if __name__ == "__main__":
    main()
