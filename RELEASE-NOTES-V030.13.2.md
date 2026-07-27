# V030.13.2 — Historical Multiple Statistics

Builds readiness-gated statistics from the point-in-time observations created by V030.13.1.

## Principles

- Never treats one observation as a historical benchmark.
- Produces 20d, 60d, 252d, and all-history windows.
- Emits statistics only when the configured minimum observation count is met.
- Uses linear percentile interpolation.
- Excludes IQR outliers before statistics are calculated.
- Preserves the latest confidence and formula provenance for every company/method series.

## Outputs

- `data/generated/historical_multiple_statistics/historical_multiple_statistics.json`
- `data/generated/historical_multiple_statistics/historical_multiple_statistics_diagnostic.json`

## Default readiness

`minimum_ready_observations = 20`

With only one daily observation, each series is expected to be `insufficient_history` and have an empty `statistics` object in every window.
