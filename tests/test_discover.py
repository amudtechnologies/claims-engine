from pathlib import Path

import boto3
from moto import mock_aws
from test_profiling import write_fixture

from claims_engine.discover import list_keys


@mock_aws
def test_list_keys_skips_folder_markers(tmp_path: Path) -> None:
    local_path = tmp_path / "source.xlsx"
    write_fixture(local_path, header_row=7)

    bucket = "amud-technologies"
    prefix = "raw/judicial-branch/expiring-deposits/"
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=bucket)
    client.put_object(Bucket=bucket, Key=f"{prefix}2020-1/", Body=b"")  # folder marker
    client.upload_file(str(local_path), bucket, f"{prefix}2020-1/deposits.xlsx")
    client.upload_file(str(local_path), bucket, f"{prefix}2020-2/deposits.xlsx")

    keys = list_keys(bucket, prefix)

    assert keys == [
        f"{prefix}2020-1/deposits.xlsx",
        f"{prefix}2020-2/deposits.xlsx",
    ]
