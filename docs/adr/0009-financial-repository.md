# ADR-0009: Financial Repository

## Status

Accepted

## Context

The SEC Company Facts connector and Financial Statement Builder produce canonical annual
financial statements, but callers still need to manage statement collections, select fiscal
years, and repeat common calculations. This couples analysis code to ingestion details and
makes metric behavior inconsistent.

## Decision

Introduce `FinancialRepository` as a read-only query and analysis layer over canonical
`FinancialStatements`.

The repository:

- indexes companies by caller-supplied identifier and normalized CIK;
- stores annual statements newest first;
- selects the latest fiscal year when no year is supplied;
- exposes typed Income Statement, Balance Sheet, and Cash Flow queries;
- provides revenue history and Free Cash Flow accessors;
- calculates Net Margin and Return on Equity using `Decimal` values;
- builds multi-year repositories directly from SEC Company Facts payloads.

Ratios are decimal fractions rather than percentages. Net Margin is Net Income divided by
Revenue. ROE uses average current and prior-year Shareholders' Equity when both years are
available; otherwise it uses current-year equity.

## Consequences

Analysis and valuation modules can query stable canonical financial data without knowing SEC
concept aliases or observation-selection rules. Missing inputs produce `None` for derived
metrics, while missing companies and fiscal years raise explicit repository exceptions.

The repository remains in-memory for this commit. Persistence, caching, quarterly statements,
and additional ratios are deferred to later commits.
