"""Radar contract step 4: health() — for now, just the reconciliation
invariant (D09: rows_ok + rows_rejected == rows_read) at the file level.
`normalize.transform_file` already asserts this per sheet; this is the
orchestration-facing check the pipeline reports on and keeps going, rather
than a hard crash. Freshness and volume-delta checks belong here too once
there's a second capture of the same source to compare against.
"""

from __future__ import annotations

from claims_engine.normalize import FileNormalizeResult


def reconciliation_error(result: FileNormalizeResult) -> str | None:
    """None if the file reconciles; otherwise a human-readable mismatch."""
    if result.rows_ok + result.rows_rejected == result.rows_read:
        return None
    return (
        f"{result.rows_ok} ok + {result.rows_rejected} rejected != "
        f"{result.rows_read} read"
    )
