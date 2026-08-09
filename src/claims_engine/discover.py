"""Radar contract step 1: discover() — what is new at the source."""

from __future__ import annotations

from datetime import datetime

import boto3


def list_keys(bucket: str, prefix: str) -> list[str]:
    """List real object keys under a prefix, skipping S3's zero-byte
    folder-marker objects (e.g. `.../2017-1/` itself, alongside the file
    inside it)."""
    client = boto3.client("s3")
    paginator = client.get_paginator("list_objects_v2")
    return [
        obj["Key"]
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
        if not obj["Key"].endswith("/")
    ]


def list_keys_with_last_modified(bucket: str, prefix: str) -> list[tuple[str, datetime]]:
    """Same listing as `list_keys`, plus each object's S3 `LastModified` --
    used by `lineage.py` for `file.detected_at`. A separate function rather
    than changing `list_keys`'s return shape, since every other caller
    (profiling, normalize-s3-prefix, build-identity, build-lifecycle) expects
    a plain list of keys."""
    client = boto3.client("s3")
    paginator = client.get_paginator("list_objects_v2")
    return [
        (obj["Key"], obj["LastModified"])
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
        if not obj["Key"].endswith("/")
    ]
