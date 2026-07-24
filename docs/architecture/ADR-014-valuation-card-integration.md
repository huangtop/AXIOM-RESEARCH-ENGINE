# ADR-014: Valuation Card Integration

## Decision

The valuation card consumes only the V026.0 canonical `company_research.json` through a deterministic view-model adapter.

## Data flow

`company_research.json` → `valuation_card.core` → `/v1/research/valuation-card` → WordPress valuation card.

The frontend must not call providers, recompute valuation, or read the legacy valuation payload. Seven peer-level tabs are retained: Overview, Company Analysis, Industry Map, Research Notes, Valuation, Analyst Growth Ranking, and Related News. Unsupported sections expose honest adapter states instead of fabricated content.
