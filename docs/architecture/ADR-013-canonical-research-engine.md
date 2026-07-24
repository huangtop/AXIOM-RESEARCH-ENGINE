# ADR-013 — Canonical Research Engine

## Decision

Introduce a deterministic research assembly layer that consumes only Company Registry, Financial Facts, Analyst Estimates, Market Observations, and Valuation Results.

The engine does not call providers, perform valuation, or generate investment recommendations. It selects current canonical records, assembles summaries, calculates transparent completeness confidence, preserves source record IDs, and emits diagnostics for absent layers.

## Outputs

`data/research_data/company_research.json`, `diagnostics.json`, `provenance.json`, and `manifest.json`.

## Consequences

Research cards, APIs, and report generators can share one stable canonical bundle without duplicating cross-layer joins or coupling presentation code to provider formats.

## V026.0 Hotfix1 — Research Quality Diagnostics

Research status and confidence must reflect upstream quality rather than record presence alone.

- Valuation scenarios score by status: `completed=1.0`, `partial=0.5`, `unavailable=0.0`.
- Any non-completed valuation scenario makes the research bundle `partial`.
- Financial diluted shares and market shares are compared; a difference greater than 10% emits `shares_outstanding_mismatch`.
- A material shares mismatch applies a `-10` quality penalty while preserving the original component scores.
- Diagnostics remain warnings, so a structurally valid partial bundle can still pass canonical validation.
