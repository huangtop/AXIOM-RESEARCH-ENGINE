from __future__ import annotations

from decimal import Decimal

from axiom_engine.valuation_models import (
    MilestoneInputs,
    MilestoneResult,
    ValuationModelType,
)


class MilestoneEngine:
    """Calculate a probability-weighted milestone scenario value."""

    def calculate(self, inputs: MilestoneInputs) -> MilestoneResult:
        failure_probability = Decimal("1") - inputs.success_probability
        success_value = inputs.current_price * inputs.success_multiple
        failure_value = inputs.current_price * inputs.failure_multiple
        expected_multiple = (
            inputs.success_multiple * inputs.success_probability
            + inputs.failure_multiple * failure_probability
        )
        fair_value = inputs.current_price * expected_multiple
        upside = None
        warnings: list[str] = []
        if inputs.current_price == 0:
            warnings.append("upside unavailable: current price is zero")
        else:
            upside = fair_value / inputs.current_price - Decimal("1")

        return MilestoneResult(
            identity=inputs.identity,
            model_type=ValuationModelType.milestone_scenario,
            model_version=inputs.model_version,
            current_price=inputs.current_price,
            success_probability=inputs.success_probability,
            failure_probability=failure_probability,
            success_multiple=inputs.success_multiple,
            failure_multiple=inputs.failure_multiple,
            success_value_per_share=success_value,
            failure_value_per_share=failure_value,
            expected_multiple=expected_multiple,
            fair_value_per_share=fair_value,
            upside=upside,
            warnings=tuple(warnings),
        )
