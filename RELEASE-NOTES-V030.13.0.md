# V030.13.0 — Multiple Valuation Engine

Introduces the valuation engine foundation between normalized method inputs and future fair-value assumption engines.

## Contract

- Promotes every `prepared` method to a normalized `calculated` engine payload.
- Preserves raw inputs, provider provenance, confidence, stale-input attribution, and source formula version.
- Emits engine-specific formula versions and observable metrics.
- Carries blocked methods without calculations.
- Does **not** relabel current market price as fair value.
- Does **not** introduce historical multiples, peer targets, WACC, growth assumptions, target prices, or method weights.

## Outputs

- `data/generated/valuation_engine/valuation_snapshot.json`
- `data/generated/valuation_engine/valuation_engine_diagnostic.json`
