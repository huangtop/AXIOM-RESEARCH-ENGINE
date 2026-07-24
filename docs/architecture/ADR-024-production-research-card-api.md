# ADR-024 — V029.0 Production Research Card API

## Decision

Create a read-only projection layer over the V028.4 full production build. One stable JSON card is generated per canonical company, with lookup indexes by `company_id` and ticker symbol.

## Input

- `registry/companies.json`
- `registry/securities.json`
- `financial/financial_facts.json`
- `market/market_snapshots.json`
- `estimate/consensus_estimates.json`

## Output

- `cards/<symbol>.json`
- `research_card_index.json`
- `research_card_manifest.json`

## Contract

The card exposes company identity, primary security, market history/latest snapshot, normalized financial facts, consensus estimates, and coverage/valuation-readiness metadata. It is read-only and does not fetch providers or execute valuation models.

## Scale boundary

V029.0 can project any number of companies already present in V028.4. It does not populate 6,000 companies. Population/backfill and scheduled refresh are separate production ingestion milestones.
