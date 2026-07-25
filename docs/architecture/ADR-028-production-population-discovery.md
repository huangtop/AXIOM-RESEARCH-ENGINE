# ADR-028 — Production Population Discovery

## Status
Accepted for V030.35.

## Decision
Financial, market, and estimate consumers must not select a source merely because a familiar path exists. V030.35 scans repository datasets, measures semantic evidence and linkage to the canonical 6464-company universe, ranks candidates, and writes a materialized population manifest.

Missing layers are explicit manifest states, not fabricated selections. Test, sample, onboarding, backup, and diagnostic paths are penalized. Generated outputs remain non-canonical build artifacts.

## Outputs
`data/generated/population_manifest/population_manifest.json`, `population_source_inventory.json`, and `population_discovery_report.json`.
