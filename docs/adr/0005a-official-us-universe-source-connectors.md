# ADR-0005A: Official US Universe source connectors

## Status
Accepted for Commit-005A validation.

## Decision
AXIOM will acquire the US listing universe from official, reproducible sources before transforming records into canonical Universe entities.

The source layer uses:

- Nasdaq Trader `nasdaqlisted.txt` for Nasdaq-listed securities.
- Nasdaq Trader `otherlisted.txt` for NYSE and NYSE American securities.
- SEC `company_tickers.json` for CIK and registrant-name enrichment.

The connector filters ETFs and test issues and emits a deterministic source snapshot. It does not assign classifications, research levels, valuation profiles, company IDs, or security IDs. Those transformations belong to Commit-005B.

## Consequences

- Source acquisition can be rerun and audited.
- Tests do not require network access.
- Official formats are isolated behind parsers.
- A descriptive user agent is mandatory.
- Missing SEC enrichment is retained as `null`, not guessed.
