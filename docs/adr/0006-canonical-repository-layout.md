# ADR-0006: Canonical Repository Layout

## Status
Accepted

## Decision
AXIOM canonical data is partitioned by responsibility. Market entities and listings live in `data/universe`; shared classification and valuation-profile taxonomies live in `data/taxonomy`. Other existing repositories (`valuation`, `research`, `industry`, `etf`, `impact`, and `ingestion`) remain independent.

`UniverseRepository` and `UniverseImporter` accept either the canonical data root or the legacy `data/universe` directory. Legacy compatibility is temporary migration support; new code should pass `data`.

## Canonical layout

```text
data/
  universe/
    companies.json
    securities.json
    valuation_profile_assignments.json
  taxonomy/
    classifications.json
    valuation_profile_catalog.json
  valuation/
  research/
  industry/
  etf/
  impact/
  ingestion/
```

## Consequences
Universe imports cannot overwrite taxonomy files. Official Universe migration can replace companies and securities while preserving manually curated classifications and valuation policies.
