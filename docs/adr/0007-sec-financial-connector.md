# ADR-0007: SEC Financial Connector

## Status

Accepted

## Context

AXIOM v0.8 requires a reproducible official source for company financial facts before a
normalized Financial Repository can be introduced. The SEC XBRL Company Facts endpoint
provides JSON documents keyed by taxonomy, concept, unit, and filing observation.

## Decision

Introduce a connector that:

- downloads `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`;
- requires an identifying User-Agent;
- applies conservative client-side pacing and bounded retries for transient failures;
- supports gzip and deflate responses;
- validates the structural contract and requested CIK;
- optionally stores raw, atomic JSON cache snapshots;
- exposes immutable typed read models while preserving the complete raw payload.

The connector deliberately does not map SEC concepts into AXIOM `FinancialFact` records.
Concept selection, period normalization, duplicate filing resolution, and statement
construction belong to subsequent v0.8 commits.

## Consequences

The raw source boundary is now explicit and testable. Downstream code can work from stable
snapshots without coupling normalization rules to HTTP behavior. Consumers must supply a
responsible SEC User-Agent and should use caching for repeated access.
