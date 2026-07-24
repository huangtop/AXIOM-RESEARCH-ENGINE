# ADR-021: Production Market Import

## Status
Accepted for V028.2.

## Decision
Introduce an isolated `production_market` import layer that converts provider quote exports into canonical point-in-time market snapshots.

The canonical link is `security_id`; `company_id` is retained and must agree with the V028.0 registry. The importer does not perform network access and does not replace the existing Yahoo adapter. Provider adapters may write the source files consumed by this layer.

## Invariants
- Every snapshot references a registered security and company.
- Security ownership and company linkage must agree.
- `observed_at` is timezone-aware and normalized to UTC.
- Decimal values are serialized as strings.
- Price and share fields enforce their domain constraints.
- Snapshot identity is deterministic from security, provider, and observation time.
- Provenance references are validated.
- Duplicate point-in-time snapshots are rejected.

## Outputs
`market_snapshots.json`, `provenance.json`, `market_diagnostics.json`, and `market_manifest.json`.
