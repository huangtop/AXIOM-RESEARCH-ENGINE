# ADR-0011D: Multiples Engine

## Status

Accepted.

## Context

The valuation layer needs a relative-valuation engine that can calculate current market
multiples and apply target or peer multiples without coupling the logic to a dataframe,
repository, or API layer.

## Decision

Introduce immutable multiples contracts in `valuation_models.py` and a stateless
`MultiplesEngine`.

Supported multiples are:

- EV / Revenue
- EV / EBIT
- EV / EBITDA
- EV / Free Cash Flow
- Price / Earnings, basic shares
- Price / Earnings, diluted shares
- Price / Book
- Price / Sales

The engine calculates observed multiples from market price and diluted shares. Enterprise
value is bridged from equity value using debt, non-controlling interest, preferred stock,
and cash. Target multiples produce implied enterprise value, equity value, per-share value,
and upside where the required inputs are available.

All arithmetic uses `Decimal` without implicit rounding. Each multiple is evaluated
independently. A missing or non-positive denominator suppresses only that multiple and is
reported through warnings.

## Consequences

The future intrinsic-value API can consume a deterministic, dependency-free relative
valuation result. Peer selection, median calculation, and data retrieval remain outside this
engine so that their evidence and provenance can be handled separately.
