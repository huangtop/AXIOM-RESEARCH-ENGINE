# V030.12.2 — Valuation Method Inputs

Transforms V030.12.1 eligibility decisions and V030.12.0 canonical valuation inputs into deterministic, method-specific calculation payloads.

## Added
- Seven method input contracts: Forward P/E, Trailing P/E, Price/Sales, EV/Sales, EV/EBITDA, FCF Yield, and DCF base inputs.
- Derived observable inputs such as current multiples, revenue per share, FCF per share, and FCF yield.
- Formula version identifiers and source-level provenance preservation.
- Blocked-method passthrough and invalid calculation diagnostics.

## Boundary
This release prepares calculation inputs only. It does not select fair multiples, forecast growth, calculate WACC, produce fair value, or aggregate valuation methods.
