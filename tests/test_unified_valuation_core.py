from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from axiom_engine.unified_valuation import MODEL_NAMES, build_unified_valuation


ROOT = Path(__file__).resolve().parents[1]

REAL_CANARIES = {
    "NVDA": {
        "company_id": "company:US-CIK0001045810",
        "card_path": "data/generated/full_market_coverage/per-company/company%3AUS-CIK0001045810.json",
    },
    "PM": {
        "company_id": "company:US-CIK0001413329",
        "card_path": "data/generated/full_market_coverage/per-company/company%3AUS-CIK0001413329.json",
    },
}


def metric(value, as_of_date="2026-08-25"):
    return {"status": "ready", "value": str(value), "as_of_date": as_of_date}


def base_inputs():
    financials = {
        "revenue": metric("1000"),
        "net_income": metric("200"),
        "free_cash_flow": metric("150"),
        "diluted_shares_outstanding": metric("100"),
        "cash_and_cash_equivalents": metric("100"),
        "total_debt": metric("50"),
        "book_value_per_share": metric("10"),
        "ebitda": metric("300"),
    }
    estimates = {
        "forward_eps": metric("5"),
        "forward_eps_growth": metric("0.25"),
        "forward_revenue": metric("1200"),
        "forward_ebitda": metric("350"),
    }
    assumptions = {
        "target_forward_pe": "20",
        "target_peg": "1",
        "target_forward_ps": "8",
        "target_ev_ebitda": "12",
        "target_forward_pb": "4",
        "milestone_success_probability": "0.50",
        "milestone_success_value_per_share": "120",
        "milestone_failure_value_per_share": "40",
    }
    dcf_policy = {
        "default_growth": "0.08",
        "discount_rate": "0.10",
        "terminal_growth": "0.03",
        "forecast_years": 5,
    }
    return financials, estimates, assumptions, dcf_policy


def build(**overrides):
    financials, estimates, assumptions, dcf_policy = base_inputs()
    payload = {
        "symbol": "NVDA",
        "financials": financials,
        "estimates": estimates,
        "assumptions": assumptions,
        "dcf_policy": dcf_policy,
        "reference_price": {
            "value": "90",
            "currency": "USD",
            "as_of_date": "2026-08-25",
            "source": "test",
        },
    }
    payload.update(overrides)
    return build_unified_valuation(**payload)


def _load_json(relpath: str):
    return json.loads((ROOT / relpath).read_text(encoding="utf-8"))


def _knowledge_assumption_row(company_id: str):
    rows = _load_json("data/knowledge/valuation_assumptions.json")
    for row in rows:
        if str(row.get("company_id") or "") == company_id:
            return row
    raise AssertionError(f"Missing knowledge valuation assumptions for {company_id}")


def _dcf_policy():
    return _load_json("config/valuation_dcf_policy.v1.json")


def _real_canary(symbol: str):
    spec = REAL_CANARIES[symbol]
    card = _load_json(spec["card_path"])
    assumption_row = _knowledge_assumption_row(spec["company_id"])

    market = card.get("market") or {}
    reference_price = {
        "value": market.get("current_price"),
        "currency": market.get("currency"),
        "as_of_date": market.get("as_of_date"),
        "source": "full_market_coverage.market",
    }

    return build_unified_valuation(
        symbol=symbol,
        financials=card.get("financials") or {},
        estimates=card.get("estimates") or {},
        assumptions=assumption_row.get("assumptions") or {},
        assumption_roles=assumption_row.get("assumption_roles") or {},
        dcf_policy=_dcf_policy(),
        reference_price=reference_price,
    )


def test_contract_has_all_seven_models_and_same_shape():
    result = build()
    assert result["contract_version"] == "unified-valuation.v1"
    assert tuple(result["models"]) == MODEL_NAMES
    for name in MODEL_NAMES:
        model = result["models"][name]
        assert "status" in model
        assert "effective_weight" in model
        assert "bear_fair_value" in model
        assert "base_fair_value" in model
        assert "bull_fair_value" in model


def test_weights_sum_to_one_across_included_models():
    result = build()
    weights = {
        name: Decimal(value)
        for name, value in result["aggregation"]["normalized_weights"].items()
    }
    included = result["aggregation"]["included_models"]
    assert included
    assert sum((weights[name] for name in included), Decimal("0")) == Decimal("1")


def test_market_anchored_model_gets_zero_weight():
    result = build(
        assumption_roles={"target_forward_pe": "market_anchored"}
    )
    assert result["models"]["forward_pe"]["effective_weight"] == "0"
    assert result["models"]["forward_pe"]["included_in_independent_aggregation"] is False
    assert "forward_pe" in result["diagnostics"]["market_anchored_models"]


