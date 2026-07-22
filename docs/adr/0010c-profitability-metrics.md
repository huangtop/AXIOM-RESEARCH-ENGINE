# ADR 0010C: Profitability metrics in the normalization layer

## Status

Accepted.

## Context

Commit-010B maps canonical statements into `NormalizedFinancials` but leaves all
analytical metrics empty. The first analytical increment should be small,
deterministic, and depend only on values already present in one fiscal snapshot.

## Decision

`FinancialNormalizer` calculates four profitability ratios:

- gross margin = gross profit / revenue
- operating margin = operating income / revenue
- net margin = net income / revenue
- free-cash-flow margin = free cash flow / revenue

Ratios are represented as `Decimal` fractions. For example, `Decimal("0.25")`
means 25 percent. The normalizer does not quantize or round results.

A ratio is `None` when its numerator is missing, revenue is missing, or revenue
is zero. One unavailable metric does not suppress the other profitability
metrics.

## Consequences

- Profitability analysis becomes available without changing repository or
  statement-builder responsibilities.
- Consumers retain exact decimal arithmetic and choose presentation rounding.
- Undefined ratios are represented explicitly rather than raising division
  errors or inventing sentinel values.
- Efficiency, liquidity, and leverage metrics remain deferred to Commit-010D.
