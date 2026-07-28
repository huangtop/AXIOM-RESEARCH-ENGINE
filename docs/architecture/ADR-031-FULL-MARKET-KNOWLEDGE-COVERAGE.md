# ADR-031 — Full-Market Knowledge and Valuation Coverage

Status: Accepted for V031

## Decision

The only Layer 1 product boundary is the complete canonical Population Registry. V031 derives one displayable valuation-card contract for every company in `data/universe/companies.json` and indexes every active security in `data/universe/securities.json`.

No fixed ticker cohort controls company existence, Knowledge projection, valuation eligibility, theme membership, or research depth. Small ticker sets may be used only as external migration and parity tests.

## Data flow

```text
Full Population Registry
          ↓
Canonical financial / market / estimate facts
          ↓
Rebuildable Knowledge metrics
          ↓
Seven-model eligibility
          ↓
Layer 1 valuation-card API
```

The seven stable model slots are DCF, Forward P/E, PEG, Forward P/S, EV/EBITDA, Forward P/B, and Milestone. Missing inputs produce `unavailable`, machine-readable reason codes, and missing-input lists. They never remove the company page and never trigger fabricated values.

## Research Universe boundary

Theme and sector membership will be inferred after Layer 1 from reproducible evidence such as business descriptions, filings, revenue segments, products, customers, suppliers, ETF holdings, and verified events. A policy engine will decide whether a company receives:

- news collection and filtering;
- ETF inclusion/removal monitoring;
- competitor and industry-chain analysis;
- causal event propagation and valuation-impact analysis.

The Research Universe is a generated, versioned output with evidence and scores, not a hand-maintained ticker list. Manual overrides, if any, must be sparse, provenance-bearing, reversible, and must never be required for normal operation.

## Causal evidence rule

A relationship such as “AAOI supplies NVDA” cannot enter the Knowledge graph from keyword co-occurrence. It requires an attributable source, relationship type, observation date, confidence, and evidence record. Order value and revenue contribution remain unknown unless explicitly disclosed or derived by a versioned formula with bounded assumptions. Valuation impact is downstream of the verified relationship and must expose its derivation.

## V031.1 evidence gate

Theme and sector inference accepts only canonical descriptions and classifications whose provenance IDs resolve in the provenance repository, or Knowledge relationships whose evidence IDs resolve to approved Canonical evidence. Company names and ticker symbols are display and lookup attributes, never classification evidence. The 300-company Research Universe limit is a maximum operational capacity, not a quota; an empty result is valid when the evidence layer is empty.
