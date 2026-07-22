from __future__ import annotations

from decimal import Decimal

from axiom_engine.valuation_models import (
    MultipleAssumption,
    MultiplesInputs,
    MultiplesResult,
    MultipleValuation,
    RelativeMultipleType,
    ValuationModelType,
)


_ENTERPRISE_MULTIPLES = {
    RelativeMultipleType.ev_to_revenue,
    RelativeMultipleType.ev_to_ebit,
    RelativeMultipleType.ev_to_ebitda,
    RelativeMultipleType.ev_to_free_cash_flow,
}


class MultiplesEngine:
    """Calculate observed multiples and values implied by target multiples."""

    def calculate(self, inputs: MultiplesInputs) -> MultiplesResult:
        market_equity = self._market_equity_value(inputs)
        market_enterprise = None
        warnings: list[str] = []
        if market_equity is not None:
            market_enterprise = self._equity_to_enterprise(inputs, market_equity)
        elif inputs.market_price is not None:
            warnings.append("market values unavailable: shares outstanding missing")

        assumptions = {item.multiple_type: item for item in inputs.assumptions}
        valuations = tuple(
            self._calculate_multiple(
                inputs,
                multiple_type,
                assumptions.get(multiple_type),
                market_equity,
                market_enterprise,
            )
            for multiple_type in RelativeMultipleType
        )
        return MultiplesResult(
            identity=inputs.identity,
            model_type=ValuationModelType.relative_multiples,
            model_version=inputs.model_version,
            market_equity_value=market_equity,
            market_enterprise_value=market_enterprise,
            valuations=valuations,
            warnings=tuple(warnings),
        )

    def _calculate_multiple(
        self,
        inputs: MultiplesInputs,
        multiple_type: RelativeMultipleType,
        assumption: MultipleAssumption | None,
        market_equity: Decimal | None,
        market_enterprise: Decimal | None,
    ) -> MultipleValuation:
        denominator = self._denominator(inputs, multiple_type)
        warnings: list[str] = []
        if denominator is None:
            warnings.append("multiple unavailable: denominator missing")
        elif denominator <= 0:
            warnings.append("multiple unavailable: denominator must be positive")

        market_value = (
            market_enterprise if multiple_type in _ENTERPRISE_MULTIPLES else market_equity
        )
        observed = None
        if denominator is not None and denominator > 0:
            if market_value is None:
                warnings.append("observed multiple unavailable: market value missing")
            elif market_value < 0:
                warnings.append("observed multiple unavailable: market value is negative")
            else:
                observed = market_value / denominator

        target = assumption.multiple if assumption is not None else None
        implied_enterprise = None
        implied_equity = None
        implied_per_share = None
        upside = None
        if target is not None and denominator is not None and denominator > 0:
            implied_value = denominator * target
            if multiple_type in _ENTERPRISE_MULTIPLES:
                implied_enterprise = implied_value
                implied_equity = self._enterprise_to_equity(inputs, implied_enterprise)
            else:
                implied_equity = implied_value
                implied_enterprise = self._equity_to_enterprise(inputs, implied_equity)

            shares = self._shares(inputs, multiple_type)
            if implied_equity < 0:
                warnings.append("implied value per share unavailable: equity value is negative")
            elif shares is None:
                warnings.append("implied value per share unavailable: shares outstanding missing")
            else:
                implied_per_share = implied_equity / shares
                if inputs.market_price is None:
                    warnings.append("upside unavailable: market price missing")
                elif inputs.market_price == 0:
                    warnings.append("upside unavailable: market price is zero")
                else:
                    upside = implied_per_share / inputs.market_price - Decimal("1")

        return MultipleValuation(
            multiple_type=multiple_type,
            denominator=denominator,
            observed_multiple=observed,
            target_multiple=target,
            implied_enterprise_value=implied_enterprise,
            implied_equity_value=implied_equity,
            implied_value_per_share=implied_per_share,
            upside=upside,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _denominator(inputs: MultiplesInputs, multiple_type: RelativeMultipleType) -> Decimal | None:
        financials = inputs.financials
        values = {
            RelativeMultipleType.ev_to_revenue: financials.revenue,
            RelativeMultipleType.ev_to_ebit: financials.ebit,
            RelativeMultipleType.ev_to_ebitda: financials.ebitda,
            RelativeMultipleType.ev_to_free_cash_flow: financials.free_cash_flow,
            RelativeMultipleType.price_to_earnings_basic: financials.net_income,
            RelativeMultipleType.price_to_earnings_diluted: financials.net_income,
            RelativeMultipleType.price_to_book: financials.book_value,
            RelativeMultipleType.price_to_sales: financials.revenue,
        }
        return values[multiple_type]

    @staticmethod
    def _shares(inputs: MultiplesInputs, multiple_type: RelativeMultipleType) -> Decimal | None:
        if multiple_type is RelativeMultipleType.price_to_earnings_basic:
            return inputs.financials.basic_shares_outstanding
        return inputs.capital_structure.diluted_shares_outstanding

    @staticmethod
    def _market_equity_value(inputs: MultiplesInputs) -> Decimal | None:
        if inputs.market_price is None:
            return None
        shares = inputs.capital_structure.diluted_shares_outstanding
        if shares is None:
            return None
        return inputs.market_price * shares

    @staticmethod
    def _enterprise_to_equity(inputs: MultiplesInputs, enterprise_value: Decimal) -> Decimal:
        capital = inputs.capital_structure
        return (
            enterprise_value
            + capital.cash_and_equivalents
            - capital.total_debt
            - capital.non_controlling_interest
            - capital.preferred_stock
        )

    @staticmethod
    def _equity_to_enterprise(inputs: MultiplesInputs, equity_value: Decimal) -> Decimal:
        capital = inputs.capital_structure
        return (
            equity_value
            + capital.total_debt
            + capital.non_controlling_interest
            + capital.preferred_stock
            - capital.cash_and_equivalents
        )
