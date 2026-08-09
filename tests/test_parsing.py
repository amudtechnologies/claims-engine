from datetime import date, datetime

import pytest

from claims_engine.parsing import (
    nit_check_digit,
    normalize_id,
    parse_currency_cop,
    parse_deposit_date,
)

# Every value below was pulled live from S3 during Phase 2 planning (2017-1, 2018-2's
# real detail sheet) — not invented. See docs/phase0_schema_matrix.csv.
CURRENCY_CASES = [
    ("20501", 20501),
    ("121378.11", 121378),
    ("2681947.56", 2681947),
    ("115,258,00", 115258),
    ("19,775,00", 19775),
    ("$ 88.000,oo", 88000),
    ("$ 250.000,oo", 250000),
    (" $260.000.00 ", 260000),
    ("$150.000.oo", 150000),
    ("$10.000.oo", 10000),
    ("135.000,00", 135000),
    ("24.356.33", 24356),
    ("166.642.83", 166642),
    ("\xa0$ \xa0 2.863.837,00\xa0", 2863837),
    ("700,000,00", 700000),
    ("2,570,334,72", 2570334),
    ("9044965.199999999", 9044965),
    ("1043912.5", 1043912),  # banker's rounding on the exact .5 boundary
    (1500000, 1500000),
    (1500000.0, 1500000),
    (None, None),
    ("", None),
    ("abc", None),
]


@pytest.mark.parametrize("raw,expected", CURRENCY_CASES)
def test_parse_currency_cop(raw, expected):
    assert parse_currency_cop(raw) == expected


def test_parse_currency_cop_negative():
    assert parse_currency_cop("-135.000,00") == -135000


DATE_CASES = [
    ("2011-03-13 00:00:00", date(2011, 3, 13)),
    ("2019-12-09 00:00:00", date(2019, 12, 9)),
    ("02/11/1963", date(1963, 11, 2)),
    ("29/10/2015", date(2015, 10, 29)),
    ("26/08/2016", date(2016, 8, 26)),
    ("19991004", date(1999, 10, 4)),
    ("20130617", date(2013, 6, 17)),
    (20080417.0, date(2008, 4, 17)),
    (19991020.0, date(1999, 10, 20)),
    (datetime(2026, 1, 15), date(2026, 1, 15)),
    (date(2026, 1, 15), date(2026, 1, 15)),
    (None, None),
    ("not a date", None),
    ("2026-13-01", None),  # month 13 doesn't exist
]


@pytest.mark.parametrize("raw,expected", DATE_CASES)
def test_parse_deposit_date(raw, expected):
    assert parse_deposit_date(raw) == expected


ID_CASES = [
    ("900123456", "900123456"),
    ("80123456", "80123456"),
    ("Desconocido", None),
    ("desconocido", None),
    (900123456, "900123456"),
    (900123456.0, "900123456"),
    (None, None),
    ("", None),
]


@pytest.mark.parametrize("raw,expected", ID_CASES)
def test_normalize_id(raw, expected):
    assert normalize_id(raw) == expected


def test_nit_check_digit_matches_dian_worked_example():
    # DIAN's own published example: base 123456789 -> check digit 6.
    # (9*3)+(8*7)+(7*13)+(6*17)+(5*19)+(4*23)+(3*29)+(2*37)+(1*41) = 665
    # 665 % 11 = 5; since > 1, DV = 11 - 5 = 6.
    assert nit_check_digit("123456789") == "6"
