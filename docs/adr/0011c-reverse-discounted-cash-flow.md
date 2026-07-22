# ADR 0011C: Reverse Discounted Cash Flow

## Status

Accepted.

## Context

Commit-011B calculates value from explicit free-cash-flow forecasts. The valuation layer
also needs the inverse question: what constant explicit-period FCF growth rate is embedded
in the current market price when discount rates, terminal assumptions, and capital
structure are held fixed?

## Decision

Add immutable `ReverseDCFInputs` and `ReverseDCFResult` contracts plus
`ReverseDiscountedCashFlowEngine`.

The engine converts market capitalization to target enterprise value, compounds current
FCF at one constant rate across the explicit forecast period, delegates each candidate
valuation to `DiscountedCashFlowEngine`, and solves the market-implied growth rate by
bounded bisection. It supports perpetual-growth and exit-multiple terminal methods,
preserves `Decimal` precision, performs no presentation rounding, and exposes convergence,
iteration count, valuation error, and deterministic warnings.

Inputs require positive current FCF, market price, WACC, forecast length, and diluted
shares. Growth bounds must be ordered and greater than -100%. A target outside the values
spanned by the configured bounds fails explicitly rather than extrapolating.

## Consequences

Reverse DCF remains auditable and reuses the authoritative forward DCF implementation.
The solved variable is intentionally limited to a single constant FCF growth rate;
revenue/margin decomposition, multi-stage growth, and simultaneous assumption solving are
future extensions.
