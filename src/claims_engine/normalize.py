"""Phase 2: normalize a raw judicial-deposit file into the staging shape from
Phase 1's data dictionary (docs/project-context.md §6) — `stg_jd_published_deposit`
at grain (capture_id, sheet, source_row), and `stg_jd_reject`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from claims_engine import capture, column_mapping, profiling
from claims_engine.column_mapping import SheetMapping
from claims_engine.contracts import StagingDepositSchema, StagingRejectSchema
from claims_engine.parsing import normalize_id, parse_currency_cop, parse_deposit_date

CANONICAL_FIELDS = [
    "deposit_no",
    "deposit_type",
    "classification",
    "court_account",
    "court_name",
    "plaintiff_id",
    "plaintiff_id_type",
    "plaintiff_name",
    "defendant_id",
    "defendant_id_type",
    "defendant_name",
    "amount_cop",
    "origin_date",
    "case_action_date",
    "case_number",
    "seccional",
    "department",
    "city",
    "judicial_district",
    "source_extra",
]

# Fields with a _raw twin because a parser actually transforms the value. Every
# other canonical field is stored as received (stringified), no separate raw column.
CURRENCY_FIELDS = {"amount_cop"}
DATE_FIELDS = {"origin_date", "case_action_date"}
ID_FIELDS = {"deposit_no", "plaintiff_id", "defendant_id"}

_PERIOD_RE = re.compile(r"/(\d{4}-\d)/")


class RowRejected(Exception):
    pass


@dataclass
class FileNormalizeResult:
    key: str
    ok_rows: list[dict] = field(default_factory=list)
    reject_rows: list[dict] = field(default_factory=list)
    rows_read: int = 0

    @property
    def rows_ok(self) -> int:
        return len(self.ok_rows)

    @property
    def rows_rejected(self) -> int:
        return len(self.reject_rows)

    def ok_frame(self) -> pl.DataFrame:
        schema = _polars_schema(StagingDepositSchema)
        df = pl.DataFrame(self.ok_rows or [], schema=schema)
        return StagingDepositSchema.validate(df)

    def reject_frame(self) -> pl.DataFrame:
        schema = _polars_schema(StagingRejectSchema)
        df = pl.DataFrame(self.reject_rows or [], schema=schema)
        return StagingRejectSchema.validate(df)


def _polars_schema(model) -> dict:
    return {name: dtype.type for name, dtype in model.to_schema().dtypes.items()}


def period_from_key(key: str) -> str:
    match = _PERIOD_RE.search(key)
    if not match:
        raise ValueError(f"Could not extract period from key: {key}")
    return match.group(1)


def capture_id_for_key(key: str) -> str:
    """Deterministic id for this run over this file (D08). Not the full `capture`
    core table yet (code_version/schema_version bookkeeping) — Phase 2 only builds
    staging; this is enough to give staging rows a stable, reprocessable grain key."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _stringify(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _parse_or_reject(raw_value: object, parser, field_name: str):
    if raw_value is None:
        return None
    parsed = parser(raw_value)
    if parsed is None:
        raise RowRejected(f"could not parse {field_name} from {raw_value!r}")
    return parsed


def _build_row(
    raw_row: dict, mapping: SheetMapping, capture_id: str, period: str, sheet: str, source_row: int
) -> dict:
    values: dict[str, object] = {}
    for source_col, canon in mapping.column_map.items():
        values[canon] = raw_row.get(source_col)

    out: dict = {
        "capture_id": capture_id,
        "period": period,
        "sheet": sheet,
        "source_row": source_row,
    }
    for canon_field in CANONICAL_FIELDS:
        raw_value = values.get(canon_field)
        if canon_field in CURRENCY_FIELDS:
            out[f"{canon_field}_raw"] = _stringify(raw_value)
            out[canon_field] = _parse_or_reject(raw_value, parse_currency_cop, canon_field)
        elif canon_field in DATE_FIELDS:
            out[f"{canon_field}_raw"] = _stringify(raw_value)
            out[canon_field] = _parse_or_reject(raw_value, parse_deposit_date, canon_field)
        elif canon_field in ID_FIELDS:
            out[f"{canon_field}_raw"] = _stringify(raw_value)
            out[canon_field] = normalize_id(raw_value)
        else:
            out[canon_field] = _stringify(raw_value)
    return out


