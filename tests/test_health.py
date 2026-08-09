from claims_engine.health import reconciliation_error
from claims_engine.normalize import FileNormalizeResult


def test_reconciliation_error_none_when_counts_match():
    result = FileNormalizeResult(key="k", ok_rows=[{}], reject_rows=[{}], rows_read=2)
    assert reconciliation_error(result) is None


def test_reconciliation_error_reports_mismatch():
    result = FileNormalizeResult(key="k", ok_rows=[{}], reject_rows=[], rows_read=2)
    error = reconciliation_error(result)
    assert error == "1 ok + 0 rejected != 2 read"
