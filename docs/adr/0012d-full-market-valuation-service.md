# ADR 0012D: Full Market Valuation Service

## Status

Accepted.

## Context

Market retrieval, model eligibility and valuation engines existed as separate units. A caller still had to fetch a quote, reconcile quote fields with research inputs, decide which models could run and handle failures consistently.

## Decision

Add `FullMarketValuationService` as the orchestration boundary. It:

- fetches a provider-neutral `MarketSnapshot` for any requested symbol;
- validates symbol identity and fails closed on provider mismatches;
- enriches market-linked fields such as price, shares and forward EPS without manufacturing research assumptions;
- evaluates all models with `ModelEligibilityEngine`;
- executes supplied, runnable models independently through `IntrinsicValueEngine`;
- records each model as `executed`, `skipped` or `failed`;
- isolates model failures so one calculation cannot discard other results;
- returns the snapshot, full eligibility report, execution records and degradation warnings.

The service does not average model outputs or invent missing forecasts, peer multiples, discount rates or milestone probabilities.

## Consequences

Application layers receive one deterministic full-market valuation entry point while providers and model engines remain replaceable and independently testable. Consensus weighting and persistence remain separate policies.
