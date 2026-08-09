"""Pinned column-name -> canonical-field mapping, one entry per (period, sheet).

Generated once by generate_column_mapping.py from docs/phase0_schema_matrix.csv,
then hand-reviewed. The pipeline reads this static list at runtime and never
re-classifies a column name — reprocessing determinism (D07) requires that a
later change to the classifier logic can never silently reinterpret a historical
file differently."""

from pydantic import BaseModel


class SheetMapping(BaseModel):
    period: str
    sheet: str
    column_map: dict[str, str]
    skip_reason: str | None = None


SHEET_MAPPINGS: list[SheetMapping] = [
    SheetMapping(
        period='2017-1',
        sheet='D J EN CONDICION ESPECIAL',
        column_map={
            'NÙMERODEDEPÒSITOJUDICIALENCONDICIÒNESPECIAL': 'deposit_no',
            'FECHA DE  CONSTITUCION DD/MM/AAAA ': 'origin_date',
            'VALOR': 'amount_cop',
            'NUMERO DE RADICADO DEL PROCESO (23 DIGITOS)': 'case_number',
            'ID DEMANTANTE': 'plaintiff_id',
            'NOMBRE DEMANTANDE': 'plaintiff_name',
            'ID DEMANDADO': 'defendant_id',
            'NOMBRE DEMANDADO': 'defendant_name',
            'NOMBRE DESPACHO': 'court_name',
            'FECHA DE LA ACTUACIÓN QUE DIO FIN AL PROCESO  DD/MM/AAAA': 'case_action_date',
            '__UNNAMED__10': 'source_extra',
        },
    ),
    SheetMapping(
        period='2017-1',
        sheet='D J NO RECLAMADOS',
        column_map={
            'NÙMERO DE DEPÒSITO JUDICIAL NO RECLAMADOS': 'deposit_no',
            'FECHA DE  CONSTITUCION DD/MM/AAAA ': 'origin_date',
            'VALOR': 'amount_cop',
            'NUMERO DE RADICADO DEL PROCESO (23 DIGITOS)': 'case_number',
            'ID DEMANTANTE': 'plaintiff_id',
            'NOMBRE DEMANTANDE': 'plaintiff_name',
            'ID DEMANDADO': 'defendant_id',
            'NOMBRE DEMANDADO': 'defendant_name',
            'NOMBRE DESPACHO': 'court_name',
            'FECHA DE LA ACTUACIÓN QUE DIO FIN AL PROCESO  DD/MM/AAAA': 'case_action_date',
            '__UNNAMED__10': 'source_extra',
            '__UNNAMED__11': 'source_extra',
        },
    ),
    SheetMapping(
        period='2018-1',
        sheet='Consolidado Publicar',
        column_map={
            'No. DEPÓSITO': 'deposit_no',
            'NOMBRE JUZGADO': 'court_name',
            'No. IDENTIFICACIÓN DEMANDANTE': 'plaintiff_id',
            'No. IDENTIFICACIÓN DEMANDADO': 'defendant_id',
            'VALOR DEPOSITO': 'amount_cop',
            'FECHA DE EMISIÓN': 'origin_date',
            'DIRECCIÓN SECCIONAL': 'seccional',
            'DEPARTAMENTO': 'department',
            'MUNICIPIO': 'city',
        },
    ),
    SheetMapping(
        period='2018-2',
        sheet='Hoja1',
        skip_reason=(
            'Aggregate summary (count + total value per city), not per-deposit rows '
            "— real detail is in the 'Publicar' sheet of this file. "
        ),
        column_map={
        },
    ),
    SheetMapping(
        period='2018-2',
        sheet='Publicar',
        column_map={
            'No. DEPÓSITO': 'deposit_no',
            'NOMBRE JUZGADO': 'court_name',
            'No. IDENTIFICACIÓN DEMANDANTE': 'plaintiff_id',
            'No. IDENTIFICACIÓN DEMANDADO': 'defendant_id',
            'VALOR DEPOSITO': 'amount_cop',
            'FECHA DE EMISIÓN': 'origin_date',
            'DIRECCIÓN SECCIONAL': 'seccional',
            'DEPARTAMENTO': 'department',
            'MUNICIPIO': 'city',
            '__UNNAMED__9': 'source_extra',
        },
    ),
    SheetMapping(
        period='2019-1',
        sheet='Listado Publicación',
        column_map={
            'TIPO DEPÓSITO ': 'deposit_type',
            'No. DEPÓSITO': 'deposit_no',
            'CUENTA JUDICIAL': 'court_account',
            'NOMBRE JUZGADO': 'court_name',
            'No. IDENTIFICACIÓN DEMANDANTE': 'plaintiff_id',
            'No. IDENTIFICACIÓN DEMANDADO': 'defendant_id',
            'VALOR DEPOSITO': 'amount_cop',
            'FECHA DE EMISIÓN': 'origin_date',
            'DIRECCIÓN SECCIONAL': 'seccional',
            'DEPARTAMENTO': 'department',
            'MUNICIPIO': 'city',
        },
    ),
    SheetMapping(
        period='2020-1',
        sheet='Consolidado',
        column_map={
            'Nro. Depósito Judicial': 'deposit_no',
            'Tipo Depósito Judicial': 'deposit_type',
            'No. cuenta judicial': 'court_account',
            'Nombre despacho judicial': 'court_name',
            'Identificación demandante': 'plaintiff_id',
            'Identificación demandado': 'defendant_id',
            'Valor Depósito': 'amount_cop',
            'Fecha Emisión': 'origin_date',
            'Dirección Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2020-2',
        sheet='Publicación',
        column_map={
            'Nro. Depósito Judicial': 'deposit_no',
            'Tipo Depósito Judicial': 'deposit_type',
            'No. cuenta judicial': 'court_account',
            'Nombre despacho judicial': 'court_name',
            'Identificación demandante': 'plaintiff_id',
            'Identificación demandado': 'defendant_id',
            'Valor Depósito': 'amount_cop',
            'Fecha Emisión': 'origin_date',
            'Dirección Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2021-1',
        sheet='Depósitos a Prescribir 2021-1a',
        column_map={
            'Tipo de Depósito': 'deposit_type',
            'Número de Depósito': 'deposit_no',
            'Número de Cuenta': 'court_account',
            'Despacho Judicial': 'court_name',
            'Identificación Demandante': 'plaintiff_id',
            'Identificación Demandado': 'defendant_id',
            'Valor del Depósito': 'amount_cop',
            'Fecha de Emisión ': 'origin_date',
            'Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2021-2',
        sheet='Detalle',
        column_map={
            'Tipo Depósito': 'deposit_type',
            'Número Depósito': 'deposit_no',
            'Cuenta Judicial': 'court_account',
            'Nombre Despacho Judicial': 'court_name',
            'Identificación Demandante': 'plaintiff_id',
            'Identificación Demandado': 'defendant_id',
            'Valor Depósito': 'amount_cop',
            'Fecha Elaboración': 'origin_date',
            'Dirección Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2022-1',
        sheet='Base Publicación',
        column_map={
            'Clasificación': 'classification',
            'Depósito Judicial': 'deposit_no',
            'Cuenta Judicial': 'court_account',
            'Nombre Despacho': 'court_name',
            'Demandante': 'plaintiff_id',
            'Demandando': 'defendant_id',
            'Valor': 'amount_cop',
            'Fecha': 'origin_date',
            'Dirección Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2022-2',
        sheet='Consolidado',
        column_map={
            'Clasificación': 'classification',
            'Numero depósito': 'deposit_no',
            'Cuenta judicial': 'court_account',
            'Nombre Despacho': 'court_name',
            'Demandante': 'plaintiff_id',
            'Demandado': 'defendant_id',
            'Valor Depósito': 'amount_cop',
            'Fecha Constitución': 'origin_date',
            'Dirección Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2023-1',
        sheet='Inventario Publicar',
        column_map={
            'Número Depósito Judicial': 'deposit_no',
            'Nombre Despacho': 'court_name',
            'Cuenta Judicial': 'court_account',
            'Demandante': 'plaintiff_id',
            'Demandado': 'defendant_id',
            'Valor Depósito': 'amount_cop',
            'Fecha Depósito': 'origin_date',
            'Seccional ': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2023-2',
        sheet='Busqueda',
        column_map={
            'Depósito': 'deposit_no',
            'Despacho Judicial': 'court_name',
            'Cuenta Judicial': 'court_account',
            'Tipo Identificación': 'plaintiff_id_type',
            'Identificación Demandante': 'plaintiff_id',
            'Nombre Demandante': 'plaintiff_name',
            'Tipo Identificación2': 'defendant_id_type',
            'Identificación Demandado': 'defendant_id',
            'Nombre Demandado': 'defendant_name',
            'Valor Depósito': 'amount_cop',
            'Fecha Constitución': 'origin_date',
            'Distrito Judicial': 'judicial_district',
            'Dpto.': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2024-1',
        sheet='Busqueda',
        column_map={
            'No. Depósito': 'deposit_no',
            'Despacho Judicial': 'court_name',
            'Cuenta Judicial': 'court_account',
            'Identificación Demandante': 'plaintiff_id',
            'Identificación Demandado': 'defendant_id',
            'Valor': 'amount_cop',
            'Fecha Constitución': 'origin_date',
            'Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2024-2',
        sheet='Busqueda',
        column_map={
            'No. Depósito': 'deposit_no',
            'Despacho Judicial': 'court_name',
            'Cuenta Judicial': 'court_account',
            'Identificación Demandante': 'plaintiff_id',
            'Identificación Demandado': 'defendant_id',
            'Valor': 'amount_cop',
            'Fecha Constitución': 'origin_date',
            'Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2025-1',
        sheet='Busqueda',
        column_map={
            'No. Depósito': 'deposit_no',
            'Despacho Judicial': 'court_name',
            'Cuenta Judicial': 'court_account',
            'Identificación Demandante': 'plaintiff_id',
            'Identificación Demandado': 'defendant_id',
            'Valor': 'amount_cop',
            'Fecha Constitución': 'origin_date',
            'Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2025-2',
        sheet='Busqueda',
        column_map={
            'No. Depósito': 'deposit_no',
            'Despacho Judicial': 'court_name',
            'Cuenta Judicial': 'court_account',
            'Identificación Demandante': 'plaintiff_id',
            'Identificación Demandado': 'defendant_id',
            'Valor': 'amount_cop',
            'Fecha Constitución': 'origin_date',
            'Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
    SheetMapping(
        period='2026-1',
        sheet='Busqueda',
        column_map={
            'No. Depósito': 'deposit_no',
            'Despacho Judicial': 'court_name',
            'Cuenta Judicial': 'court_account',
            'Identificación Demandante': 'plaintiff_id',
            'Identificación Demandado': 'defendant_id',
            'Valor': 'amount_cop',
            'Fecha Constitución': 'origin_date',
            'Seccional': 'seccional',
            'Departamento': 'department',
            'Ciudad': 'city',
        },
    ),
]


def get_mapping(period: str, sheet: str) -> SheetMapping:
    for mapping in SHEET_MAPPINGS:
        if mapping.period == period and mapping.sheet == sheet:
            return mapping
    raise KeyError(f"No column mapping for period={period!r} sheet={sheet!r}")
