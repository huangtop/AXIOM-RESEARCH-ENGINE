# ADR-019: Production Registry Import

## Decision
V028.0 introduces a production registry canonicalization boundary before all financial, estimate, market, valuation, research, and card workflows.

Raw company and security sources are converted into canonical `companies.json`, `securities.json`, and `provenance.json`. Company identity remains separate from a security, listing, exchange, or ticker.

## Guarantees
- deterministic company IDs when an official ID is absent;
- multiple securities and listings may map to one company;
- exactly zero or one primary listing is accepted with a warning for zero and an error for multiple;
- `(exchange, ticker)` collisions are errors;
- every security must link to an existing company;
- provenance references are validated;
- diagnostics and manifest outputs are machine-readable.

## Non-goals
V028.0 does not fetch external data, merge companies automatically, overwrite valuation logic, or modify the Production Orchestrator.
