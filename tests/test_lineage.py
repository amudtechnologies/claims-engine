import hashlib
from datetime import UTC, datetime
from pathlib import Path

import boto3
import duckdb
from moto import mock_aws
from test_normalize import write_fixture as write_normalize_fixture
from typer.testing import CliRunner

from claims_engine.cli import app
from claims_engine.lineage import (
    SOURCE_ACTIVE_DEPOSITS,
    SOURCE_EXPIRING_DEPOSITS,
    build_captures,
    build_files,
    file_id,
    source_for_key,
)

runner = CliRunner()
BUCKET = "amud-technologies"


def _connect_with_dep_rej(dep_rows: list[dict], rej_rows: list[dict]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE dep (capture_id VARCHAR)")
    for row in dep_rows:
        con.execute("INSERT INTO dep VALUES ($capture_id)", row)
    con.execute("CREATE TABLE rej (key VARCHAR, reason VARCHAR)")
    for row in rej_rows:
        con.execute("INSERT INTO rej VALUES ($key, $reason)", row)
    return con


def test_source_for_key_distinguishes_the_two_radars_sharing_raw_judicial_branch():
    assert (
        source_for_key("raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx")
        == SOURCE_EXPIRING_DEPOSITS
    )
    assert (
        source_for_key("raw/judicial-branch/active-deposits/2026-08-30/sogamoso-familia.xlsx")
        == SOURCE_ACTIVE_DEPOSITS
    )


def test_source_for_key_raises_for_an_unrecognized_subtree():
    try:
        source_for_key("raw/some-other-source/file.xlsx")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unrecognized raw subtree")


def test_file_id_is_deterministic():
    key = "raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx"
    assert file_id(key) == file_id(key)
    assert file_id(key) != file_id(key + "x")


@mock_aws
def test_build_files_computes_real_content_hash(tmp_path: Path):
    local_path = tmp_path / "deposits.xlsx"
    local_path.write_bytes(b"some fake xlsx bytes for hashing")

    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=BUCKET)
    key = "raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx"
    client.upload_file(str(local_path), BUCKET, key)

    last_modified = datetime(2026, 1, 15, tzinfo=UTC)
    df = build_files(BUCKET, [(key, last_modified)])

    assert df.height == 1
    row = df.row(0, named=True)
    assert row["file_id"] == file_id(key)
    assert row["source"] == "judicial_deposits"
    assert row["period"] == "2026-1"
    assert row["uri"] == f"s3://{BUCKET}/{key}"
    assert row["content_hash"] == hashlib.sha256(local_path.read_bytes()).hexdigest()
    # naive on the way out -- polars/pandera store datetimes without tzinfo
    # (see lineage._FILE_SCHEMA); the instant is still the same UTC moment.
    assert row["detected_at"] == last_modified.replace(tzinfo=None)


@mock_aws
def test_build_files_tags_active_deposits_source(tmp_path: Path):
    local_path = tmp_path / "sogamoso-familia.xlsx"
    local_path.write_bytes(b"some fake xlsx bytes")

    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=BUCKET)
    key = "raw/judicial-branch/active-deposits/2026-08-30/sogamoso-familia.xlsx"
    client.upload_file(str(local_path), BUCKET, key)

    df = build_files(BUCKET, [(key, datetime(2026, 8, 30, tzinfo=UTC))])

    assert df.height == 1
    row = df.row(0, named=True)
    assert row["source"] == SOURCE_ACTIVE_DEPOSITS
    assert row["period"] == "2026-08-30"


def test_build_captures_counts_ok_and_rejected_rows():
    key = "raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx"
    cid = file_id(key)
    con = _connect_with_dep_rej(
        dep_rows=[{"capture_id": cid}, {"capture_id": cid}],
        rej_rows=[{"key": key, "reason": "could not parse amount_cop from 'abc'"}],
    )

    result = build_captures(con, [key], code_version="1.0.0", schema_version="1")

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["capture_id"] == cid
    assert row["file_id"] == cid
    assert row["rows_ok"] == 2
    assert row["rows_rejected"] == 1
    assert row["rows_read"] == 3
    assert row["status"] == "ok"
    assert row["code_version"] == "1.0.0"
    assert row["schema_version"] == "1"


def test_build_captures_marks_read_error_status():
    key = "raw/judicial-branch/expiring-deposits/2020-2/deposits.xlsx"
    con = _connect_with_dep_rej(
        dep_rows=[],
        rej_rows=[{"key": key, "reason": "file unreadable: BadZipFile: not a zip file"}],
    )

    result = build_captures(con, [key], code_version="1.0.0", schema_version="1")

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["status"] == "read_error"
    assert row["rows_ok"] == 0
    assert row["rows_rejected"] == 1


def test_build_captures_handles_key_with_no_rows_at_all():
    key = "raw/judicial-branch/expiring-deposits/2099-1/deposits.xlsx"
    con = _connect_with_dep_rej(dep_rows=[], rej_rows=[])

    result = build_captures(con, [key], code_version="1.0.0", schema_version="1")

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["rows_ok"] == 0
    assert row["rows_rejected"] == 0
    assert row["rows_read"] == 0
    assert row["status"] == "ok"


@mock_aws
def test_build_lineage_cli_writes_file_and_capture_parquet(tmp_path: Path):
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

    prefix = "raw/judicial-branch/expiring-deposits/"
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=BUCKET)
    client.upload_file(str(local_path), BUCKET, f"{prefix}2026-1/deposits.xlsx")
    client.upload_file(str(corrupt_path), BUCKET, f"{prefix}2020-2/deposits.xlsx")

    normalize_result = runner.invoke(app, ["normalize-s3-prefix", BUCKET, prefix])
    assert normalize_result.exit_code == 0, normalize_result.output

    result = runner.invoke(app, ["build-lineage", BUCKET, "--raw-prefix", prefix])

    assert result.exit_code == 0, result.output
    assert "files: 2" in result.output
    assert "captures: 2" in result.output

    objects = client.list_objects_v2(Bucket=BUCKET, Prefix="core/")["Contents"]
    keys = {o["Key"] for o in objects}
    assert "core/file/current.parquet" in keys
    assert "core/capture/current.parquet" in keys
