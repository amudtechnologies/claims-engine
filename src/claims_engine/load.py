"""Writes staging output to its Hive-partitioned home on S3."""

from __future__ import annotations

import tempfile

import polars as pl


def staging_key(prefix: str, period: str, capture_id: str) -> str:
    return f"{prefix}/period={period}/{capture_id}.parquet"


def core_key(table: str, filename: str = "current.parquet") -> str:
    """Core tables are a single rebuilt-in-full snapshot per table (D07), not
    period-partitioned like staging."""
    return f"core/{table}/{filename}"


def enrichment_key(source: str, batch_id: str) -> str:
    """Enrichment is append-only and dated (D20) — every batch is its own
    file under core/enrichment/, never overwritten, unlike the rebuilt-in-
    full core tables `core_key` targets."""
    return f"core/enrichment/source={source}/{batch_id}.parquet"


def write_frame_to_s3(client, df: pl.DataFrame, bucket: str, key: str) -> None:
    """Write via a local temp file + boto3 upload, not polars' native cloud writer
    — keeps one consistent credential path (boto3 + AWS_PROFILE) everywhere in this
    codebase, rather than a second, untested S3 auth mechanism."""
    with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
        df.write_parquet(tmp.name)
        client.upload_file(tmp.name, bucket, key)
