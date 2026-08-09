from pathlib import Path

import boto3
import polars as pl
from moto import mock_aws

from claims_engine.load import staging_key, write_frame_to_s3


def test_staging_key_is_hive_partitioned_by_period():
    assert (
        staging_key("staging/jd_published_deposit", "2026-1", "abc123")
        == "staging/jd_published_deposit/period=2026-1/abc123.parquet"
    )


@mock_aws
def test_write_frame_to_s3_roundtrips(tmp_path: Path):
    bucket = "amud-technologies"
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=bucket)
    df = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    key = "staging/jd_published_deposit/period=2026-1/abc123.parquet"

    write_frame_to_s3(client, df, bucket, key)

    local_path = tmp_path / "roundtrip.parquet"
    client.download_file(bucket, key, str(local_path))
    assert pl.read_parquet(local_path).equals(df)
