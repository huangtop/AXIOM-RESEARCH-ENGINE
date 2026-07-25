# AXIOM V030.3 — 6464 Valuation Readiness

This release adds a non-destructive readiness scanner and validator for the full canonical company universe.

Outputs are written only when `--write` is supplied:

- `data/generated/valuation_readiness/company_readiness.json`
- `data/generated/valuation_readiness/readiness_summary.json`
- `data/generated/valuation_readiness/readiness_diagnostics.json`
- `data/generated/valuation_readiness/readiness_manifest.json`

The release does not build valuation cards and does not introduce legacy classification, `structure.json`, news, graph, exposure, or valuation policy dependencies.
