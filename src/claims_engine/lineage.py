"""Builds `core.file` and `core.capture` -- the lineage tables the documented
data model always described (project-context.md §6) but Phase 2 never
materialized; only a deterministic `capture_id` hash existed, with no backing
row anywhere (`normalize.capture_id_for_key`'s own docstring says so).

Full rebuilt-in-place snapshots (D07), same pattern as party/court/claim, not
a historical run-log: one row per file/capture reflecting the most recent
build, not every past reprocess. Closes two gaps at once: a proper lineage
path from observation back to period/URI without going through staging by
hand, and a persisted home for the per-capture health metrics D10 calls for
(today they only ever reach stdout during normalize-s3-prefix and vanish).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import duckdb
import polars as pl

from claims_engine import capture as capture_module
from claims_engine.normalize import period_from_key

# Two radars share this one raw/judicial-branch/ tree today (see
# docs/project-context.md's active-deposits design): the semiannual
# CSJ-published "eviction notice" and the irregular, per-despacho
# active-deposits extracts. `file.source` is what lets the web layer tell
# them apart -- e.g. never looking up a `ClaimWindow` for an active-deposits
# claim, since it was never part of a 20-business-day-countdown publication
# in the first place.
SOURCE_EXPIRING_DEPOSITS = "judicial_deposits"
SOURCE_ACTIVE_DEPOSITS = "judicial_deposits_active"
BACKFILL_CODE_VERSION = "backfill"


def source_for_key(key: str) -> str:
    """Classifies a raw key by which raw/ subtree it lives under. A new
    radar sharing this raw/judicial-branch/ tree adds one more branch here,
    same as column_mapping.py grows by one more pinned entry per file --
    this is the adapter, core stays untouched."""
    if "/active-deposits/" in key:
        return SOURCE_ACTIVE_DEPOSITS
    if "/expiring-deposits/" in key:
        return SOURCE_EXPIRING_DEPOSITS
    raise ValueError(f"Cannot determine source for key: {key!r}")

# Bare pl.Datetime (no explicit time_zone) silently strips tzinfo from the
# tz-aware datetimes fed in below (S3's LastModified, datetime.now(UTC)) --
# matches pandera's plain `datetime` type hint, which expects naive Datetime
# and errors on a tz-aware one. Same pattern enrichment.py's own
# _ENRICHMENT_SCHEMA already relies on; letting polars *infer* the schema
# instead preserves the tz and fails EnrichmentSchema/FileSchema/
# CaptureSchema validation later.
_FILE_SCHEMA = {
    "file_id": pl.Utf8,
    "source": pl.Utf8,
    "period": pl.Utf8,
    "uri": pl.Utf8,
    "content_hash": pl.Utf8,
    "detected_at": pl.Datetime,
}

_CAPTURE_SCHEMA = {
    "capture_id": pl.Utf8,
    "file_id": pl.Utf8,
    "code_version": pl.Utf8,
    "schema_version": pl.Utf8,
    "executed_at": pl.Datetime,
    "rows_read": pl.Int64,
    "rows_ok": pl.Int64,
    "rows_rejected": pl.Int64,
    "status": pl.Utf8,
}


def file_id(key: str) -> str:
    """Deterministic id for the raw object at `key` (D08) -- deliberately
    the same value `normalize.capture_id_for_key` already computes. `file`
    and `capture` are 1:1 today (this pipeline never keeps two capture rows
    for one file under different code versions), so they share one
    identifier rather than inventing a second, redundant id scheme."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def build_files(bucket: str, keys_with_last_modified: list[tuple[str, datetime]]) -> pl.DataFrame:
    """One row per raw object. `content_hash` needs the actual bytes --
    fetched via `capture.fetch_to_local`, the pipeline's one S3-read path,
    same as build-identity and profile-s3-prefix already do."""
    rows = []
    for key, last_modified in keys_with_last_modified:
        with capture_module.fetch_to_local(bucket, key) as path:
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(
            {
                "file_id": file_id(key),
                "source": source_for_key(key),
                "period": period_from_key(key),
                "uri": f"s3://{bucket}/{key}",
                "content_hash": content_hash,
                "detected_at": last_modified,
            }
        )
    return pl.DataFrame(rows, schema=_FILE_SCHEMA)


def build_captures(
    con: duckdb.DuckDBPyConnection,
    keys: list[str],
    code_version: str,
    schema_version: str,
) -> pl.DataFrame:
    """One row per raw key in `keys`, derived from staging/reject data
    already on S3 -- views `dep` (stg_jd_published_deposit) and `rej`
    (stg_jd_reject) must already be registered by the caller (see cli.py's
    build-lineage command).

    rows_ok/rows_rejected are real row counts per file; rows_read is their
    sum, not an independently-read number. That's not a shortcut: `normalize.
    py`'s own per-sheet assert (`len(ok_rows) + len(reject_rows) ==
    rows_read`) already guarantees anything that made it to S3 satisfies the
    invariant, so a genuine 'reconciliation_mismatch' can only ever be
    observed live, from an in-memory FileNormalizeResult -- never
    reconstructed after the fact. This function can only produce 'ok' or
    'read_error' (a whole file/sheet that failed to open, distinct from a
    normal per-row rejection); 'reconciliation_mismatch' stays a valid
    CaptureSchema value for a future live-wired caller, just not this one.
    """
    executed_at = datetime.now(UTC)

    ok_counts = dict(
        con.execute("SELECT capture_id, count(*) FROM dep GROUP BY capture_id").fetchall()
    )
    reject_counts = dict(con.execute("SELECT key, count(*) FROM rej GROUP BY key").fetchall())
    read_error_keys = {
        row[0]
        for row in con.execute(
            "SELECT DISTINCT key FROM rej "
            "WHERE reason LIKE 'file unreadable%' OR reason LIKE 'sheet unreadable%'"
        ).fetchall()
    }

    rows = []
    for key in keys:
        cid = file_id(key)
        rows_ok = ok_counts.get(cid, 0)
        rows_rejected = reject_counts.get(key, 0)
        rows.append(
            {
                "capture_id": cid,
                "file_id": cid,
                "code_version": code_version,
                "schema_version": schema_version,
                "executed_at": executed_at,
                "rows_read": rows_ok + rows_rejected,
                "rows_ok": rows_ok,
                "rows_rejected": rows_rejected,
                "status": "read_error" if key in read_error_keys else "ok",
            }
        )
    return pl.DataFrame(rows, schema=_CAPTURE_SCHEMA)
