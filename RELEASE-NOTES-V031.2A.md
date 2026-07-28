# V031.2A — SEC Canonical Company Evidence Acquisition

V031.2A establishes a cache-first SEC EDGAR Submissions pipeline for every CIK-bearing company in the full Registry.

## Outputs

- raw SEC Submissions cache with content hashes and retrieval timestamps;
- authoritative SEC SIC code and label records, preserved under the `SEC_SIC` scheme;
- latest annual filing document manifest for 10-K, 20-F, and 40-F families;
- provenance records and explicit full-population coverage diagnostics.

The builder supports the SEC nightly submissions bulk ZIP, existing per-CIK cache files, and optional live per-CIK fallback. Cache is preferred over bulk, and bulk is preferred over live retrieval.

This release does not download Yahoo data, summarize filing text, infer company signals, assign themes, or maintain ticker membership. SIC remains a source classification and is not relabeled as an AXIOM sector.
