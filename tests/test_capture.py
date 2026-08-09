from pathlib import Path

import boto3
from moto import mock_aws
from test_profiling import write_fixture

from claims_engine.capture import fetch_to_local


@mock_aws
def test_fetch_to_local_downloads_and_cleans_up(tmp_path: Path) -> None:
    local_path = tmp_path / "source.xlsx"
    write_fixture(local_path, header_row=7)

    bucket = "amud-technologies"
    key = "raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx"
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=bucket)
    client.upload_file(str(local_path), bucket, key)

    with fetch_to_local(bucket, key) as fetched_path:
        assert fetched_path.exists()
        assert fetched_path.read_bytes() == local_path.read_bytes()

    assert not fetched_path.exists()  # temp file discarded on exit
