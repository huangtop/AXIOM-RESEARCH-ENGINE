# V030.12.0 — Valuation Input Snapshot

Introduces the first canonical valuation-engine input contract. It requires a passing Bridge QA report, joins SEC-first routed financial metrics with completed-session previous closes, preserves field-level source/confidence/freshness metadata, emits capability flags, and classifies each company as ready, financial_only, market_only, or insufficient. Missing market coverage remains diagnostic; invalid market rows fail strict mode.
