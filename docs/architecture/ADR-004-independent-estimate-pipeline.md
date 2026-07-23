# ADR-004: Independent Estimate Pipeline

## Decision

Analyst estimates and forward assumptions are stored in an independent canonical bundle. They reference Company Registry IDs and provenance records, but do not contain market prices or valuation outputs.

Reported financial facts remain owned by V017. Analyst estimates represent externally sourced forward-period observations. Forward assumptions represent explicit, reviewable inputs with lifecycle status.

## Hard boundaries

- No `current_price`, `fair_value`, `intrinsic_value`, or valuation result.
- No legacy `research_report.json`, yfinance, classification, theme membership, or exposure.
- No valuation calculation in V018.
- Provider-specific payloads must be normalized before entering this layer.
- Dry-run is the default; writing requires `--write`.
