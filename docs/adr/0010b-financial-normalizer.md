# ADR 0010B: Financial Normalizer

## Status

Accepted.

## Context

The Financial Repository exposes canonical statements and selected analytical helpers. Downstream
valuation and research code needs a stable, immutable snapshot with plain `Decimal` values rather
than SEC observation metadata. Commit-010A introduced the normalized domain model but intentionally
did not connect it to the repository.

## Decision

Introduce `FinancialNormalizer` as a structural mapping layer between `FinancialRepository` and
`NormalizedFinancials`.

The normalizer:

- resolves the latest or requested fiscal year through the repository;
- preserves canonical company identity;
- maps every available statement value to `Decimal` while preserving missing values as `None`;
- derives the normalized period bounds from canonical observations;
- validates that monetary observations use one currency;
- leaves all analytical metrics empty in Commit-010B.

`FinancialRepository.normalize()` is a thin convenience delegate. The import is local to avoid a
module cycle between the repository and normalizer.

## Consequences

Consumers can now request a stable normalized snapshot without depending on SEC taxonomy,
observation provenance, or builder internals. Ratio calculation remains isolated for Commit-010C
and later work. Mixed monetary units fail explicitly rather than silently combining currencies.
