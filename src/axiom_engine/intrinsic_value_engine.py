from __future__ import annotations

from axiom_engine.dcf_engine import DiscountedCashFlowEngine
from axiom_engine.multiples_engine import MultiplesEngine
from axiom_engine.reverse_dcf_engine import ReverseDiscountedCashFlowEngine
from axiom_engine.valuation_models import (
    IntrinsicValueInputs,
    IntrinsicValueResult,
)


class IntrinsicValueEngine:
    """Unified entry point for supported valuation engines."""

    def __init__(
        self,
        *,
        dcf_engine: DiscountedCashFlowEngine | None = None,
        reverse_dcf_engine: ReverseDiscountedCashFlowEngine | None = None,
        multiples_engine: MultiplesEngine | None = None,
    ) -> None:
        self._dcf_engine = dcf_engine or DiscountedCashFlowEngine()
        self._reverse_dcf_engine = reverse_dcf_engine or ReverseDiscountedCashFlowEngine()
        self._multiples_engine = multiples_engine or MultiplesEngine()

    def calculate(self, inputs: IntrinsicValueInputs) -> IntrinsicValueResult:
        """Run every valuation model supplied in ``inputs`` independently."""

        dcf_result = None
        reverse_dcf_result = None
        multiples_result = None
        warnings: list[str] = []

        if inputs.dcf is not None:
            dcf_result = self._dcf_engine.calculate(
                inputs.dcf,
                market_price=inputs.market_price,
            )

        if inputs.reverse_dcf is not None:
            reverse_dcf_result = self._reverse_dcf_engine.calculate(inputs.reverse_dcf)
            if not reverse_dcf_result.converged:
                warnings.append("reverse DCF did not converge")

        if inputs.multiples is not None:
            multiples_result = self._multiples_engine.calculate(inputs.multiples)

        return IntrinsicValueResult(
            identity=inputs.identity,
            model_version=inputs.model_version,
            dcf=dcf_result,
            reverse_dcf=reverse_dcf_result,
            multiples=multiples_result,
            warnings=tuple(warnings),
        )
