# ADR 0013: Canonical Six-Model Scenario Valuation

## Status

Accepted.

## Decision

The production repository valuation profile for high-growth AI semiconductors uses six canonical models: Forward P/E, PEG, Forward P/S, EV/EBITDA, Forward P/B and milestone expected value. Model blend weights are explicit profile parameters and are normalized across completed models. PEG inputs come from scenario-specific canonical EPS and growth estimates plus a scenario PEG assumption. Milestone inputs come from scenario assumptions and use the resolved previous close as the common valuation baseline.

NVDA receives explicit Bear, Base and Bull scenarios. A request without `scenario_id` continues to select the latest Base scenario. The API publishes the selected scenario type, available scenarios and each model's blend weight.

## Consequences

The frontend remains read-only. Scenario selection changes only canonical backend records. Missing model inputs produce skipped models; completed model weights are re-normalized rather than silently assigning a value to unavailable models.
