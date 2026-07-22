# ADR 0011B: Discounted Cash Flow Engine

## Status

Accepted.

## Context

Commit-011A established immutable valuation inputs and a common result contract. The
project now requires a deterministic numerical engine that turns explicit free-cash-flow
forecasts into enterprise value, bridges enterprise value to equity value, and optionally
produces per-share value and market-price upside.

## Decision

Add `DiscountedCashFlowEngine` in `axiom_engine.dcf_engine`.

The engine:

- uses the WACC supplied by `DiscountRateAssumptions`;
- treats explicit forecasts as year-end cash flows and discounts period `n` by
  `1 / (1 + WACC) ** n`;
- supports both perpetual-growth and exit-multiple terminal values;
- defines the exit-multiple base as final-year free cash flow;
- discounts terminal value using the final explicit forecast period;
- bridges enterprise value to equity value by adding cash and subtracting debt,
  non-controlling interest, and preferred stock;
- computes fair value per diluted share only when shares are available and equity value
  is non-negative;
- computes upside only when market price is positive and fair value per share exists;
- preserves `Decimal` precision and performs no implicit rounding.

A non-positive WACC is rejected at calculation time. Missing optional outputs are
represented by `None` plus deterministic warning messages rather than fabricated values.

## Consequences

The resulting API is deterministic, auditable, and directly compatible with the immutable
models from Commit-011A. Forecast construction, scenario generation, reverse DCF, and
presentation-layer rounding remain outside this commit.