def test_headline_scenarios_are_backend_generated_and_monotonic():
    result = build()
    bear = Decimal(result["headline"]["bear_fair_value"])
    base = Decimal(result["headline"]["base_fair_value"])
    bull = Decimal(result["headline"]["bull_fair_value"])
    assert bear < base < bull
    assert result["range"]["low"] == result["headline"]["bear_fair_value"]
    assert result["range"]["base"] == result["headline"]["base_fair_value"]
    assert result["range"]["high"] == result["headline"]["bull_fair_value"]


def test_loss_making_company_disables_forward_earnings_family():
    financials, estimates, assumptions, dcf_policy = base_inputs()
    financials["net_income"] = metric("-50")
    result = build_unified_valuation(
        symbol="LOSS",
        financials=financials,
        estimates=estimates,
        assumptions=assumptions,
        dcf_policy=dcf_policy,
    )
    assert result["aggregation"]["financial_archetype"] == "loss_making_or_pre_profit"
    assert result["models"]["forward_pe"]["effective_weight"] == "0"
    assert result["models"]["peg"]["effective_weight"] == "0"


def test_dcf_is_not_globally_forced_to_zero():
    result = build()
    assert Decimal(result["models"]["dcf"]["effective_weight"]) > 0


def test_dominant_model_is_backend_output():
    result = build()
    dominant = result["headline"]["dominant_model"]
    assert dominant in MODEL_NAMES
    weights = {
        name: Decimal(value)
        for name, value in result["aggregation"]["normalized_weights"].items()
    }
    assert weights[dominant] == max(weights.values())


def test_real_nvda_and_pm_share_identical_unified_contract_shape():
    nvda = _real_canary("NVDA")
    pm = _real_canary("PM")

    assert nvda["contract_version"] == pm["contract_version"] == "unified-valuation.v1"
    assert tuple(nvda["models"]) == tuple(pm["models"]) == MODEL_NAMES
    assert tuple(nvda["headline"]) == tuple(pm["headline"])
    assert tuple(nvda["scenarios"]) == tuple(pm["scenarios"])
    assert tuple(nvda["range"]) == tuple(pm["range"])
    assert tuple(nvda["aggregation"]) == tuple(pm["aggregation"])


def test_real_nvda_and_pm_backend_scenarios_are_available_and_monotonic():
    for symbol in ("NVDA", "PM"):
        result = _real_canary(symbol)
        bear = Decimal(result["headline"]["bear_fair_value"])
        base = Decimal(result["headline"]["base_fair_value"])
        bull = Decimal(result["headline"]["bull_fair_value"])

        assert bear < base < bull, symbol
        assert result["scenarios"]["bear"]["status"] == "calculated"
        assert result["scenarios"]["base"]["status"] == "calculated"
        assert result["scenarios"]["bull"]["status"] == "calculated"


def test_real_nvda_and_pm_weights_are_backend_normalized():
    for symbol in ("NVDA", "PM"):
        result = _real_canary(symbol)
        included = result["aggregation"]["included_models"]
        weights = {
            name: Decimal(value)
            for name, value in result["aggregation"]["normalized_weights"].items()
        }
        assert included, symbol
        assert sum((weights[name] for name in included), Decimal("0")) == Decimal("1"), symbol


def test_real_canary_diagnostics():
    seen = []
    for symbol in ("NVDA", "PM"):
        result = _real_canary(symbol)
        weights = result["aggregation"]["normalized_weights"]
        calculated = [
            name
            for name in MODEL_NAMES
            if result["models"][name]["status"] == "calculated"
        ]
        included = result["aggregation"]["included_models"]

        line = (
            "CANARY "
            + symbol
            + f" archetype={result['aggregation']['financial_archetype']}"
            + f" dominant={result['headline']['dominant_model']}"
            + f" bear={result['headline']['bear_fair_value']}"
            + f" base={result['headline']['base_fair_value']}"
            + f" bull={result['headline']['bull_fair_value']}"
            + f" calculated={','.join(calculated)}"
            + f" included={','.join(included)}"
            + " weights="
            + ",".join(
                f"{name}:{Decimal(weights[name]):.4f}"
                for name in MODEL_NAMES
                if Decimal(weights[name]) > 0
            )
            + f" market_anchored={','.join(result['diagnostics']['market_anchored_models']) or '-'}"
        )
        print(line)
        seen.append(symbol)

    assert seen == ["NVDA", "PM"]