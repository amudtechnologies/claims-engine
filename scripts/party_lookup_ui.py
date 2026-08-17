"""Lightweight validation UI: type a party identification number, see its
aggregate metrics. Not a serving surface -- marts/Postgres don't exist yet
(Phase 6 is deferred, see docs/project-context.md §7) and this isn't meant
to become one. It reads `core/` straight off S3 with DuckDB, same pattern as
`scripts/explore.py`, just wrapped in a search box for eyeballing results
without writing SQL by hand each time.

    uv run streamlit run scripts/party_lookup_ui.py

Every search re-derives the canonical `party_id` from the typed number
(`identity.canonical_document_number` + `identity.party_id`, the exact
functions `build-identity` uses) and filters on it -- no separate index,
just DuckDB scanning the parquet files under `core/`.
"""

from __future__ import annotations

import re

import duckdb
import streamlit as st

from claims_engine.identity import canonical_document_number
from claims_engine.identity import party_id as compute_party_id

st.set_page_config(page_title="Party lookup", page_icon="🔎", layout="centered")

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


@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    """Mirrors scripts/explore.py's connect() -- duplicated rather than
    imported, since `scripts` isn't a package and relying on it landing on
    sys.path is fragile across how `streamlit run` gets invoked."""
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
    con.execute(
        "CREATE VIEW enrichment AS "
        f"SELECT * FROM read_parquet('s3://{BUCKET}/core/enrichment/source=RUES/*.parquet', "
        "union_by_name=true)"
    )
    return con


def fetch_party_metrics(con: duckdb.DuckDBPyConnection, party_id: str) -> tuple | None:
    """Aggregate metrics for a party: overall totals, a plaintiff/defendant
    breakdown, and the same breakdown scoped to only the latest publication
    period this party appeared in. None if the party_id has no row in
    `core/party` (never seen as plaintiff or defendant in any capture --
    not an error, just not a party we know)."""
    return con.execute(
        """
        WITH target_party AS (
            SELECT * FROM party WHERE party_id = $party_id
        ),
        latest_enrichment AS (
            SELECT *
            FROM enrichment
            WHERE party_id = $party_id
            QUALIFY row_number() OVER (ORDER BY queried_at DESC) = 1
        ),
        party_claims AS (
            SELECT cl.claim_id, cl.amount_cop, cl.court_id, cp.procedural_role
            FROM claim_party cp
            JOIN claim cl ON cl.claim_id = cp.claim_id
            WHERE cp.party_id = $party_id
        ),
        claim_periods AS (
            SELECT DISTINCT o.claim_id, f.period
            FROM observation o
            JOIN capture c USING (capture_id)
            JOIN file f USING (file_id)
            WHERE o.claim_id IN (SELECT claim_id FROM party_claims)
        ),
        latest_period AS (
            SELECT max(period) AS period FROM claim_periods
        ),
        latest_period_claims AS (
            SELECT pc.*
            FROM party_claims pc
            JOIN claim_periods cpd ON cpd.claim_id = pc.claim_id
            WHERE cpd.period = (SELECT period FROM latest_period)
        )
        SELECT
            tp.document_number,
            tp.document_type,
            le.name AS rues_name,
            le.active AS rues_active,
            le.categoria AS rues_categoria,
            (SELECT count(DISTINCT court_id) FROM party_claims WHERE court_id IS NOT NULL)
                AS n_courts,
            (SELECT count(DISTINCT period) FROM claim_periods) AS n_periods,
            (SELECT coalesce(sum(amount_cop), 0) FROM party_claims) AS total_amount,
            (SELECT count(*) FROM party_claims WHERE procedural_role = 'plaintiff')
                AS claims_as_plaintiff,
            (SELECT coalesce(sum(amount_cop), 0) FROM party_claims
                WHERE procedural_role = 'plaintiff') AS amount_as_plaintiff,
            (SELECT count(*) FROM party_claims WHERE procedural_role = 'defendant')
                AS claims_as_defendant,
            (SELECT coalesce(sum(amount_cop), 0) FROM party_claims
                WHERE procedural_role = 'defendant') AS amount_as_defendant,
            (SELECT period FROM latest_period) AS latest_period,
            (SELECT count(DISTINCT court_id) FROM latest_period_claims WHERE court_id IS NOT NULL)
                AS latest_period_n_courts,
            (SELECT count(*) FROM latest_period_claims WHERE procedural_role = 'plaintiff')
                AS latest_period_claims_as_plaintiff,
            (SELECT coalesce(sum(amount_cop), 0) FROM latest_period_claims
                WHERE procedural_role = 'plaintiff') AS latest_period_amount_as_plaintiff,
            (SELECT count(*) FROM latest_period_claims WHERE procedural_role = 'defendant')
                AS latest_period_claims_as_defendant,
            (SELECT coalesce(sum(amount_cop), 0) FROM latest_period_claims
                WHERE procedural_role = 'defendant') AS latest_period_amount_as_defendant
        FROM target_party tp
        LEFT JOIN latest_enrichment le ON true
        """,
        {"party_id": party_id},
    ).fetchone()


