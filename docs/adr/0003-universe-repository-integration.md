# ADR 0003: Universe Repository Integration

## Status
Accepted for Commit-003 validation.

## Context
Commit-001 introduced strict Market Universe records and seed data. Commit-002 introduced the valuation profile catalog. Callers still had to load and join multiple JSON files themselves, which would duplicate lookup and integrity logic before the planned 8,000+ company import.

## Decision
Introduce a read-only `UniverseRepository` as the first-class access boundary for Market Universe data.

The repository:

- loads Company, Security, Classification, profile assignment, and profile catalog records;
- validates cross-file references at construction time;
- resolves a company from company ID, security ID, or ticker;
- returns a `ResolvedCompany` aggregate;
- exposes research level, themes, business-model IDs, primary profile, and primary valuation models without coupling to the valuation execution engine.

## Boundaries
This commit does not add import pipelines, financial facts, news, industry-chain reasoning, knowledge graphs, or valuation calculation behavior.

## Consequences
Future import commits can increase Universe size without changing caller-facing lookup logic. Financial, News, and later graph repositories can reference the same stable company and security IDs.
