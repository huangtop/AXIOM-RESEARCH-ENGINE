# Incremental browser publication

The publication build writes `data/generated/publication_gate/manifest.json` and one
content-addressed JSON shard per company under `companies/`. The manifest is the only
resource clients poll. Its `release_id` changes only when company content changes, and
`changed_company_ids` reports the delta from the previous build.

Serve the manifest with `Cache-Control: public, max-age=60, must-revalidate`; serve company
shards with `Cache-Control: public, max-age=31536000, immutable`. The WSGI API exposes these
at `/v1/publication/manifest.json` and `/v1/publication/companies/<hashed-file>` and supports
`ETag` / `If-None-Match` with `304 Not Modified`.

`clients/axiom-incremental-cache.js` is a browser Cache Storage client. Call
`refreshManifest()` at application start, then `company("NVDA")` on demand. It downloads only
the selected company's current hash shard and removes superseded cached shards.

The build prunes unreferenced hash files after the new release is complete, so repository and
deployment size do not grow once per release.
