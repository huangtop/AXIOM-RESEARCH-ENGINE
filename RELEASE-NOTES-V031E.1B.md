# V031E.1B — ETF Security Identity Bridge

## Outcome

- Resolves ETF-ENGINE-V2 holding symbols to AXIOM active common-equity `security_id` and `company_id` records.
- Uses deterministic exact ticker, verified Registry alias, and class-share punctuation rules without company-name matching.
- Reads V031V.2 instrument normalization so warrants, units, rights, and preferred shares cannot become company ETF exposures.
- Preserves ambiguous, unsupported-market, and unresolved holdings as diagnostics instead of guessing.
- Carries the source ETF snapshot ID and holdings SHA-256 into the bridge output.
- Does not consume valuation readiness.

## Current bridge coverage

- Source holding symbols: 423
- Resolved symbols: 225
- Resolved AXIOM companies: 224
- Exact active common-equity matches: 223
- Deterministic class-share punctuation aliases: 2
- Unsupported foreign-market symbols: 188
- Unresolved symbols: 10
- Resolved ETF-to-holding exposure records: 715 of 1,458

The unsupported group primarily consists of Taiwan and other non-US securities that are present in ETF-ENGINE-V2 but not yet represented in the current AXIOM Registry. They remain explicit diagnostics and are not converted into ticker-only company identities.

## Unresolved boundary

The remaining bare symbols include provider-reported funds, cash-like instruments, units, and foreign numeric symbols without sufficient market identity. V031E.1B does not infer their identity from display names. Verified historical ticker aliases will be consumed automatically when they become available in Registry security metadata.
