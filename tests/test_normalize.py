from pathlib import Path

import boto3
import polars as pl
import xlsxwriter
from moto import mock_aws

from claims_engine.normalize import (
    _stringify_datetime_columns,
    capture_id_for_key,
    normalize_file,
    period_from_key,
)

BUCKET = "amud-technologies"

# Matches the real, pinned 2026-1 / "Busqueda" mapping in column_mapping.py exactly,
# so normalize_file resolves it through the real config rather than a fake one.
HEADERS = [
    "No. Depósito",
    "Despacho Judicial",
    "Cuenta Judicial",
    "Identificación Demandante",
    "Identificación Demandado",
    "Valor",
    "Fecha Constitución",
    "Seccional",
    "Departamento",
    "Ciudad",
]


def write_fixture(path: Path, sheet_name: str, rows: list[list], header_row: int = 3) -> None:
    workbook = xlsxwriter.Workbook(str(path))
    sheet = workbook.add_worksheet(sheet_name)
    sheet.write(0, 0, "CONSEJO SUPERIOR DE LA JUDICATURA")
    for col, header in enumerate(HEADERS):
        sheet.write(header_row, col, header)
    for row_offset, row in enumerate(rows):
        for col, value in enumerate(row):
            if value is not None:
                sheet.write(header_row + 1 + row_offset, col, value)
    workbook.close()


def upload(client, local_path: Path, key: str) -> None:
    client.create_bucket(Bucket=BUCKET)
    client.upload_file(str(local_path), BUCKET, key)


def test_period_from_key():
    key = "raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx"
    assert period_from_key(key) == "2026-1"


def test_capture_id_is_deterministic():
    key = "raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx"
    assert capture_id_for_key(key) == capture_id_for_key(key)
    assert capture_id_for_key(key) != capture_id_for_key(key + "x")


@mock_aws
def test_normalize_file_happy_path(tmp_path: Path):
    rows = [
        [1, "Juzgado 1 Civil", "12345", "900123456", "80123456", "135.000,00",
         "26/08/2016", "Bogota", "Cundinamarca", "Bogota"],
        [2, "Juzgado 2 Civil", "12346", "900654321", "Desconocido", 2500000,
         "2020-02-01 00:00:00", "Bogota", "Cundinamarca", "Bogota"],
    ]
    local_path = tmp_path / "source.xlsx"
    write_fixture(local_path, "Busqueda", rows)
    key = "raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx"
    client = boto3.client("s3", region_name="us-east-1")
    upload(client, local_path, key)

    result = normalize_file(BUCKET, key)

    assert result.rows_read == 2
    assert result.rows_ok == 2
    assert result.rows_rejected == 0
    first = result.ok_rows[0]
    assert first["amount_cop"] == 135000
    assert first["origin_date"].isoformat() == "2016-08-26"
    assert first["plaintiff_id"] == "900123456"
    second = result.ok_rows[1]
    assert second["defendant_id"] is None  # "Desconocido" -> unknown, not a reject
    assert second["defendant_id_raw"] == "Desconocido"

    # Contract validation (pandera): must pass for real rows, and an empty reject
    # frame (this file has none) must validate too, not blow up on empty input.
    ok_frame = result.ok_frame()
    assert ok_frame.height == 2
    reject_frame = result.reject_frame()
    assert reject_frame.height == 0


@mock_aws
def test_normalize_file_rejects_unparseable_currency(tmp_path: Path):
    rows = [
        [1, "Juzgado 1 Civil", "12345", "900123456", "80123456", "not a number",
         "26/08/2016", "Bogota", "Cundinamarca", "Bogota"],
        [2, "Juzgado 2 Civil", "12346", "900654321", "80654321", 2500000,
         "2020-02-01 00:00:00", "Bogota", "Cundinamarca", "Bogota"],
    ]
    local_path = tmp_path / "source.xlsx"
    write_fixture(local_path, "Busqueda", rows)
    key = "raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx"
    client = boto3.client("s3", region_name="us-east-1")
    upload(client, local_path, key)

    result = normalize_file(BUCKET, key)

    assert result.rows_read == 2
    assert result.rows_ok == 1
    assert result.rows_rejected == 1
    assert "amount_cop" in result.reject_rows[0]["reason"]
    assert result.rows_ok + result.rows_rejected == result.rows_read

    assert result.ok_frame().height == 1
    assert result.reject_frame().height == 1


@mock_aws
def test_normalize_file_skip_reason_sheet_rejects_wholesale(tmp_path: Path):
    rows = [[1, "Bogota", 5]]
    local_path = tmp_path / "source.xlsx"
    write_fixture(local_path, "Hoja1", rows)
    key = "raw/judicial-branch/expiring-deposits/2018-2/summary.xlsx"
    client = boto3.client("s3", region_name="us-east-1")
    upload(client, local_path, key)

    result = normalize_file(BUCKET, key)

    assert result.rows_ok == 0
    assert result.rows_rejected == result.rows_read == 1
    assert "Aggregate summary" in result.reject_rows[0]["reason"]
    assert result.ok_frame().height == 0
    assert result.reject_frame().height == 1


@mock_aws
def test_normalize_file_unknown_sheet_rejects_wholesale(tmp_path: Path):
    rows = [[1, "Juzgado 1 Civil", "12345", "900123456", "80123456", 1500000,
             "26/08/2016", "Bogota", "Cundinamarca", "Bogota"]]
    local_path = tmp_path / "source.xlsx"
    write_fixture(local_path, "SomeUnknownSheet", rows)
    key = "raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx"
    client = boto3.client("s3", region_name="us-east-1")
    upload(client, local_path, key)

    result = normalize_file(BUCKET, key)

    assert result.rows_ok == 0
    assert result.rows_rejected == result.rows_read == 1
    assert "no column mapping" in result.reject_rows[0]["reason"]


def test_stringify_datetime_columns_survives_out_of_range_year():
    """Reproduces the real 2024-2 crash directly: a Datetime cell whose internal
    value decodes to a year beyond Python's datetime range used to crash polars'
    Rust-side row materialization with an unrecoverable panic. Cast via a huge
    microsecond value the same way the manual repro did, since xlsxwriter can't
    write an out-of-range datetime itself (it only accepts real Python objects,
    which are bounded to year 9999)."""
    huge_and_valid = pl.DataFrame({"us": [1 << 62, 1_718_000_000_000_000]}).select(
        pl.col("us").cast(pl.Datetime("us")).alias("d")
    )

    sanitized = _stringify_datetime_columns(huge_and_valid)

    assert sanitized.schema["d"] == pl.String
    rows = sanitized.rows()  # must not raise
    assert rows[0][0] is not None  # absurd year, but a string, not a crash
    assert rows[1][0] == "2024-06-10 06:13:20"
