# ADR 0004: Universe Import Framework

## Status
Accepted for Commit-004 validation.

## Context
AXIOM v0.7 needs to grow from hand-maintained seed JSON to thousands of companies. Direct editing of canonical JSON does not provide repeatable validation, conflict handling, dry-run inspection, or atomic writes.

## Decision
Introduce a format-neutral `UniverseImporter` that:

- accepts JSON bundles and row-oriented CSV files;
- validates every record through the existing Pydantic Universe models;
- resolves all staged references through `UniverseRepository` before writing;
- defaults to dry-run and merge mode;
- rejects conflicting IDs unless replacement is explicitly requested;
- writes the three mutable canonical datasets atomically;
- leaves classifications and the valuation profile catalog authoritative and read-only.

The framework is a data transport layer only. It does not infer classifications, themes, research levels, or valuation profiles.

## Consequences
Commit-005 and Commit-006 can focus on market-specific source adapters while producing the same import contract. Financial, news, industry-chain and reasoning data remain outside this boundary.
