# V030.13.3 — Historical Multiple Benchmark

Creates a readiness-gated benchmark contract from V030.13.2 statistics.

- Selects the preferred ready statistics window.
- Uses median as the benchmark and p25/p75 as the valuation range.
- Emits `target_multiple` for multiple methods and `target_yield_percent` for FCF yield.
- Preserves insufficient history without fabricating a benchmark.
- Grades confidence from both source confidence and observation depth.
- Does not calculate fair value or target price.
