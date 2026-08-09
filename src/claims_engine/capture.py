"""Radar contract step 2: capture() — fetch to a local copy, immutable
source untouched.

This is the only place the pipeline reads bytes from `raw/`. Profiling and
normalize both fetch through here rather than each holding their own
download logic, so there is exactly one code path to trust for "did we read
the real object" and no second permanent local copy of raw/ is ever created.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import boto3


@contextmanager
def fetch_to_local(bucket: str, key: str) -> Iterator[Path]:
    """Download one object from S3 to a local temp file, yield its path, and
    discard the copy on exit."""
    client = boto3.client("s3")
    with tempfile.NamedTemporaryFile(suffix=Path(key).suffix) as tmp:
        client.download_fileobj(bucket, key, tmp)
        tmp.flush()
        yield Path(tmp.name)
