# ADR-008: Real 100 Company Registry Builder

V022 resolves the fixed V020 cohort against the SEC `company_tickers_exchange.json` identity table and writes V015-compatible canonical Company, Security and Provenance records.

## Decisions

- CIK is the stable company identity component.
- A security remains separate from its company and records the SEC-reported exchange and cohort ticker.
- The builder is dry-run by default and refuses to write if any cohort member is unresolved.
- A downloaded SEC payload can be supplied for reproducible and offline runs.
- No financial facts, estimates, prices, classifications, exposures or valuation results are created.
