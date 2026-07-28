# V031C.1.1 — Filing-aware Canonical Refresh

## Outcome

- Canonical Business Evidence resumed at filing offset 200 and now contains evidence for 280 companies.
- SEC financial refresh is driven by new filing accessions instead of depending on an incomplete earnings calendar.
- The current full Registry audit identifies 256 companies whose latest financial filing accession is not yet present in the available Companyfacts data.

## Refresh policy

- Poll lightweight SEC submissions metadata daily.
- Refresh a company's Companyfacts after a new 10-K, 10-Q, 20-F, 40-F, or XBRL 6-K accession is detected.
- Keep a 90-day TTL as a safety audit and stale-cache fallback, not as the primary event schedule.
- Treat Yahoo earnings-calendar dates as advisory only.
- Request market close data once per scheduled fetch date and deduplicate stored observations by symbol and market session date.
- Refresh Yahoo estimates on their existing 30-day pending/expired schedule.

## Verification

- 672 backend tests pass.
- No WordPress, PHP, CSS, or JavaScript frontend artifact is included.
