from __future__ import annotations

from decimal import Decimal

from axiom_engine.valuation_models import (
    DCFInputs,
    DiscountedCashFlowPeriod,
    TerminalValueMethod,
    ValuationModelType,
    ValuationResult,
)


class DiscountedCashFlowEngine:
    """Calculate an enterprise-value DCF from immutable ``DCFInputs``."""

    def calculate(
        self,
        inputs: DCFInputs,
        *,
        market_price: Decimal | None = None,
    ) -> ValuationResult:
        """Return a deterministic DCF result without implicit rounding.

        Forecast periods are discounted as year-end cash flows. Terminal value is
        calculated from the final forecast period and discounted by the same final
        period exponent.
        """

        if market_price is not None and market_price < 0:
            raise ValueError("market_price cannot be negative")

        wacc = inputs.discount_rates.weighted_average_cost_of_capital
        if wacc <= 0:
            raise ValueError("WACC must be positive")

        forecast_values = tuple(
            self._discount_forecast_period(period_number, forecast, wacc)
            for period_number, forecast in enumerate(inputs.forecasts, start=1)
        )

        final_free_cash_flow = inputs.forecasts[-1].free_cash_flow
        if final_free_cash_flow is None:  # guarded by DCFInputs; keeps type narrowing explicit
            raise ValueError("final forecast requires free_cash_flow")

        terminal_value = self._terminal_value(inputs, final_free_cash_flow, wacc)
        final_discount_factor = forecast_values[-1].discount_factor
        present_value_terminal = terminal_value * final_discount_factor
        enterprise_value = (
            sum((period.present_value for period in forecast_values), Decimal("0"))
            + present_value_terminal
        )

        capital = inputs.capital_structure
        equity_value = (
            enterprise_value
            + capital.cash_and_equivalents
            - capital.total_debt
            - capital.non_controlling_interest
            - capital.preferred_stock
        )

        warnings: list[str] = []
        fair_value_per_share: Decimal | None = None
        if capital.diluted_shares_outstanding is None:
            warnings.append("fair value per share unavailable: diluted shares missing")
        elif equity_value < 0:
            warnings.append("fair value per share unavailable: equity value is negative")
        else:
            fair_value_per_share = equity_value / capital.diluted_shares_outstanding

        upside: Decimal | None = None
        if market_price is not None:
            if market_price == 0:
                warnings.append("upside unavailable: market price is zero")
            elif fair_value_per_share is None:
                warnings.append("upside unavailable: fair value per share unavailable")
            else:
                upside = fair_value_per_share / market_price - Decimal("1")

        return ValuationResult(
            identity=inputs.identity,
            model_type=ValuationModelType.discounted_cash_flow,
            model_version=inputs.model_version,
            enterprise_value=enterprise_value,
            equity_value=equity_value,
            fair_value_per_share=fair_value_per_share,
            market_price=market_price,
            upside=upside,
            forecast_values=forecast_values,
            terminal_value=terminal_value,
            present_value_terminal=present_value_terminal,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _discount_forecast_period(
        period_number: int,
        forecast: object,
        wacc: Decimal,
    ) -> DiscountedCashFlowPeriod:
        # ``forecast`` is intentionally narrowed via attributes to keep this helper private.
        fiscal_year = getattr(forecast, "fiscal_year")
        free_cash_flow = getattr(forecast, "free_cash_flow")
        if free_cash_flow is None:
            raise ValueError("every DCF forecast requires free_cash_flow")
        discount_factor = Decimal("1") / ((Decimal("1") + wacc) ** period_number)
        return DiscountedCashFlowPeriod(
            fiscal_year=fiscal_year,
            free_cash_flow=free_cash_flow,
            discount_factor=discount_factor,
            present_value=free_cash_flow * discount_factor,
        )

    @staticmethod
    def _terminal_value(
        inputs: DCFInputs,
        final_free_cash_flow: Decimal,
        wacc: Decimal,
    ) -> Decimal:
        assumptions = inputs.terminal_value
        if assumptions.method is TerminalValueMethod.perpetual_growth:
            growth = assumptions.perpetual_growth_rate
            if growth is None:  # guarded by TerminalValueAssumptions
                raise ValueError("perpetual_growth_rate is required")
            return final_free_cash_flow * (Decimal("1") + growth) / (wacc - growth)

        exit_multiple = assumptions.exit_multiple
        if exit_multiple is None:  # guarded by TerminalValueAssumptions
            raise ValueError("exit_multiple is required")
        return final_free_cash_flow * exit_multiple
