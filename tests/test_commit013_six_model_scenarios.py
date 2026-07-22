from __future__ import annotations

from datetime import date
from decimal import Decimal

from axiom_engine.previous_close import DailyClose
from axiom_engine.valuation_api import BackendValuationAPIService


class CloseProvider:
    def previous_close(self, symbol, *, as_of=None):
        return DailyClose(
            symbol,
            date(2026, 7, 21),
            Decimal("207.2899932861328"),
            "USD",
            "America/New_York",
            "fixture",
        )


def service() -> BackendValuationAPIService:
    return BackendValuationAPIService(CloseProvider())


def test_default_nvda_scenario_remains_base():
    result = service().calculate({"symbol": "NVDA"})
    assert result["scenario_id"] == "valuation_scenario:NVDA-2026Q3-BASE"
    assert result["scenario_type"] == "base"
    assert {item["scenario_type"] for item in result["available_scenarios"]} == {
        "bear",
        "base",
        "bull",
    }


def test_each_nvda_scenario_completes_the_unified_six_model_profile():
    expected = {"forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb", "milestone"}
    for scenario_type in ("BEAR", "BASE", "BULL"):
        result = service().calculate(
            {
                "symbol": "NVDA",
                "scenario_id": f"valuation_scenario:NVDA-2026Q3-{scenario_type}",
            }
        )
        assert set(result["models"]) == expected
        assert result["summary"]["completed_models"] == 6
        assert result["summary"]["total_models"] == 6
        assert all(model["status"] == "completed" for model in result["models"].values())


def test_profile_weights_are_explicit_normalized_and_used_for_blending():
    result = service().calculate({"symbol": "NVDA"})
    models = result["models"]
    weights = {name: Decimal(model["blend_weight"]) for name, model in models.items()}
    assert weights == {
        "forward_pe": Decimal("0.3"),
        "peg": Decimal("0.25"),
        "forward_ps": Decimal("0.15"),
        "ev_ebitda": Decimal("0.15"),
        "forward_pb": Decimal("0.05"),
        "milestone": Decimal("0.1"),
    }
    assert sum(weights.values()) == Decimal("1")
    expected = sum(
        Decimal(model["fair_value"]) * weights[name] for name, model in models.items()
    )
    assert Decimal(result["summary"]["blended_fair_value"]) == expected.quantize(
        Decimal("0.000001")
    )


def test_peg_and_milestone_use_canonical_scenario_inputs_and_reference_price():
    result = service().calculate({"symbol": "NVDA"})
    peg = result["models"]["peg"]
    milestone = result["models"]["milestone"]
    reference = Decimal(result["reference_price"])

    assert Decimal(str(peg["inputs"]["forward_eps"])) == Decimal("12.8313")
    assert Decimal(str(peg["inputs"]["growth_rate"])) == Decimal("0.4279")
    assert Decimal(str(peg["inputs"]["target_peg"])) == Decimal("0.9")
    assert Decimal(str(peg["inputs"]["market_price"])) == reference

    assert Decimal(str(milestone["inputs"]["success_probability"])) == Decimal("0.6")
    assert Decimal(str(milestone["inputs"]["success_multiple"])) == Decimal("1.6")
    assert Decimal(str(milestone["inputs"]["failure_multiple"])) == Decimal("0.7")
    assert Decimal(str(milestone["inputs"]["market_price"])) == reference
