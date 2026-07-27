# V030.10.4.2 — Yahoo Runtime Dependency Fix

- Declares `yfinance` as the `yahoo` optional runtime dependency.
- Adds a dependency declaration test.
- Deployment stops with an explicit install command when the active environment lacks `yfinance`.
- No provider, identity schema, or generated data behavior changes.
