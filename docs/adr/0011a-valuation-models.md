# ADR 0011A: Valuation model contracts

## Status

Accepted.

## Context

The normalized financial layer now exposes stable, Decimal-preserving financial data. The valuation layer needs equally stable input and output contracts before calculation engines are introduced. Existing persistence-oriented Pydantic models remain valid, but they represent catalog, scenario, execution, and snapshot records rather than the in-memory numerical contract of a DCF engine.

## Decision

Add `axiom_engine.valuation_models` with immutable, slotted dataclasses for:

- valuation identity and market context;
- explicit forecast periods;
- CAPM and WACC assumptions;
- terminal-value assumptions;
- capital structure and enterprise-to-equity bridge;
- DCF input contract;
- discounted forecast-period output;
- common valuation result.

All monetary and rate values use `Decimal`. Models validate structural invariants but do not round values. Serialization converts Decimal values to strings and dates/enums to JSON-compatible values.

The existing `axiom_engine.models.valuation` persistence schema is not modified in this commit. A future engine may translate `ValuationResult` into the persisted `ValuationSnapshot` schema.

## Consequences

Commit 011B can implement DCF calculations without redefining model boundaries. Reverse DCF and relative multiples can reuse identity and result contracts. Incorrect terminal-method combinations, invalid capital weights, unordered forecasts, absent free cash flow, and perpetual growth at or above WACC fail at construction time.
