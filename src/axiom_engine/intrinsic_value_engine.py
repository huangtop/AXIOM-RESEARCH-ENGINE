from __future__ import annotations

from axiom_engine.dcf_engine import DiscountedCashFlowEngine
from axiom_engine.milestone_engine import MilestoneEngine
from axiom_engine.multiples_engine import MultiplesEngine
from axiom_engine.peg_engine import PEGEngine
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
        peg_engine: PEGEngine | None = None,
        milestone_engine: MilestoneEngine | None = None,
    ) -> None:
        self._dcf_engine = dcf_engine or DiscountedCashFlowEngine()
        self._reverse_dcf_engine = reverse_dcf_engine or ReverseDiscountedCashFlowEngine()
        self._multiples_engine = multiples_engine or MultiplesEngine()
        self._peg_engine = peg_engine or PEGEngine()
        self._milestone_engine = milestone_engine or MilestoneEngine()

    def calculate(self, inputs: IntrinsicValueInputs) -> IntrinsicValueResult:
        """Run every valuation model supplied in ``inputs`` independently."""

        dcf_result = None
        reverse_dcf_result = None
        multiples_result = None
        peg_result = None
        milestone_result = None
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

        if inputs.peg is not None:
            peg_result = self._peg_engine.calculate(inputs.peg)

        if inputs.milestone is not None:
            milestone_result = self._milestone_engine.calculate(inputs.milestone)

        return IntrinsicValueResult(
            identity=inputs.identity,
            model_version=inputs.model_version,
            dcf=dcf_result,
            reverse_dcf=reverse_dcf_result,
            multiples=multiples_result,
            peg=peg_result,
            milestone=milestone_result,
            warnings=tuple(warnings),
        )
