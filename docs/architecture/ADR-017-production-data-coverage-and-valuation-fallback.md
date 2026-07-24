# ADR-017: Production Data Coverage and Valuation Fallback

## Status
Accepted for V027.2.

## Decision
Valuation method selection is separated from the canonical valuation engine. A deterministic strategy selector evaluates canonical financial, estimate, and market observations and emits a versioned strategy record.

Priority is Tier A forward estimates, Tier B historical cash-flow proxy, Tier C revenue multiple, Tier D book value, then Tier X unavailable. Every fallback records its reason, missing inputs, confidence, and source record IDs.

## Boundaries
V027.2 selects and computes transparent fallback reference values. It does not fabricate missing source data, mutate canonical inputs, or claim that simplified multiples are equivalent to a full DCF. The existing V025 valuation engine remains unchanged.