def _reject_entry(
    key: str, period: str, sheet: str, source_row: int | None, reason: str, raw_row: dict | None
) -> dict:
    return {
        "key": key,
        "period": period,
        "sheet": sheet,
        "source_row": source_row,
        "reason": reason,
        "raw_row": json.dumps(raw_row, default=str) if raw_row is not None else None,
    }


def _stringify_datetime_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Cast every Date/Datetime column to its string form before any row-level
    Python iteration. A cell with a year outside Python's datetime range (found
    for real in 2024-2: year 56634) crashes polars' Rust-side row materialization
    with a pyo3_runtime.PanicException that no Python try/except can catch —
    confirmed by reproducing it directly. strftime runs entirely on polars'
    internal representation and never constructs a Python datetime object, so
    it's safe even for out-of-range values; parse_deposit_date already parses
    this exact "YYYY-MM-DD HH:MM:SS" shape via its ISO-date branch, and a value
    too absurd to match becomes a normal reject instead of a crash.
    """
    exprs = [
        pl.col(name).dt.strftime("%Y-%m-%d %H:%M:%S").alias(name)
        for name, dtype in df.schema.items()
        if dtype == pl.Date or isinstance(dtype, pl.Datetime)
    ]
    return df.with_columns(exprs) if exprs else df


def _normalize_sheet(
    path: Path, key: str, period: str, sheet: str, capture_id: str
) -> tuple[list[dict], list[dict], int]:
    try:
        df = profiling.read_sheet(path, sheet_name=sheet)
        df = _stringify_datetime_columns(df)
    except Exception as e:
        reason = f"sheet unreadable: {type(e).__name__}: {e}"
        return [], [_reject_entry(key, period, sheet, None, reason, None)], 1

    rows_read = df.height
    try:
        mapping = column_mapping.get_mapping(period, sheet)
    except KeyError:
        mapping = None

    if mapping is None or mapping.skip_reason:
        reason = (
            mapping.skip_reason
            if mapping
            else f"no column mapping for period={period!r} sheet={sheet!r}"
        )
        reject_rows = [
            _reject_entry(key, period, sheet, i, reason, raw_row)
            for i, raw_row in enumerate(df.iter_rows(named=True))
        ]
        return [], reject_rows, rows_read

    ok_rows, reject_rows = [], []
    for i, raw_row in enumerate(df.iter_rows(named=True)):
        try:
            ok_rows.append(_build_row(raw_row, mapping, capture_id, period, sheet, i))
        except RowRejected as e:
            reject_rows.append(_reject_entry(key, period, sheet, i, str(e), raw_row))

    assert len(ok_rows) + len(reject_rows) == rows_read, (
        f"reconciliation failed for {key} sheet={sheet}: "
        f"{len(ok_rows)} ok + {len(reject_rows)} rejected != {rows_read} read"
    )
    return ok_rows, reject_rows, rows_read


def transform_file(path: Path, key: str) -> FileNormalizeResult:
    """Radar contract step 3: normalize() in isolation. Given an already-
    captured local file and the S3 key it came from (for period, capture_id,
    and reject provenance), produce staging rows. No S3 I/O here —
    capture.fetch_to_local is the pipeline's only read from S3, so this
    stays a pure function of what's already on disk."""
    period = period_from_key(key)
    capture_id = capture_id_for_key(key)
    try:
        sheet_names = profiling.list_sheets(path)
    except Exception as e:
        reason = f"file unreadable: {type(e).__name__}: {e}"
        reject = _reject_entry(key, period, "<unknown>", None, reason, None)
        return FileNormalizeResult(key=key, reject_rows=[reject], rows_read=1)

    result = FileNormalizeResult(key=key)
    for sheet in sheet_names:
        ok_rows, reject_rows, rows_read = _normalize_sheet(path, key, period, sheet, capture_id)
        result.ok_rows.extend(ok_rows)
        result.reject_rows.extend(reject_rows)
        result.rows_read += rows_read
    return result


def normalize_file(bucket: str, key: str) -> FileNormalizeResult:
    """Convenience: capture + transform for one file. Kept for simple
    single-file callers (tests, ad hoc use); a pipeline that already has a
    fetched path (e.g. reusing capture.fetch_to_local across profile and
    normalize) should call transform_file directly instead of fetching
    twice."""
    with capture.fetch_to_local(bucket, key) as path:
        return transform_file(path, key)
