# V031C.1 — Refresh Policy and Canonical Business Evidence Continuation

V031C.1 starts the classification mainline while estimate population remains independently resumable.

Refresh semantics are now explicit and tested:

- Market closes are fetched once per scheduled fetch date and stored idempotently by symbol and completed session date.
- Yahoo company estimates use a 30-day TTL and refresh only pending or expired symbols.
- SEC Companyfacts use a 90-day TTL. A stale cached fact remains an explicit fallback only when a newer bulk archive is not available.

Canonical company evidence status:

- SEC submissions available: 5,904 companies.
- Official SEC SIC classifications: 5,505 companies.
- Annual filing manifests: 5,360 companies.
- Extracted filing Business sections: 188 companies after the first resumable continuation batch.

The Business-section writer now merges batches by stable evidence identity instead of overwriting prior results. This makes the remaining filing population safely resumable. Classification, Research Universe selection, news eligibility, ETF eligibility and supply-chain eligibility remain downstream inference outputs; no ticker membership list is introduced.

No frontend files or raw SEC filing caches are included.
