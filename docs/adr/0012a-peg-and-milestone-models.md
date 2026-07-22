# ADR-0012A: PEG and Milestone Models

## Status

Accepted.

## Context

The replacement valuation page must support the two legacy model families not covered by DCF, reverse DCF, or relative multiples: PEG growth valuation and probability-weighted milestone valuation. The current web page calculates both models in JavaScript, which prevents reuse, deterministic testing, and server-side data-quality controls.

## Decision

Add immutable PEG and milestone contracts to `valuation_models.py`, stateless `PEGEngine` and `MilestoneEngine` implementations, and optional support for both models in `IntrinsicValueEngine`.

PEG uses forward earnings per share, a decimal growth rate, and a PEG ratio. The implied P/E is `PEG ratio × growth percentage`. For positive forward EPS but non-positive growth, the engine applies an explicit configurable fallback P/E and emits a warning. Non-positive forward EPS produces no fair value because neither PEG nor the fallback P/E is meaningful for a loss-making company.

Milestone valuation uses the current price as the scenario baseline and calculates a probability-weighted expected multiple from success and failure cases. Defaults preserve the existing web behavior: `3.0x` success and `0.5x` failure.

Both engines:

- use `Decimal` without implicit rounding;
- expose fair value per share and upside where meaningful;
- return structured warnings rather than silently coercing unavailable values;
- preserve their native outputs when orchestrated through the intrinsic-value API.

## Consequences

The valuation core now supports every model currently exposed by the web page: PEG, P/E, P/S, P/B, EV/EBITDA, and milestone scenarios. Data retrieval, model eligibility, compatibility serialization, and dynamic full-market ticker support remain separate follow-up commits.
