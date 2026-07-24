# ADR-010 — Real-100 Estimate Provider Adapter and Production UX

## Decision

V024.1 keeps analyst consensus separate from internally derived assumptions and introduces a vendor-neutral adapter boundary before the canonical V018 estimate layer.

Supported adapter identifiers are `auto`, `canonical`, `generic`, `fmp`, `finnhub`, `polygon`, `yahoo`, and `alpha_vantage`. These identifiers normalize common field aliases; they do not imply that AXIOM fabricates, downloads, or licenses provider data.

CSV sources may provide provider metadata through CLI options. JSON sources may provide `provider_id`, `provider_name`, and `as_of_date` in the envelope. Canonical output always retains provider provenance.

Blank generated template rows are skipped. A completely blank template returns `input_status=empty_template`, `acceptance_passed=false`, and no canonical estimates. Partially populated invalid rows remain errors.

Production acceptance requires at least 90 covered registry companies and at least 80 companies for each required metric: revenue, net income, and diluted EPS.

## CLI behavior

`--compact` suppresses the large per-company missing metric map while preserving coverage and summary diagnostics. A write operation that does not pass acceptance exits with code 2.

When piping output through `tee`, validation must use `set -o pipefail` or `${PIPESTATUS[0]}` because `$?` otherwise reports the exit status of `tee`.
