from pathlib import Path

import boto3
from moto import mock_aws
from test_normalize import write_fixture as write_normalize_fixture
from test_profiling import write_fixture
from typer.testing import CliRunner

from claims_engine.cli import app

runner = CliRunner()


@mock_aws
def test_profile_s3_prefix_processes_every_key_and_survives_a_bad_one(tmp_path: Path) -> None:
    local_path = tmp_path / "source.xlsx"
    write_fixture(local_path, header_row=7)
    corrupt_path = tmp_path / "corrupt.xlsx"
    corrupt_path.write_bytes(b"not actually an xlsx file")

    bucket = "amud-technologies"
    prefix = "raw/judicial-branch/expiring-deposits/"
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=bucket)
    client.upload_file(str(local_path), bucket, f"{prefix}2020-1/deposits.xlsx")
    client.upload_file(str(corrupt_path), bucket, f"{prefix}2020-2/deposits.xlsx")

    out = tmp_path / "matrix.csv"
    result = runner.invoke(app, ["profile-s3-prefix", bucket, prefix, "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()
    content = out.read_text()
    assert "2020-1/deposits.xlsx" in content
    assert "2020-2/deposits.xlsx" in content
    assert "<READ_ERROR>" in content


@mock_aws
def test_normalize_s3_prefix_writes_parquet_and_reconciles(tmp_path: Path) -> None:
    local_path = tmp_path / "source.xlsx"
    write_normalize_fixture(
        local_path,
        "Busqueda",
        [
            [1, "Juzgado 1", "12345", "900123456", "80123456", 1500000,
             "26/08/2016", "Bogota", "Cundinamarca", "Bogota"],
        ],
    )
    corrupt_path = tmp_path / "corrupt.xlsx"
    corrupt_path.write_bytes(b"not actually an xlsx file")

    bucket = "amud-technologies"
    prefix = "raw/judicial-branch/expiring-deposits/"
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=bucket)
    client.upload_file(str(local_path), bucket, f"{prefix}2026-1/deposits.xlsx")
    client.upload_file(str(corrupt_path), bucket, f"{prefix}2020-2/deposits.xlsx")

    result = runner.invoke(app, ["normalize-s3-prefix", bucket, prefix])

    assert result.exit_code == 0, result.output
    assert "TOTAL: read=" in result.output

    objects = client.list_objects_v2(Bucket=bucket, Prefix="staging/")["Contents"]
    keys = [o["Key"] for o in objects]
    assert any("jd_published_deposit/period=2026-1" in k for k in keys)
    assert any("jd_reject/period=2020-2" in k for k in keys)
