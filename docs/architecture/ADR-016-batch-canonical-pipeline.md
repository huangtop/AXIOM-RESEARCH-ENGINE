# ADR-016 — Batch Canonical Pipeline

## Status
Accepted for V027.1.

## Decision
The production pipeline processes each company in an isolated workspace and merges only successful canonical research bundles into shared output datasets. The pipeline records deterministic input fingerprints, per-company state, diagnostics, and a batch manifest.

## Guarantees
- One company failure does not abort the remaining batch.
- `--resume` reuses a completed company only when its input fingerprint is unchanged.
- `--retry-failed` targets failed companies from the previous state.
- Canonical upstream files are read-only.
- Shared research and valuation-card outputs are rebuilt atomically from successful company workspaces.

## Non-goals
V027.1 does not fetch missing provider data and does not introduce fallback valuation methods. Those remain separate production concerns.
