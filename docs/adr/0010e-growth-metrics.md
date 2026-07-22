# ADR 0010E: Year-over-Year Growth Metrics

## Status

Accepted

## Context

The normalized financial snapshot already exposes profitability, efficiency,
liquidity, and leverage. Valuation and research workflows also need a compact,
deterministic view of fundamental growth.

## Decision

`NormalizedFinancials` gains an immutable `GrowthMetrics` value object with:

- revenue growth
- net-income growth
- diluted-EPS growth
- free-cash-flow growth

Each metric compares the selected fiscal year with the nearest older available
fiscal year:

`(current - prior) / prior`

The normalizer preserves `Decimal` precision and does not round. A metric is
`None` when either observation is missing, units differ, no older period is
available, or the prior value is zero or negative. Negative and zero bases are
excluded because conventional percentage growth is not economically stable or
comparable across a loss-to-profit transition.

Metrics remain independently available: one missing input does not suppress the
other growth calculations.

## Consequences

The normalized snapshot now supplies directly consumable growth inputs for
valuation and research scoring. Multi-year CAGR, TTM, and quarterly growth stay
outside this commit.
