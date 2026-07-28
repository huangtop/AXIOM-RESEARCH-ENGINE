# V031V.5 — Seven-Model Fair-Value Calculation

V031V.5 pauses population growth and changes the valuation-card contract from model eligibility to actual fair-value calculation.

- Implements DCF, Forward P/E, PEG, Forward P/S, EV/EBITDA, Forward P/B and probability-weighted Milestone formulas.
- DCF consumes Canonical FCF, cash, debt and diluted shares plus the versioned DCF policy. It does not require market price.
- Relative and milestone models consume Canonical estimates plus evidence-backed Knowledge assumptions. Missing assumptions remain unavailable.
- Every model returns calculation status, fair value, formula version, assumption source and explicit missing inputs.
- The unified fair value averages only successfully calculated models and declares its aggregation version.
- No company-specific assumptions are seeded in this release. `valuation_assumptions.json` is intentionally empty until evidence population exists.

Offline audit over the normalized 5,876-company scope calculates DCF for 1,720 companies. The other six model counts remain zero because the estimate layer and evidence-backed target assumptions have not yet been populated. No value is synthesized to increase coverage.

No frontend files are included.
