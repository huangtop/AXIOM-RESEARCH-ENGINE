# V031E.1A — ETF Engine Source Contract and Cache

## Outcome

- Defines ETF-ENGINE-V2 as a read-only external provider over HTTPS.
- Validates provider manifest schema, timestamps, counts, markets, holdings structure, and normalized weight ranges before accepting an update.
- Stores validated provider data in immutable local snapshots and atomically advances a small state pointer only after the complete snapshot succeeds.
- Avoids provider requests while the 24-hour cache is fresh and avoids re-downloading holdings when the remote manifest is unchanged.
- Retains the last-known-good snapshot with an explicit stale-fallback diagnostic when a later fetch or contract validation fails.
- Does not consume valuation readiness and does not modify ETF-ENGINE-V2.

## Live contract verification

The first live read-only synchronization validated ETF-ENGINE-V2 schema `2.2` with:

- 158 ETFs
- 423 holding symbols
- 1,458 ETF-to-holding exposure records
- 1,326 overlap pairs
- 80 Taiwan ETFs and 78 US ETFs

The provider coverage is explicitly labeled `top_holdings_only`. Runtime cache files are intentionally ignored by Git so normal refreshes do not create data commits.

## Next boundary

V031E.1B will consume the validated cached snapshot and resolve holding symbols to AXIOM `security_id` and `company_id`, preserving ambiguous, unsupported-market, and unresolved records as diagnostics.
