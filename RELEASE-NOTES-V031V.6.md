# V031V.6 — Estimate Population and Evidence-Backed Multiple Policy

V031V.6 keeps the market scope fixed and begins real population of the five relative valuation models.

- Projects Yahoo provider observations into Canonical Forward EPS, EPS growth, Forward Revenue and explicitly labelled TTM EBITDA records.
- Builds Knowledge target multiples from ready historical medians when available.
- Until sufficient history exists, derives target multiples from analyst-consensus target price when analyst coverage and each required denominator are present.
- Forbids using the current spot multiple as a target multiple.
- Keeps Milestone unavailable unless a separate verified company-event case supplies probability and outcome values.
- Adds resumable `offset`/`limit` controls and US class-share symbol mapping to the Yahoo snapshot population command.

The first cache-backed checkpoint contains 220 companies and 654 Canonical observations. It creates 155 evidence-backed Knowledge policies. Across the normalized 5,876-company valuation scope, calculated coverage is now:

- DCF: 1,720
- Forward P/E: 101
- PEG: 54
- Forward P/S: 124
- EV/EBITDA: 77
- Forward P/B: 98
- Milestone: 0, by design

No value is emitted when analyst coverage, estimates, denominators or evidence are absent. No frontend files are included.
