# AXIOM development history

This repository keeps architecture decisions in `docs/adr/` and `docs/architecture/`.
Detailed per-patch release notes were consolidated into this file to keep the
repository maintainable.

## Foundation (v0.3-v0.7)

- Established the market universe, canonical repository contracts, financial
  ingestion, valuation foundations, research services, and news integration.
- Legacy migration guides are no longer required by the current production
  pipeline.

## Production data and valuation (v0.15-v0.30)

- Separated Registry, Canonical, Knowledge, and Valuation responsibilities.
- Added SEC company identity and financial facts, market snapshots, estimates,
  valuation eligibility, fallback policy, batch valuation, and quality signals.
- Expanded from the initial validation cohort toward the full US-market company
  population. Cohorts remain verification scopes, not manually maintained product
  universes.
- The valuation layer supports DCF, reverse DCF, forward P/E, PEG, forward P/S,
  EV/EBITDA, forward P/B, and evidence-gated milestone scenarios. A model may
  truthfully report unavailable when required evidence is missing.

## Full-market knowledge and research eligibility (v0.31)

- Normalized company and security identity so warrants, units, preferred shares,
  ADRs, and operating companies are not treated as interchangeable instruments.
- Added resumable SEC companyfacts, filing evidence, Yahoo previous-close, and
  estimate population pipelines with explicit source and freshness metadata.
- Company classification is inferred from verifiable business evidence through
  ontology and rules. No ticker membership list is the classification source.
- Knowledge projections support multidimensional Theme, Sector, Cluster,
  Technology, Product, End Market, and Supply-chain Role inference.
- Research eligibility independently determines news screening, ETF tracking,
  supply-chain analysis, and deep research; it does not depend on valuation
  readiness.

## ETF integration (v0.31E)

- AXIOM consumes ETF-ENGINE-V2 through a read-only source contract and identity
  bridge; ETF business logic remains in the external engine.
- Canonical ETF exposure, holding-change events, company-card projection, and a
  unified ETF detail API are available without writing valuation data back to the
  ETF repository.
- Holding additions, removals, and weight changes require at least two genuine
  source snapshots. Missing provider dates remain null rather than invented.

## Repository policy

- This repository contains backend data contracts, pipelines, APIs, tests, and
  architectural documentation only.
- Private WordPress/PHP/CSS/JavaScript frontend implementations are maintained
  outside Git and must not be committed.
- Generated caches are committed only when they are intentional production or
  reproducibility artifacts covered by repository policy.

