# ADR-007: Independent Market Data Pipeline

## Decision

AXIOM stores point-in-time market observations in an independent canonical layer. Provider connectors normalize into `MarketDataSource`; valuation code reads canonical output rather than calling providers.

## Scope

Included: current price, previous close, market capitalization, enterprise value, market-side shares outstanding, trading status, timestamps, sessions, currency and provenance.

Excluded: fair value, intrinsic value, analyst price targets, upside/downside, margin of safety, valuation conclusions, themes, classifications and exposures.

## Temporal rule

Every numeric observation carries `observed_at`, `trading_date` and session. No record may be treated as timeless or silently overwritten by a newer quote.

## Identity rule

Every observation references both canonical `company_id` and `security_id`. Market data attaches to a security; company aggregation remains a derived view.

## Provider rule

The canonical schema contains no provider-specific fields. Provider-specific payloads belong in connectors outside this package and may retain extra source details only under provenance metadata.
