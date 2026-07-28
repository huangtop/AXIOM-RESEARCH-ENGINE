# V031.1 — Theme / Sector Evidence Inference

V031.1 adds an evidence-driven Knowledge projection across the complete company Registry. It does not maintain a ticker cohort and does not infer themes from company names or symbols.

## Contract

- Canonical business descriptions and official classifications participate only when their provenance IDs resolve in the provenance repository.
- Industry exposures and graph edges participate only when their evidence IDs resolve to approved Canonical evidence.
- Theme and sector scores are reproducible from a versioned taxonomy policy.
- The Research Universe is dynamically ranked and capped at 300 companies; the cap is capacity policy, not a target to fill.
- News, ETF, and industry-chain analysis are enabled independently by evidence thresholds.
- Missing or rejected evidence is preserved as diagnostics rather than converted into a guessed classification.

## Current production-data baseline

The full 6,464-company population receives a result. The current canonical description and official-classification datasets are empty, and all 10 existing industry seed relationships lack evidence IDs. Consequently, zero companies are selected until the canonical population pipeline supplies verifiable evidence.

## Backend API

- `GET /v1/research-universe`
- `GET /v1/companies/{ticker}/research-policy`

No frontend files are part of this release.
