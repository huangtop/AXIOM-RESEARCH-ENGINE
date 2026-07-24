# ADR-020 — Production Financial Import

## Status
Accepted for V028.1.

## Decision
Introduce an isolated `production_financial` ingestion boundary between external financial providers and AXIOM canonical valuation inputs.

The importer accepts canonical fact rows, links every row to the V028.0 `company_id`, normalizes decimal and date representations, preserves field-level provenance, and writes an immutable dataset plus diagnostics and manifest.

## Canonical fact identity
A fact is uniquely identified by:

`company_id + concept + fiscal_year + fiscal_period + period_end + unit + currency`

Duplicate natural keys are validation errors. Provider-specific taxonomy names remain in `source_concept`; AXIOM concepts remain in `concept`.

## Non-goals
V028.1 does not fetch SEC data, calculate ratios, restate filings, select valuation models, or overwrite the legacy financial repository. Provider adapters may feed this boundary later.
