import gzip

import pytest

from axiom_engine.sec_financial_loader.core import (
    METRICS,
    _debt,
    _decode,
    _fiscal_year,
    _latest_annual,
    _validate_ua,
)


def test_gzip_decode():
    assert _decode(gzip.compress(b"{}"), "gzip") == b"{}"


def test_user_agent_ascii():
    with pytest.raises(ValueError):
        _validate_ua("AXIOM 測試 a@b.com")


def test_latest_annual_prefers_latest_filed():
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "fy": 2024, "start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "val": 10, "accn": "a"},
                            {"form": "10-K", "fy": 2025, "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "val": 12, "accn": "b"},
                        ]
                    }
                }
            }
        }
    }
    tag, row = _latest_annual(payload, METRICS["revenue"])
    assert tag == "Revenues" and row["val"] == 12


def test_latest_annual_accepts_missing_fy_for_annual_length_period():
    payload = {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "val": 7, "accn": "x"}
                        ]
                    }
                }
            }
        }
    }
    tag, row = _latest_annual(payload, METRICS["net_income"])
    assert tag == "NetIncomeLoss" and _fiscal_year(row) == 2025


def test_capex_productive_assets_fallback():
    payload = {
        "facts": {
            "us-gaap": {
                "PaymentsToAcquireProductiveAssets": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "fy": 2025, "fp": "FY", "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "val": 50, "accn": "x"}
                        ]
                    }
                }
            }
        }
    }
    tag, row = _latest_annual(payload, METRICS["capital_expenditures"])
    assert tag == "PaymentsToAcquireProductiveAssets" and row["val"] == 50


def test_debt_prefers_direct_total():
    payload = {
        "facts": {
            "us-gaap": {
                "LongTermDebtAndFinanceLeaseObligations": {
                    "units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 90, "accn": "a"}]}
                },
                "LongTermDebtCurrent": {
                    "units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 10, "accn": "a"}]}
                },
                "LongTermDebtNoncurrent": {
                    "units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 80, "accn": "a"}]}
                },
            }
        }
    }
    tag, row = _debt(payload)
    assert tag == "LongTermDebtAndFinanceLeaseObligations" and row["val"] == 90


def test_debt_sums_current_and_noncurrent_same_period():
    payload = {
        "facts": {
            "us-gaap": {
                "LongTermDebtCurrent": {
                    "units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 10, "accn": "a"}]}
                },
                "LongTermDebtNoncurrent": {
                    "units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 80, "accn": "a"}]}
                },
            }
        }
    }
    tag, row = _debt(payload)
    assert tag == "LongTermDebtCurrent+LongTermDebtNoncurrent"
    assert str(row["val"]) == "90"
    assert row["_derived_tags"] == ["LongTermDebtCurrent", "LongTermDebtNoncurrent"]


def test_debt_adaptive_pair_supports_debt_current_noncurrent():
    payload = {
        "facts": {"us-gaap": {
            "DebtCurrent": {"units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 12, "accn": "a"}]}},
            "DebtNoncurrent": {"units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 88, "accn": "a"}]}},
        }}
    }
    tag, row = _debt(payload)
    assert tag == "DebtCurrent+DebtNoncurrent"
    assert str(row["val"]) == "100"


def test_debt_noncurrent_proxy_is_explicitly_marked():
    payload = {
        "facts": {"us-gaap": {
            "LongTermDebtNoncurrent": {"units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 80, "accn": "a"}]}}
        }}
    }
    tag, row = _debt(payload)
    assert tag == "LongTermDebtNoncurrent[proxy]"
    assert row["_coverage_proxy"] == "noncurrent_debt_only"


def test_debt_notes_payable_pair():
    payload = {
        "facts": {"us-gaap": {
            "NotesPayableCurrent": {"units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 12, "accn": "a"}]}},
            "NotesPayableNoncurrent": {"units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 88, "accn": "a"}]}},
        }}
    }
    tag, row = _debt(payload)
    assert tag == "NotesPayableCurrent+NotesPayableNoncurrent"
    assert str(row["val"]) == "100"


def test_debt_finance_lease_pair_is_traceable():
    payload = {
        "facts": {"us-gaap": {
            "FinanceLeaseLiabilityCurrent": {"units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 5, "accn": "a"}]}},
            "FinanceLeaseLiabilityNoncurrent": {"units": {"USD": [{"form": "10-K", "fy": 2025, "end": "2025-12-31", "filed": "2026-02-01", "val": 45, "accn": "a"}]}},
        }}
    }
    tag, row = _debt(payload)
    assert tag == "FinanceLeaseLiabilityCurrent+FinanceLeaseLiabilityNoncurrent"
    assert row["_derived_tags"] == ["FinanceLeaseLiabilityCurrent", "FinanceLeaseLiabilityNoncurrent"]
