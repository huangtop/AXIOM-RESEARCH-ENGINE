# V030.10.2 — Yahoo Company Snapshot Provider

- Adds cache-first company, market, financial and analyst snapshot collection.
- Fresh per-symbol cache is checked before any Yahoo request.
- Default cache TTL is 30 days; `--force` is available for manual repair.
- Emits one canonical aggregate file for later valuation input routing.
- One failed symbol does not abort the remaining batch.
