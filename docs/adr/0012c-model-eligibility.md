# ADR 0012C: Model Eligibility

## Status

Accepted.

## Context

The full-market valuation service must not attempt every valuation model for every
security. Market snapshots can supply prices, shares and selected quote metrics,
but they cannot establish forecast quality, peer assumptions, discount rates or
research milestone probabilities.

## Decision

Add a provider-neutral `ModelEligibilityEngine` that performs deterministic,
side-effect-free readiness checks before any valuation engine is invoked.

Each model receives one of three states:

- `eligible`: all required inputs exist and basic quality checks pass;
- `conditional`: the model can run, but its output has an identified limitation;
- `ineligible`: one or more required inputs are unavailable or invalid.

The report includes stable reason codes, required and optional missing fields,
and suggested fallback models. Eligibility does not fetch data, manufacture
assumptions or execute a valuation.

Rules cover DCF, reverse DCF, multiples, PEG and milestone valuation. Research
assumptions remain explicit inputs rather than being inferred from Yahoo data.

## Consequences

The next orchestration layer can choose models consistently and explain why a
model was skipped. Eligibility remains independently testable and can evolve
without coupling providers to valuation engines.
