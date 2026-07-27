# V030.10.3 — Yahoo Provider Stabilization

- Adds endpoint-isolated Yahoo collection with `info` → `get_info()` fallback.
- Adds field-level fallback for company name, market cap, shares, forward EPS, TTM revenue and forward revenue diagnostics.
- Missing optional fields no longer fail an entire company snapshot.
- Adds JSON-safe serialization for Decimal, datetime/date, numpy-like scalar values and pandas-like timestamps.
- Adds merged provider diagnostics at `data/generated/provider_cache/yahoo/provider_diagnostic.json`.
- Adds append-only provider exception logging at `data/generated/provider_cache/yahoo/provider_errors.log`.
- Preserves cache-first behavior and existing V030.10.2 snapshot fields.
- Upgrades canonical aggregate schema to `yahoo-company-snapshot.v030.10.3`.
