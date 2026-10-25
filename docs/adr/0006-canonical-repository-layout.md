# ADR-0006: Canonical Repository Layout

## Status
Accepted

## Decision
AXIOM canonical data is partitioned by responsibility. Market entities and listings live in `data/universe`. Classification and valuation data are maintained by their own pipelines. Other existing repositories (`valuation`, `research`, `industry`, `etf`, `impact`, and `ingestion`) remain independent.

`UniverseRepository` and `UniverseImporter` accept either the canonical data root or the legacy `data/universe` directory. Legacy compatibility is temporary migration support; new code should pass `data`.

## Canonical layout

```text
data/
  universe/
    companies.json
    securities.json
  valuation/
  research/
  industry/
  etf/
  impact/
  ingestion/
```

## Consequences
Universe imports write only companies and securities. Official Universe migration can replace both files while enforcing company, security, ticker and primary-listing integrity.
