from pathlib import Path

import boto3
import xlsxwriter
from moto import mock_aws

from claims_engine.profiling import (
    detect_header_row,
    profile_file,
    profile_s3_key,
    read_sheet,
)

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

ROWS = [
    [1, "Juzgado 1 Civil", "12345", "900123456", "80123456", 1500000,
     "2020-01-01", "Bogota", "Cundinamarca", "Bogota"],
    [2, "Juzgado 2 Civil", "12346", "900654321", "80654321", 2500000,
     "2020-02-01", "Bogota", "Cundinamarca", "Bogota"],
    [3, "Juzgado 3 Civil", "12347", None, "80777777", 3200000,
     "2020-03-01", "Medellin", "Antioquia", "Medellin"],
]


def write_fixture(path: Path, header_row: int, sheet_name: str = "Deposits") -> None:
    workbook = xlsxwriter.Workbook(str(path))
    sheet = workbook.add_worksheet(sheet_name)
    sheet.write(0, 0, "CONSEJO SUPERIOR DE LA JUDICATURA")
    sheet.write(2, 0, "Depositos proximos a prescribir")
    for col, header in enumerate(HEADERS):
        sheet.write(header_row, col, header)
    for row_offset, row in enumerate(ROWS):
        for col, value in enumerate(row):
            if value is not None:
                sheet.write(header_row + 1 + row_offset, col, value)
    workbook.close()


def test_detect_header_row_skips_title_block(tmp_path: Path) -> None:
    path = tmp_path / "2026-1.xlsx"
    write_fixture(path, header_row=7)

    assert detect_header_row(path, sheet_name="Deposits") == 7


def test_read_sheet_recovers_declared_headers(tmp_path: Path) -> None:
    path = tmp_path / "2026-1.xlsx"
    write_fixture(path, header_row=7)

    df = read_sheet(path, sheet_name="Deposits")

    assert df.columns == HEADERS
    assert df.height == len(ROWS)
    assert df["No. Depósito"].to_list() == [1, 2, 3]


def test_profile_file_covers_every_sheet(tmp_path: Path) -> None:
    """A workbook can carry the real data on a sheet other than the first
    (e.g. a small summary sheet ahead of the detail sheet) — profiling must
    not silently skip any sheet."""
    path = tmp_path / "multi_sheet.xlsx"
    workbook = xlsxwriter.Workbook(str(path))
    resumen = workbook.add_worksheet("Resumen")
    resumen.write(0, 0, "Ciudad")
    resumen.write(0, 1, "Total")
    resumen.write(1, 0, "Bogota")
    resumen.write(1, 1, 5)
    detalle = workbook.add_worksheet("Detalle")
    detalle.write(2, 0, "Depositos proximos a prescribir")
    for col, header in enumerate(HEADERS):
        detalle.write(7, col, header)
    for row_offset, row in enumerate(ROWS):
        for col, value in enumerate(row):
            if value is not None:
                detalle.write(7 + 1 + row_offset, col, value)
    workbook.close()

    profiles = profile_file(path, file_label="multi_sheet.xlsx")

    assert {p.sheet for p in profiles} == {"Resumen", "Detalle"}
    detalle_columns = {p.column for p in profiles if p.sheet == "Detalle"}
    assert detalle_columns == set(HEADERS)
    resumen_columns = {p.column for p in profiles if p.sheet == "Resumen"}
    assert resumen_columns == {"Ciudad", "Total"}


def test_profile_file_records_read_error_without_raising(tmp_path: Path) -> None:
    """A sheet that fails to read must not take down the whole file's
    profile — record the failure and keep going, same no-silent-loss spirit
    as the rejects tables in the real pipeline."""
    path = tmp_path / "corrupt.xlsx"
    path.write_bytes(b"not actually an xlsx file")

    profiles = profile_file(path, file_label="corrupt.xlsx")

    assert len(profiles) == 1
    assert profiles[0].column == "<READ_ERROR>"
    assert profiles[0].file == "corrupt.xlsx"


@mock_aws
def test_profile_s3_key_fetches_and_labels_by_key(tmp_path: Path) -> None:
    local_path = tmp_path / "source.xlsx"
    write_fixture(local_path, header_row=7)

    bucket = "amud-technologies"
    key = "raw/judicial-branch/expiring-deposits/2026-1/deposits.xlsx"
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=bucket)
    client.upload_file(str(local_path), bucket, key)

    profiles = profile_s3_key(bucket, key)

    assert {p.file for p in profiles} == {key}
    assert {p.sheet for p in profiles} == {"Deposits"}
    assert {p.column for p in profiles} == set(HEADERS)
    valor = next(p for p in profiles if p.column == "Valor")
    assert valor.distinct_count == 3
