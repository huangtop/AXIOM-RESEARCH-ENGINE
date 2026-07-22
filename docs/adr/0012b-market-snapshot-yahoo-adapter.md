# ADR 0012B: Market Snapshot and Yahoo Adapter

## Status

Accepted.

## Context

Full-market valuation needs a provider-neutral point-in-time contract for prices,
market capitalization, shares, earnings, valuation multiples, and trading context.
The valuation engines must not depend directly on a remote provider payload.

## Decision

Introduce `MarketSnapshot` as an immutable normalized market-data contract and
`YahooMarketDataAdapter` as the first provider implementation.

The adapter:

- uses Yahoo's quote response as an external transport format only;
- converts numeric values to `Decimal`;
- records a timezone-aware observation timestamp;
- supports single and batched symbols;
- deduplicates batched requests while preserving caller order;
- provides bounded retries for transient HTTP failures;
- supports optional JSON caching;
- accepts an injectable opener, clock, sleep function, and random source;
- has no live-network requirement in the test suite.

Yahoo is not treated as an authoritative accounting source. SEC-normalized
financial statements remain the source for reported financial fundamentals.
Market snapshots are intended for market prices, market-derived ratios, model
eligibility, and later full-market valuation orchestration.

## Consequences

Later commits can determine valuation-model eligibility and construct valuation
inputs without coupling core engines to Yahoo field names. Additional providers
can produce the same `MarketSnapshot` contract.
