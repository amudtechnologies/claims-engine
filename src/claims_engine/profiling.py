"""Phase 0: schema-drift profiling over raw judicial-deposit publications in S3.

Reads go through `fastexcel` directly rather than `pl.read_excel`: polars'
wrapper silently downcasts any "integral-looking" float column to Int64 with
no magnitude check, which crashes on real data (a corrupted deposit number
like 7.6e22 is integral but far outside Int64 range). `fastexcel` has no such
step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fastexcel
import polars as pl

from claims_engine import capture

MAX_HEADER_SCAN_ROWS = 25


def list_sheets(path: Path) -> list[str]:
    return fastexcel.read_excel(path).sheet_names


def detect_header_row(path: Path, sheet_name: str) -> int:
    """Return the 0-indexed row containing column headers.

    Heuristic: try each candidate row as the header and count how many
    columns get a real name instead of a synthetic `__UNNAMED__*` one. Title
    blocks above the header populate at most a cell or two per row; the
    header row names every column.
    """
    reader = fastexcel.read_excel(path)
    best_row, best_score = 0, -1
    for row in range(MAX_HEADER_SCAN_ROWS):
        sheet = reader.load_sheet(sheet_name, header_row=row, n_rows=0)
        columns = sheet.to_polars().columns
        score = sum(1 for c in columns if not c.startswith("__UNNAMED__"))
        if score > best_score:
            best_row, best_score = row, score
    return best_row


def read_sheet(path: Path, sheet_name: str) -> pl.DataFrame:
    header_row = detect_header_row(path, sheet_name=sheet_name)
    reader = fastexcel.read_excel(path)
    return reader.load_sheet(sheet_name, header_row=header_row).to_polars()


@dataclass(frozen=True)
class ColumnProfile:
    file: str
    sheet: str
    column: str
    position: int
    dtype: str
    null_rate: float
    distinct_count: int


def profile_sheet(path: Path, sheet_name: str, file_label: str) -> list[ColumnProfile]:
    df = read_sheet(path, sheet_name=sheet_name)
    rows = df.height
    profiles = []
    for position, column in enumerate(df.columns):
        series = df[column]
        null_rate = series.null_count() / rows if rows else 0.0
        profiles.append(
            ColumnProfile(
                file=file_label,
                sheet=sheet_name,
                column=column,
                position=position,
                dtype=str(series.dtype),
                null_rate=round(null_rate, 4),
                distinct_count=series.n_unique(),
            )
        )
    return profiles


def profile_file(path: Path, file_label: str) -> list[ColumnProfile]:
    """Profile every sheet in the workbook.

    The sheet carrying the real per-deposit rows is not always the first
    one: some publications split "unclaimed" vs "special condition"
    deposits across two large sheets, or lead with a small summary sheet
    before the real detail sheet. A sheet that fails to read (corrupt data,
    unexpected layout) is recorded as a `<READ_ERROR>` row rather than
    aborting the rest of the file — the same no-silent-loss spirit as the
    project's rejects tables, applied to profiling.
    """
    try:
        sheet_names = list_sheets(path)
    except Exception as e:
        return [read_error_profile(file_label, "<unknown>", e)]

    profiles = []
    for sheet_name in sheet_names:
        try:
            profiles.extend(profile_sheet(path, sheet_name, file_label))
        except Exception as e:
            profiles.append(read_error_profile(file_label, sheet_name, e))
    return profiles


def read_error_profile(file_label: str, sheet_name: str, error: Exception) -> ColumnProfile:
    return ColumnProfile(
        file=file_label,
        sheet=sheet_name,
        column="<READ_ERROR>",
        position=-1,
        dtype=f"{type(error).__name__}: {error}",
        null_rate=0.0,
        distinct_count=0,
    )


def profile_s3_key(bucket: str, key: str) -> list[ColumnProfile]:
    """Capture one raw object from S3 by key, then profile every sheet in
    it. Convenience combining capture.fetch_to_local + profile_file for
    single-file callers; a pipeline that already has a fetched path should
    call profile_file directly instead of fetching twice."""
    with capture.fetch_to_local(bucket, key) as path:
        return profile_file(path, file_label=key)


def profiles_to_frame(profiles: list[ColumnProfile]) -> pl.DataFrame:
    return pl.DataFrame([p.__dict__ for p in profiles])
