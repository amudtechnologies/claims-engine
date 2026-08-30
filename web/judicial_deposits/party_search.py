"""The document-number search (NIT or cédula — D28), run live against the
local `core/` cache (see `core_cache.py`). Recomputes a
`marts.party_summary`-shaped aggregation at query time straight off `core`
facts — there is no materialized marts table yet (Phase 6/marts is still
deferred, project-context.md §7).

`document_number` here follows the pipeline's own convention: digits only,
NIT stored without its check digit (see CLAUDE.md "Conventions"). A cédula
has no check digit to strip, so `_candidate_document_numbers` below only ever
generates a stripped-digit candidate for NIT-length inputs (9-10 digits) — it
has no way to know in advance which kind of number it's holding (D26), so a
9-10 digit cédula harmlessly tries one extra, unmatched candidate before
falling through.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Literal

import duckdb
from django.utils import timezone

from claims_engine.lineage import SOURCE_ACTIVE_DEPOSITS

from . import core_cache
from .models import ClaimWindow

ProceduralRole = Literal["plaintiff", "defendant"]
DocumentType = Literal["legal_entity", "natural_person"]


@dataclass(frozen=True)
class Deposit:
    claim_id: str
    court_office: str | None
    amount_cop: int
    constituted_on: date
    procedural_role: ProceduralRole
    period: str | None
    source: str | None
    source_declared_name: str | None


@dataclass(frozen=True)
class PartySearchResult:
    document_number: str
    party_name: str | None
    document_type: DocumentType | None
    rues_active: bool | None
    deposits: list[Deposit]

    @property
    def deposit_count(self) -> int:
        return len(self.deposits)

    @property
    def total_amount_cop(self) -> int:
        return sum(deposit.amount_cop for deposit in self.deposits)

    @property
    def court_office_count(self) -> int:
        return len({deposit.court_office for deposit in self.deposits})

    @property
    def last_period(self) -> str | None:
        """The most recent period this party appears in — not necessarily
        the corpus-wide latest published period (see `latest_published_period`
        below): a party can go quiet for several publications and still show
        up earlier in the history."""
        periods = [deposit.period for deposit in self.deposits if deposit.period]
        return max(periods, default=None)

    def _by_role(self, role: ProceduralRole) -> list[Deposit]:
        return [deposit for deposit in self.deposits if deposit.procedural_role == role]

    @property
    def plaintiff_count(self) -> int:
        return len(self._by_role("plaintiff"))

    @property
    def plaintiff_amount_cop(self) -> int:
        return sum(deposit.amount_cop for deposit in self._by_role("plaintiff"))

    @property
    def defendant_count(self) -> int:
        return len(self._by_role("defendant"))

    @property
    def defendant_amount_cop(self) -> int:
        return sum(deposit.amount_cop for deposit in self._by_role("defendant"))

    @property
    def source_declared_name(self) -> str | None:
        """A name the source itself stated for this party (project-context.md
        §6: `claim_party.attributes`, provenance is the file, not a lookup) —
        distinct from `party_name`, which only ever comes from a RUES
        enrichment and must never be conflated with this: a source-declared
        name is not "verified" the way a RUES match is. Picks the most
        recent period among deposits that actually carry one — a party can
        have claims from several deposits/periods, only some of which state
        a name."""
        named = [d for d in self.deposits if d.source_declared_name and d.period]
        if not named:
            return None
        return max(named, key=lambda d: d.period).source_declared_name

    def source_for_period(self, period: str) -> str | None:
        """The radar a period's deposits came from — a period is never mixed
        across radars (a semester label vs. an active-deposits batch date
        can't collide), so the first match's source speaks for the period."""
        for deposit in self.deposits:
            if deposit.period == period:
                return deposit.source
        return None

    def for_period(self, period: str) -> PartySearchResult | None:
        """The same result restricted to one publication period. `None` when
        the party has no deposits in that period — distinct from no match at
        all, which is `search_party` returning `None` in the first place."""
        deposits = [deposit for deposit in self.deposits if deposit.period == period]
        if not deposits:
            return None
        return PartySearchResult(
            document_number=self.document_number,
            party_name=self.party_name,
            document_type=self.document_type,
            rues_active=self.rues_active,
            deposits=deposits,
        )


def claim_window(period: str | None) -> ClaimWindow | None:
    """The configured 20-business-day claim window for a publication period,
    or None when no window has been entered yet — a permanent, valid unset
    state (see `ClaimWindow`'s docstring), not an error."""
    if not period:
        return None
    return ClaimWindow.objects.filter(period=period).first()


def claim_status(window: ClaimWindow | None, source: str | None = None) -> str | None:
    """"activo" for a deposit from the active-deposits radar — it was never
    part of a 20-business-day-countdown publication, so it's never checked
    against a `ClaimWindow` at all (a data-entry lag on a real expiring
    period must stay distinguishable from this — see the module docstring
    above `claim_window`). Otherwise "reclamable" / "no_reclamable" for a
    configured claim window, or None when no window has been configured yet
    for that period."""
    if source == SOURCE_ACTIVE_DEPOSITS:
        return "activo"
    if not window:
        return None
    return "reclamable" if timezone.localdate() <= window.closes_on else "no_reclamable"


def normalize_document_number(raw_value: str) -> str:
    """Digits only — mirrors the pipeline's national-ID normalization rule."""
    return "".join(character for character in raw_value if character.isdigit())


def _candidate_document_numbers(digits: str) -> list[str]:
    """Tries the digits as given, then the check-digit-stripped form — the
    same candidate order the pipeline's own RUES lookup uses (see
    `claims_engine.enrichment._candidate_document_numbers`): a NIT typed with
    its check digit (e.g. "900123456-7") should still resolve to the record
    stored without one."""
    candidates = [digits]
    if len(digits) in (9, 10):
        base = digits[:-1]
        if base not in candidates:
            candidates.append(base)
    return candidates


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def latest_published_period() -> str | None:
    """The most recent semester published across the whole corpus — a
    property of the dataset, not of any one party (see project-context.md
    §8.5 on whether it's still "current")."""
    con = _connect()
    row = con.execute(
        f"SELECT MAX(period) FROM read_parquet('{core_cache.table_path('file')}')"
    ).fetchone()
    return row[0] if row else None


def total_observation_count() -> int:
    """Corpus-wide row count of `core/observation` — one row per claim seen
    in one capture (see project-context.md §4 glossary). Backs the "N
    observaciones registradas" proof stat."""
    con = _connect()
    row = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{core_cache.table_path('observation')}')"
    ).fetchone()
    return row[0] if row else 0


def total_claim_amount_cop() -> int:
    """Corpus-wide sum of `core/claim.amount_cop` — every deposit's face
    value across the whole 2017-2026 history, claimed or not. Backs the
    "total involved" stat next to the despachos/partes counts."""
    con = _connect()
    row = con.execute(
        f"SELECT SUM(amount_cop) FROM read_parquet('{core_cache.table_path('claim')}')"
    ).fetchone()
    return row[0] if row and row[0] is not None else 0


def total_court_count() -> int:
    """Corpus-wide row count of `core/court` — canonical court offices
    resolved by identity (Phase 3, project-context.md §7)."""
    con = _connect()
    row = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{core_cache.table_path('court')}')"
    ).fetchone()
    return row[0] if row else 0


