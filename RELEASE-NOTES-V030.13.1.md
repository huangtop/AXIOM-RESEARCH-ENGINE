# V030.13.1 — Historical Multiple Dataset

Creates a point-in-time, append-only observation store from the V030.13.0 valuation engine snapshot.

## Integrity rule

The release does not reconstruct historical multiples by combining old prices with current fundamentals. Each observation is captured from the engine snapshot available on that observation date.

## Supported historical metrics

- Forward P/E
- Trailing P/E
- Price/Sales
- EV/Sales
- EV/EBITDA
- FCF Yield (%)

DCF is excluded because it is not a market multiple.

## Dataset behavior

- New dates append observations.
- Re-running the same date replaces the same company/method/date record.
- Series remain `collecting` until the configured minimum observation count is reached.
- No target multiple or fair value is produced in this release.
