# V030.11.0 — Canonical Financial Bridge

Bridges SEC Financial Facts into a company-oriented canonical financial snapshot using the V030.10.4 identity map.

## Scope

- Validate every financial fact against canonical company identity.
- Normalize numeric values for JSON-safe downstream use.
- Preserve filing periods, forms, accession numbers, audit state and provenance.
- Group facts by company and expose a latest-per-metric convenience view without deleting history.
- Emit bridge diagnostics for unmapped, invalid and duplicate records.

TTM construction, freshness classification and cross-provider fallback are intentionally deferred to V030.11.1 and V030.11.2.

Known Universe coverage gaps remain diagnostic-only in strict mode; malformed rows and duplicate fact IDs remain strict failures.