def total_party_count() -> int:
    """Corpus-wide row count of `core/party` — canonical parties resolved by
    identity (Phase 3, project-context.md §7)."""
    con = _connect()
    row = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{core_cache.table_path('party')}')"
    ).fetchone()
    return row[0] if row else 0


def _find_party(con: duckdb.DuckDBPyConnection, digits: str) -> tuple[str, str, str | None] | None:
    for candidate in _candidate_document_numbers(digits):
        row = con.execute(
            f"""
            SELECT party_id, document_number, document_type
            FROM read_parquet('{core_cache.table_path('party')}')
            WHERE document_number = ?
            """,
            [candidate],
        ).fetchone()
        if row:
            return row
    return None


def _fetch_enrichment(
    con: duckdb.DuckDBPyConnection, party_id: str
) -> tuple[str | None, bool | None]:
    row = con.execute(
        f"""
        SELECT name, active
        FROM read_parquet('{core_cache.enrichment_glob()}')
        WHERE party_id = ?
        ORDER BY queried_at DESC
        LIMIT 1
        """,
        [party_id],
    ).fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


def _fetch_deposits(con: duckdb.DuckDBPyConnection, party_id: str) -> list[Deposit]:
    rows = con.execute(
        f"""
        WITH party_claims AS (
            SELECT cp.claim_id, cp.procedural_role, cp.attributes, c.court_id,
                   c.amount_cop, c.origin_date
            FROM read_parquet('{core_cache.table_path('claim_party')}') cp
            JOIN read_parquet('{core_cache.table_path('claim')}') c USING (claim_id)
            WHERE cp.party_id = ?
        ),
        claim_periods AS (
            -- A claim can carry observations from both radars (e.g. an
            -- active deposit later published as expiring) -- picks the
            -- (period, source) pair belonging to the single latest
            -- observation, not an independent MAX(period) next to an
            -- arbitrary source, which could pair a claim's newest period
            -- with a stale source.
            SELECT o.claim_id, f.period, f.source
            FROM read_parquet('{core_cache.table_path('observation')}') o
            JOIN read_parquet('{core_cache.table_path('capture')}') cap USING (capture_id)
            JOIN read_parquet('{core_cache.table_path('file')}') f USING (file_id)
            WHERE o.claim_id IN (SELECT claim_id FROM party_claims)
            QUALIFY ROW_NUMBER() OVER (PARTITION BY o.claim_id ORDER BY f.period DESC) = 1
        ),
        court_names AS (
            SELECT court_id, name
            FROM read_parquet('{core_cache.table_path('court_name')}')
            QUALIFY ROW_NUMBER() OVER (PARTITION BY court_id ORDER BY last_period DESC) = 1
        )
        SELECT
            party_claims.claim_id,
            court_names.name AS court_office,
            party_claims.amount_cop,
            party_claims.origin_date,
            party_claims.procedural_role,
            claim_periods.period,
            claim_periods.source,
            party_claims.attributes
        FROM party_claims
        LEFT JOIN claim_periods USING (claim_id)
        LEFT JOIN court_names USING (court_id)
        """,
        [party_id],
    ).fetchall()
    return [
        Deposit(
            claim_id=claim_id,
            court_office=court_office,
            amount_cop=amount_cop,
            constituted_on=origin_date,
            procedural_role=procedural_role,
            period=period,
            source=source,
            source_declared_name=json.loads(attributes)["name"] if attributes else None,
        )
        for (
            claim_id,
            court_office,
            amount_cop,
            origin_date,
            procedural_role,
            period,
            source,
            attributes,
        ) in rows
    ]


def search_party(raw_value: str) -> PartySearchResult | None:
    digits = normalize_document_number(raw_value)
    if not digits:
        return None

    con = _connect()
    match = _find_party(con, digits)
    if match is None:
        return None
    party_id, document_number, document_type = match

    party_name, rues_active = _fetch_enrichment(con, party_id)
    deposits = _fetch_deposits(con, party_id)

    return PartySearchResult(
        document_number=document_number,
        party_name=party_name,
        document_type=document_type,
        rues_active=rues_active,
        deposits=deposits,
    )
