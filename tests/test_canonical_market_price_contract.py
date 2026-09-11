from __future__ import annotations

import json
import math
from pathlib import Path

from axiom_engine.full_market_coverage.core import _dual_fy_seven_models
from axiom_engine.multiple_policy import build_multiple_policy


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_multiple_policy_uses_canonical_market_close_not_snapshot_previous_close(
    tmp_path: Path,
):
    _write_json(
        tmp_path / "data/generated/company/yahoo_company_snapshot.json",
        {
            "symbols": {
                "AAA": {
                    "fetched_at": "2026-09-11T00:00:00+00:00",
                    "previous_close": "999",
                    "shares_outstanding": "10",
                    "trailing_eps": "4",
                    # Deliberately wrong. P/E must be rebuilt from canonical close / EPS.
                    "trailing_pe": "999",
                    "revenue_ttm": "800",
                    "price_to_book": "5",
                    "enterprise_to_ebitda": "14",
                    "annual_estimates": {
                        "CURRENT_FY": {
                            "eps": "8",
                            "revenue": "1600",
                        },
                        "NEXT_FY": {
                            "eps": "10",
                            "revenue": "1900",
                        },
                    },
                }
            }
        },
    )
    _write_json(
        tmp_path / "data/generated/market/previous_close_cache.json",
        {"AAA": [100, "2026-09-10"]},
    )
    _write_json(
        tmp_path / "data/universe/securities.json",
        [{"ticker": "AAA", "company_id": "c1"}],
    )

    report = build_multiple_policy(tmp_path)
    company = next(row for row in report["companies"] if row["company_id"] == "c1")

    current_pe = 100.0 / 4.0
    expected_pe = current_pe / math.sqrt(8.0 / 4.0)
    current_ps = 100.0 * 10.0 / 800.0
    expected_ps = current_ps / math.sqrt(1600.0 / 800.0)

    assert math.isclose(
        company["assumptions"]["target_forward_pe"],
        expected_pe,
        rel_tol=1e-12,
    )
    assert math.isclose(
        company["assumptions"]["target_forward_ps"],
        expected_ps,
        rel_tol=1e-12,
    )
    assert report["policy"]["market_price_source"] == (
        "data/generated/market/previous_close_cache.json"
    )
    assert any(
        evidence.startswith("canonical-market-close:AAA:")
        and evidence.endswith(":2026-09-10")
        for evidence in company["evidence_ids"]
    )


def test_multiple_policy_does_not_fall_back_to_snapshot_price_when_market_missing(
    tmp_path: Path,
):
    _write_json(
        tmp_path / "data/generated/company/yahoo_company_snapshot.json",
        {
            "symbols": {
                "AAA": {
                    "previous_close": "999",
                    "shares_outstanding": "10",
                    "trailing_pe": "25",
                    "revenue_ttm": "800",
                    "price_to_book": "5",
                    "enterprise_to_ebitda": "14",
                }
            }
        },
    )
    _write_json(
        tmp_path / "data/universe/securities.json",
        [{"ticker": "AAA", "company_id": "c1"}],
    )

    report = build_multiple_policy(tmp_path)
    company = next(row for row in report["companies"] if row["company_id"] == "c1")

    # Without canonical market price, neither P/E nor P/S may be
    # manufactured from snapshot.previous_close or snapshot.trailing_pe.
    assert "target_forward_pe" not in company["assumptions"]
    assert "target_forward_ps" not in company["assumptions"]


def test_dual_fy_models_ignore_snapshot_previous_close_as_price_fallback():
    horizons = _dual_fy_seven_models(
        {
            "previous_close": "999",
            "trailing_eps": "5",
            "trailing_pe": "20",
            "revenue_ttm": "500",
            "shares_outstanding": "10",
            "annual_estimates": {
                "CURRENT_FY": {
                    "eps": "6",
                    "revenue": "600",
                    "peg_growth": "0.10",
                },
                "NEXT_FY": {
                    "eps": "7",
                    "revenue": "700",
                    "peg_growth": "0.10",
                },
            },
        },
        {"diluted_shares_outstanding": {"value": "10"}},
        {},
        {},
        {},
    )

    current = horizons["CURRENT_FY"]
    pe = current["models"]["forward_pe"]

    assert pe["inputs"]["observed_price"] is None
    assert pe["inputs"]["observed_trailing_pe"] is None
    assert all(
        model.get("fair_value") != "999"
        for model in current["models"].values()
    )