def format_cop(value: int) -> str:
    return f"${value:,.0f}"


def render_metrics(row: tuple) -> None:
    (
        document_number,
        document_type,
        rues_name,
        rues_active,
        rues_categoria,
        n_courts,
        n_periods,
        total_amount,
        claims_as_plaintiff,
        amount_as_plaintiff,
        claims_as_defendant,
        amount_as_defendant,
        latest_period,
        latest_period_n_courts,
        latest_period_claims_as_plaintiff,
        latest_period_amount_as_plaintiff,
        latest_period_claims_as_defendant,
        latest_period_amount_as_defendant,
    ) = row

    st.subheader(f"Party {document_number}")

    with st.container(border=True):
        st.caption("RUES")
        status_cols = st.columns(2)
        status_cols[0].metric("Document type", document_type or "unclassified")
        status_cols[1].metric(
            "Active", "—" if rues_active is None else ("Yes" if rues_active else "No")
        )
        st.markdown(f"**Name:** {rues_name or 'not enriched'}")
        st.markdown(f"**Categoria:** {rues_categoria or '—'}")

    summary_cols = st.columns(3)
    summary_cols[0].metric("Court offices", n_courts)
    summary_cols[1].metric("Publication periods", n_periods)
    summary_cols[2].metric("Total money involved (COP)", format_cop(total_amount))

    with st.expander("Breakdown by procedural role (all periods)"):
        role_cols = st.columns(2)
        with role_cols[0]:
            st.markdown("**As plaintiff**")
            st.metric("Deposits", claims_as_plaintiff)
            st.metric("Amount (COP)", format_cop(amount_as_plaintiff))
        with role_cols[1]:
            st.markdown("**As defendant**")
            st.metric("Deposits", claims_as_defendant)
            st.metric("Amount (COP)", format_cop(amount_as_defendant))
        st.caption(
            "Plaintiff/defendant are the source's procedural roles (fact), not a "
            "claim about who the money belongs to -- economic-role inference is "
            "deferred (CLAUDE.md rule 6, Phase 6)."
        )

    st.divider()
    if latest_period is None:
        st.caption("No publication period found for this party.")
        return

    st.markdown(f"**Latest period published: {latest_period}**")
    st.metric("Court offices (latest period)", latest_period_n_courts)
    latest_cols = st.columns(2)
    with latest_cols[0]:
        st.markdown("**As plaintiff**")
        st.metric("Deposits", latest_period_claims_as_plaintiff)
        st.metric("Amount (COP)", format_cop(latest_period_amount_as_plaintiff))
    with latest_cols[1]:
        st.markdown("**As defendant**")
        st.metric("Deposits", latest_period_claims_as_defendant)
        st.metric("Amount (COP)", format_cop(latest_period_amount_as_defendant))


def render() -> None:
    st.title("Party lookup")
    st.caption(
        "Validation tool: aggregate metrics for one party, read live from `core/` on S3."
    )

    with st.form("party_search"):
        raw_input = st.text_input("Party identification number", placeholder="e.g. 900123456")
        submitted = st.form_submit_button("Search")

    if not submitted:
        return

    digits = re.sub(r"\D", "", raw_input)
    if not digits:
        st.warning("Type a national ID (digits only).")
        return

    document_number = canonical_document_number(digits)
    party_id = compute_party_id(document_number)

    with st.spinner("Searching..."):
        con = get_connection()
        row = fetch_party_metrics(con, party_id)

    if row is None:
        st.warning(f"No party found for {digits} (never seen as plaintiff or defendant).")
        return

    render_metrics(row)


render()
