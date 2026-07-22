# ADR-0011E: Intrinsic Value API

## Status

Accepted

## Context

The valuation layer now contains independent DCF, reverse DCF, and relative-multiples engines. Callers should not need to coordinate these engines directly or construct a different integration path for each model.

## Decision

Add `IntrinsicValueEngine` as the single orchestration entry point.

`IntrinsicValueInputs` accepts one or more existing model-specific input contracts. Every nested input must share the same `ValuationIdentity`. At least one model input is required.

The engine:

- runs only the supplied models;
- preserves each engine's native result without averaging or ranking values;
- passes the API-level market price to the DCF engine;
- exposes reverse-DCF non-convergence as an API-level warning;
- returns one immutable `IntrinsicValueResult` containing optional DCF, reverse-DCF, and multiples results;
- retains full `Decimal` precision and serializes nested values through `to_dict()`.

## Consequences

Callers receive one stable API while model-specific calculation rules remain isolated and independently testable. The API intentionally does not create a consensus price because weighting unrelated valuation methods requires an explicit policy that belongs in a later commit.
