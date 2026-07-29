# V031E.1C — Canonical ETF Exposure and Coverage Audit

## Outcome

- Projects validated ETF-ENGINE-V2 Top Holdings into Canonical ETF Exposure records only after V031E.1B resolves an active common-equity security and company identity.
- Preserves portfolio weight as a decimal ratio and adds a separately labeled percentage representation.
- Carries provider snapshot ID, generation time, holdings SHA-256, acquisition mode, and provenance into every exposure.
- Leaves provider `as_of` unavailable rather than substituting the retrieval or manifest date.
- Retains every unresolved source exposure in the coverage audit instead of dropping or guessing it.
- Does not consume valuation readiness.

## Current coverage

- Provider manifest ETFs: 158
- ETFs represented in the current holdings index: 150
- Source holding symbols: 423
- Source ETF-to-holding exposure records: 1,458
- Canonical ETF Exposure records: 715
- Unresolved exposure records retained by audit: 743
- Canonical AXIOM companies: 224
- Canonical ETFs with at least one resolved company: 85
- Canonical exposure ratio: 49.0398%
- Invalid portfolio weights: 0
- Source records without provider `as_of`: 1,458

Of the Canonical records, 581 originate from US ETFs and 134 from Taiwan ETFs holding securities already represented by AXIOM company identity. Taiwan and other foreign holdings without an AXIOM Registry company remain outside Canonical exposure and are reported explicitly.

## Interpretation boundary

`portfolio_weight_percent` means the holding's share of that ETF portfolio. It is not the ETF's ownership percentage of the company. Because the upstream coverage is `top_holdings_only` and has no dated history, this version does not infer additions, removals, trading activity, or weight-change events.
