# V030.10.4.1 — Yahoo Cache Discovery Fix

- Fixes Identity Mapping reporting zero Yahoo cached symbols when per-symbol cache files exist but the merged canonical snapshot is absent or empty.
- Identity now unions symbols from the canonical Yahoo snapshot and `data/generated/provider_cache/yahoo/company_snapshot/*.json`.
- Adds separate canonical and per-symbol cache counters for diagnostics.
- Invalid per-symbol JSON does not stop the build; the filename is used as a safe symbol fallback.
