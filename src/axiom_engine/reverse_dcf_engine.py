from __future__ import annotations

from decimal import Decimal

from axiom_engine.dcf_engine import DiscountedCashFlowEngine
from axiom_engine.valuation_models import (
    DCFInputs,
    ForecastPeriod,
    ReverseDCFInputs,
    ReverseDCFResult,
    ValuationModelType,
    ValuationResult,
)


class ReverseDiscountedCashFlowEngine:
    """Solve the constant explicit-period FCF growth implied by market price."""

    def __init__(self, dcf_engine: DiscountedCashFlowEngine | None = None) -> None:
        self._dcf_engine = dcf_engine or DiscountedCashFlowEngine()

    def calculate(self, inputs: ReverseDCFInputs) -> ReverseDCFResult:
        """Return the market-implied growth rate using deterministic bisection.

        The solved growth rate compounds ``current_free_cash_flow`` through each
        explicit forecast year. Discount rates, terminal assumptions, and capital
        structure remain fixed. No presentation rounding is applied.
        """

        shares = inputs.capital_structure.diluted_shares_outstanding
        if shares is None:  # guarded by ReverseDCFInputs
            raise ValueError("diluted_shares_outstanding is required")

        target_equity = inputs.market_price * shares
        capital = inputs.capital_structure
        target_enterprise = (
            target_equity
            - capital.cash_and_equivalents
            + capital.total_debt
            + capital.non_controlling_interest
            + capital.preferred_stock
        )
        if target_enterprise <= 0:
            raise ValueError("market price implies a non-positive enterprise value")

        lower = inputs.minimum_growth_rate
        upper = inputs.maximum_growth_rate
        lower_result = self._evaluate(inputs, lower)
        upper_result = self._evaluate(inputs, upper)
        lower_error = lower_result.enterprise_value - target_enterprise
        upper_error = upper_result.enterprise_value - target_enterprise

        if lower_error == 0:
            return self._build_result(
                inputs, lower, lower_result, target_equity, target_enterprise, 0
            )
        if upper_error == 0:
            return self._build_result(
                inputs, upper, upper_result, target_equity, target_enterprise, 0
            )
        if lower_error > 0 or upper_error < 0:
            raise ValueError(
                "target enterprise value is outside the configured growth-rate bounds"
            )

        candidate = lower
        candidate_result = lower_result
        iterations = 0
        for iterations in range(1, inputs.max_iterations + 1):
            candidate = (lower + upper) / Decimal("2")
            candidate_result = self._evaluate(inputs, candidate)
            error = candidate_result.enterprise_value - target_enterprise
            if abs(error) <= inputs.tolerance:
                break
            if error < 0:
                lower = candidate
            else:
                upper = candidate

        return self._build_result(
            inputs,
            candidate,
            candidate_result,
            target_equity,
            target_enterprise,
            iterations,
        )

    def _evaluate(
        self, inputs: ReverseDCFInputs, growth_rate: Decimal
    ) -> ValuationResult:
        forecasts = tuple(
            ForecastPeriod(
                fiscal_year=inputs.identity.as_of_date.year + period_number,
                free_cash_flow=inputs.current_free_cash_flow
                * ((Decimal("1") + growth_rate) ** period_number),
            )
            for period_number in range(1, inputs.forecast_years + 1)
        )
        dcf_inputs = DCFInputs(
            identity=inputs.identity,
            forecasts=forecasts,
            discount_rates=inputs.discount_rates,
            terminal_value=inputs.terminal_value,
            capital_structure=inputs.capital_structure,
            model_version=inputs.model_version,
        )
        return self._dcf_engine.calculate(dcf_inputs, market_price=inputs.market_price)

    @staticmethod
    def _build_result(
        inputs: ReverseDCFInputs,
        growth_rate: Decimal,
        dcf_result: ValuationResult,
        target_equity: Decimal,
        target_enterprise: Decimal,
        iterations: int,
    ) -> ReverseDCFResult:
        enterprise_value = dcf_result.enterprise_value
        equity_value = dcf_result.equity_value
        fair_value_per_share = dcf_result.fair_value_per_share
        terminal_value = dcf_result.terminal_value
        present_value_terminal = dcf_result.present_value_terminal
        if fair_value_per_share is None or terminal_value is None or present_value_terminal is None:
            raise ValueError("reverse DCF produced incomplete valuation outputs")

        valuation_error = enterprise_value - target_enterprise
        converged = abs(valuation_error) <= inputs.tolerance
        warnings = () if converged else ("solver reached max_iterations before tolerance",)
        return ReverseDCFResult(
            identity=inputs.identity,
            model_type=ValuationModelType.reverse_discounted_cash_flow,
            model_version=inputs.model_version,
            market_price=inputs.market_price,
            target_equity_value=target_equity,
            target_enterprise_value=target_enterprise,
            implied_growth_rate=growth_rate,
            enterprise_value=enterprise_value,
            equity_value=equity_value,
            implied_value_per_share=fair_value_per_share,
            forecast_values=dcf_result.forecast_values,
            terminal_value=terminal_value,
            present_value_terminal=present_value_terminal,
            iterations=iterations,
            converged=converged,
            valuation_error=valuation_error,
            warnings=warnings,
        )
