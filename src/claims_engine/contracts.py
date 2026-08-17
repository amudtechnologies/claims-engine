"""Pandera contracts (D16) for the staging tables `normalize.py` produces. Validated
right before writing Parquet — the layer boundary between staging and everything
downstream.
"""

from __future__ import annotations

from datetime import date, datetime

import pandera.polars as pa

# Versions `StagingDepositSchema` explicitly (it was previously only implicit
# in the mapping code) -- bump whenever this schema's shape changes, so
# `core.capture.schema_version` means something.
SCHEMA_VERSION = "1"


class StagingDepositSchema(pa.DataFrameModel):
    capture_id: str
    period: str
    sheet: str
    source_row: int = pa.Field(ge=0)

    deposit_no_raw: str | None = pa.Field(nullable=True)
    deposit_no: str | None = pa.Field(nullable=True)
    deposit_type: str | None = pa.Field(nullable=True)
    classification: str | None = pa.Field(nullable=True)
    court_account: str | None = pa.Field(nullable=True)
    court_name: str | None = pa.Field(nullable=True)
    plaintiff_id_raw: str | None = pa.Field(nullable=True)
    plaintiff_id: str | None = pa.Field(nullable=True)
    plaintiff_id_type: str | None = pa.Field(nullable=True)
    plaintiff_name: str | None = pa.Field(nullable=True)
    defendant_id_raw: str | None = pa.Field(nullable=True)
    defendant_id: str | None = pa.Field(nullable=True)
    defendant_id_type: str | None = pa.Field(nullable=True)
    defendant_name: str | None = pa.Field(nullable=True)
    amount_cop_raw: str | None = pa.Field(nullable=True)
    amount_cop: int | None = pa.Field(nullable=True)
    origin_date_raw: str | None = pa.Field(nullable=True)
    origin_date: date | None = pa.Field(nullable=True)
    case_action_date_raw: str | None = pa.Field(nullable=True)
    case_action_date: date | None = pa.Field(nullable=True)
    case_number: str | None = pa.Field(nullable=True)
    seccional: str | None = pa.Field(nullable=True)
    department: str | None = pa.Field(nullable=True)
    city: str | None = pa.Field(nullable=True)
    judicial_district: str | None = pa.Field(nullable=True)
    source_extra: str | None = pa.Field(nullable=True)

    class Config:
        strict = True


class StagingRejectSchema(pa.DataFrameModel):
    key: str
    period: str
    sheet: str
    source_row: int | None = pa.Field(nullable=True)
    reason: str
    raw_row: str | None = pa.Field(nullable=True)

    class Config:
        strict = True


class PartySchema(pa.DataFrameModel):
    party_id: str
    document_number: str
    # Nullable per D26: document_type is sourced from RUES's own Categoria
    # field, not inferred at build-identity time -- null until a party has
    # actually been queried (see identity.apply_rues_classification).
    document_type: str | None = pa.Field(isin=["legal_entity", "natural_person"], nullable=True)
    document_type_confidence: float | None = pa.Field(ge=0, le=1, nullable=True)
    document_type_rule_id: str | None = pa.Field(nullable=True)

    class Config:
        strict = True


class CourtSchema(pa.DataFrameModel):
    court_id: str
    court_account: str
    seccional: str | None = pa.Field(nullable=True)
    department: str | None = pa.Field(nullable=True)
    city: str | None = pa.Field(nullable=True)
    judicial_district: str | None = pa.Field(nullable=True)
    row_count: int = pa.Field(ge=1)

    class Config:
        strict = True


class CourtNameSchema(pa.DataFrameModel):
    court_id: str
    court_account: str
    name: str
    first_period: str
    last_period: str
    row_count: int = pa.Field(ge=1)

    class Config:
        strict = True


class ClaimSchema(pa.DataFrameModel):
    claim_id: str
    type: str
    court_id: str | None = pa.Field(nullable=True)
    deposit_no: str
    deposit_type: str | None = pa.Field(nullable=True)
    amount_cop: int | None = pa.Field(nullable=True)
    origin_date: date | None = pa.Field(nullable=True)
    case_number: str | None = pa.Field(nullable=True)
    legal_basis: str | None = pa.Field(nullable=True)
    claim_route: str | None = pa.Field(nullable=True)
    attributes: str | None = pa.Field(nullable=True)

    class Config:
        strict = True


class ObservationSchema(pa.DataFrameModel):
    capture_id: str
    sheet: str
    source_row: int = pa.Field(ge=0)
    claim_id: str

    class Config:
        strict = True


class ClaimPartySchema(pa.DataFrameModel):
    claim_id: str
    party_id: str
    procedural_role: str = pa.Field(isin=["plaintiff", "defendant"])
    attributes: str | None = pa.Field(nullable=True)

    class Config:
        strict = True


class EnrichmentSchema(pa.DataFrameModel):
    party_id: str
    source: str
    queried_at: datetime
    result: str
    name: str | None = pa.Field(nullable=True)
    active: bool | None = pa.Field(nullable=True)
    attributes: str | None = pa.Field(nullable=True)
    status: str = pa.Field(isin=["found", "not_found", "error"])
    # D26: every RUES match is queried and enriched with no discrimination by
    # document type. `categoria` is the verbatim value RUES returned (no
    # isin restriction -- it's a fact, not this project's classification),
    # stored even when document_type below can't map it to legal_entity/
    # natural_person, so nothing RUES actually told us is ever lost.
    categoria: str | None = pa.Field(nullable=True)
    # These three carry the classification RUES's own Categoria field gives
    # us for this attempt -- null on an 'error' row,
    # since a failed attempt yields no classification signal.
    document_type: str | None = pa.Field(isin=["legal_entity", "natural_person"], nullable=True)
    document_type_confidence: float | None = pa.Field(ge=0, le=1, nullable=True)
    document_type_rule_id: str | None = pa.Field(nullable=True)


class FileSchema(pa.DataFrameModel):
    file_id: str
    source: str
    period: str
    uri: str
    content_hash: str
    detected_at: datetime

    class Config:
        strict = True


class CaptureSchema(pa.DataFrameModel):
    capture_id: str
    file_id: str
    code_version: str
    schema_version: str
    executed_at: datetime
    rows_read: int = pa.Field(ge=0)
    rows_ok: int = pa.Field(ge=0)
    rows_rejected: int = pa.Field(ge=0)
    status: str = pa.Field(isin=["ok", "reconciliation_mismatch", "read_error"])

    class Config:
        strict = True
