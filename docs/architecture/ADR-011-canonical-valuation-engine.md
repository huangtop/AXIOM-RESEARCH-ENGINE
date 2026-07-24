# ADR-011 — Canonical Valuation Engine

## Decision

V025 introduces `axiom_engine.valuation_engine` as a deterministic consumer of canonical financial, estimate, market, registry, and explicit assumption data. It never downloads data and never fabricates analyst estimates or valuation assumptions.

## Methods

- DCF using `operating_cash_flow - abs(capital_expenditures)` as an explicitly disclosed FCFF proxy.
- Forward P/E from canonical diluted EPS estimates.
- Forward P/S from canonical revenue estimates and shares.
- Forward EV/EBITDA only when canonical EBITDA estimates exist.
- Bear, base, and bull scenarios through explicit deltas in the assumption profile.

## Output

`data/valuation_data/{valuations,diagnostics,provenance,manifest}.json`

Partial valuation is valid when one or more methods complete. Missing data becomes diagnostics, not an uncaught exception. Confidence is deterministic and based on method completion, market price availability, and assumption provenance.
