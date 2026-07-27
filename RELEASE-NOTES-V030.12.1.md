# V030.12.1 — Valuation Method Eligibility

Introduces a deterministic eligibility layer between the canonical valuation-input snapshot and valuation execution.

## Methods

- Forward P/E
- Trailing P/E
- Price-to-Sales
- EV/Sales
- EV/EBITDA
- FCF Yield
- DCF data eligibility

## Policy

- Missing or non-positive denominator inputs block the affected method only.
- Negative free cash flow remains valid for FCF Yield, but blocks DCF eligibility.
- Stale inputs remain eligible and lower method confidence.
- Every method emits status, confidence, reason, missing inputs, invalid inputs, stale inputs, and selected provenance-bearing inputs.
- No fair value or multiple is calculated in this release.
