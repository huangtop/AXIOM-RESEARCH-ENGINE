# ADR 0012E: Legacy Valuation Parity and Previous Close

## Status

Accepted.

## Context

The WordPress valuation dashboard computes PEG, P/E, P/S, P/B, EV/EBITDA and milestone values in JavaScript. Comparing those values with the Python service using an intraday quote creates false differences.

## Decision

Add a completed-session `DailyClose` boundary and Yahoo chart adapter. Add a Decimal-only legacy parity engine that reproduces the six PHP/JavaScript formulas and accepts the existing research JSON field names. Missing inputs produce an explicit unavailable result rather than manufactured assumptions. Values retain full precision internally and round half-up to cents only for display and parity comparison.

## Consequences

NVDA and later market-wide regression fixtures can lock one prior trading-session close and compare PHP and Python model outputs deterministically. This compatibility layer is separate from native DCF and reverse-DCF valuation policy.
