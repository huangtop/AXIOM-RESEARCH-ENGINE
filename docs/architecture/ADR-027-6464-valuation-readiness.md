# ADR-027 — V030.3 6464 Valuation Readiness

## Decision

V030.3 materializes a derived readiness record for every company in the canonical `data/universe` population. It does not calculate fair value and does not modify company, financial, market, estimate, ontology, or valuation canonical layers.

A company is `ready` when at least two valuation models have the minimum inputs, `partial` when exactly one model is eligible, and `blocked` when none are eligible. Missing inputs are normal production states and must be represented by model-specific reason codes rather than exceptions.

## Model capability checks

The scanner evaluates Forward P/E, PEG, Forward P/S, EV/EBITDA, Forward P/B, and Milestone capability using canonical production financial, market, and estimate artifacts. It discovers the current repository paths in a fixed priority order and records the selected paths in `readiness_summary.json`.

## Non-goals

No news, ontology inference, graph traversal, exposure inference, industry chain, theme membership, ticker list maintenance, valuation calculation, or frontend rendering is introduced by this release.
