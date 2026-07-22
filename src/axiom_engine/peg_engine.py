from __future__ import annotations

from decimal import Decimal

from axiom_engine.valuation_models import PEGInputs, PEGResult, ValuationModelType


class PEGEngine:
    """Calculate a PEG-derived fair value with an explicit P/E fallback."""

    def calculate(self, inputs: PEGInputs) -> PEGResult:
        warnings: list[str] = []
        implied_pe = None
        applied_pe = None
        fair_value = None
        used_fallback = False

        if inputs.forward_earnings_per_share <= 0:
            warnings.append("PEG unavailable: forward earnings per share must be positive")
        elif inputs.growth_rate <= 0:
            used_fallback = True
            applied_pe = inputs.fallback_price_to_earnings
            fair_value = inputs.forward_earnings_per_share * applied_pe
            warnings.append("PEG unavailable: growth rate must be positive; fallback P/E applied")
        else:
            growth_percentage = inputs.growth_rate * Decimal("100")
            implied_pe = inputs.peg_ratio * growth_percentage
            applied_pe = implied_pe
            fair_value = inputs.forward_earnings_per_share * implied_pe

        upside = self._upside(fair_value, inputs.market_price, warnings)
        return PEGResult(
            identity=inputs.identity,
            model_type=ValuationModelType.price_earnings_growth,
            model_version=inputs.model_version,
            forward_earnings_per_share=inputs.forward_earnings_per_share,
            growth_rate=inputs.growth_rate,
            peg_ratio=inputs.peg_ratio,
            implied_price_to_earnings=implied_pe,
            applied_price_to_earnings=applied_pe,
            used_fallback=used_fallback,
            fair_value_per_share=fair_value,
            market_price=inputs.market_price,
            upside=upside,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _upside(
        fair_value: Decimal | None,
        market_price: Decimal | None,
        warnings: list[str],
    ) -> Decimal | None:
        if fair_value is None:
            return None
        if market_price is None:
            warnings.append("upside unavailable: market price missing")
            return None
        if market_price == 0:
            warnings.append("upside unavailable: market price is zero")
            return None
        return fair_value / market_price - Decimal("1")
