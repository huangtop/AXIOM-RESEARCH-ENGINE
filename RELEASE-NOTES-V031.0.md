# V031.0 — Full-Market Knowledge Coverage Foundation

V031.0 makes the 6,464-company Population Registry the sole Layer 1 product boundary.

## Delivered

- One backend valuation-card contract per canonical company.
- Indexing for all 7,451 securities, without a maintained ticker cohort.
- Canonical financial, market, and estimate discovery.
- Rebuildable trailing EPS and period-aligned free cash flow Knowledge metrics.
- Stable seven-model eligibility with explicit missing-input reason codes.
- Read-only full-market company list and single-company valuation-card APIs.
- No frontend, PHP, CSS, or JavaScript changes.

## Current measured coverage

- Companies: 6,464
- Securities: 7,451
- Companies with canonical financial records: 99
- Companies with cached canonical market close: 3
- Companies with production estimates: 0
- DCF eligible: 2
- Other six models eligible: 0

These numbers are diagnostics. V031 does not manufacture values to improve them.

## API

- `GET /v1/companies`
- `GET /v1/companies/{ticker}/valuation-card`

Every known company remains displayable even when all valuation models are unavailable.
