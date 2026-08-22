"""Syncs the `core/` tables the NIT search needs from S3 to a local Parquet
cache, and resolves paths into that cache for `party_search` to query.

Decoupled from the request path on purpose: a live point query against S3
takes 15-50s (see `settings.CORE_CACHE_DIR`), so the sync runs on its own
schedule (`python manage.py sync_core_cache`), not per search.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import boto3
from botocore.config import Config
from django.conf import settings

from claims_engine.load import core_key

# The container entrypoint runs a blocking sync before starting gunicorn (so
# the app never serves "not synced" on a cold start) — bounded timeouts keep
# that startup delay predictable even if S3 is unreachable (e.g. a container
# network misconfiguration), instead of botocore's default ~60s connect/read
# timeouts times several retries blocking gunicorn for minutes and failing
# every deploy's health check.
_CLIENT_CONFIG = Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 3})

# Tables read whole; each is small enough (<100MB) to keep a full local copy.
CORE_TABLES = [
    "party",
    "claim",
    "claim_party",
    "observation",
    "file",
    "capture",
    "court",
    "court_name",
]

# Dated, append-only batches (D20) — every object under the prefix is part
# of the current picture, not just the latest one.
ENRICHMENT_PREFIX = "core/enrichment/source=RUES/"


def cache_dir() -> Path:
    return Path(settings.CORE_CACHE_DIR)


def table_path(table: str) -> Path:
    return cache_dir() / f"{table}.parquet"


def enrichment_glob() -> str:
    return str(cache_dir() / "enrichment" / "*.parquet")


def sync(bucket: str | None = None) -> None:
    """Downloads every table in `CORE_TABLES` plus all RUES enrichment
    batches to `settings.CORE_CACHE_DIR`, replacing whatever was there.

    Downloads to a temp file per object and moves it into place last, so a
    search running mid-sync never sees a half-written Parquet file.
    """
    bucket = bucket or settings.CLAIMS_ENGINE_BUCKET
    client = boto3.client("s3", config=_CLIENT_CONFIG)
    target_dir = cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    enrichment_dir = target_dir / "enrichment"
    enrichment_dir.mkdir(exist_ok=True)

    for table in CORE_TABLES:
        _download_to(client, bucket, core_key(table), table_path(table))

    paginator = client.get_paginator("list_objects_v2")
    seen_files = set()
    for page in paginator.paginate(Bucket=bucket, Prefix=ENRICHMENT_PREFIX):
        for obj in page.get("Contents", []):
            filename = obj["Key"].rsplit("/", 1)[-1]
            seen_files.add(filename)
            _download_to(client, bucket, obj["Key"], enrichment_dir / filename)

    # Drop any locally cached enrichment batch that no longer exists upstream.
    for existing in enrichment_dir.glob("*.parquet"):
        if existing.name not in seen_files:
            existing.unlink()


def _download_to(client, bucket: str, key: str, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        client.download_file(bucket, key, str(tmp_path))
        shutil.move(str(tmp_path), destination)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def is_synced() -> bool:
    return all(table_path(table).exists() for table in CORE_TABLES)
