# ADR-015 — 6000 Company Coverage Audit

## Status

Accepted for V027.0.

## Decision

AXIOM will measure production readiness before attempting bulk valuation generation. The audit reads canonical layer outputs without changing them and produces one company-level readiness record plus aggregate coverage metrics.

Readiness is classified as:

- `ready`: revenue, market price, shares outstanding, and valuation are present.
- `partial`: at least one downstream data layer is present, but one or more required inputs/results are missing.
- `blocked`: only registry identity is available.

Analyst estimates are measured but are not a hard requirement for readiness because later valuation fallback tiers must support companies without consensus estimates.

## Extensibility boundary

Future news and industry-chain systems must remain separate canonical layers:

- company registry: durable entity identity;
- financial, estimate, market, valuation: time-indexed observations/results;
- news: immutable event/source records linked to companies and topics;
- industry graph: versioned nodes and typed edges with provenance;
- reasoning: derived claims that cite event and graph record IDs.

News text and inferred relationships must not be written into company master records or valuation outputs. This keeps ingestion, corrections, graph evolution, and causal reasoning independently maintainable.

## Outputs

- `coverage_report.json`
- `coverage_failures.json`
- `company_readiness.json`
- `manifest.json`
