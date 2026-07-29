# V031E.1D — Company ETF Exposure API Projection

## Outcome

- Adds `GET /v1/companies/{ticker}/etf-exposure` to the existing AXIOM WSGI API.
- Reads only committed Canonical ETF Exposure and indexes; request handling never fetches ETF-ENGINE-V2 or rebuilds identity.
- Resolves only active common or ordinary equity tickers through V031V.2 Security Identity.
- Returns ETF exposures ordered by descending portfolio weight.
- Returns HTTP 200 with an explicit empty state for a known company with no observed Top Holdings exposure.
- Returns HTTP 404 for an unknown or non-company instrument ticker and HTTP 503 for an unavailable or inconsistent Canonical snapshot.

## Response contract

The response includes company identity, exposure count, maximum observed portfolio weight, provider snapshot metadata, `as_of` availability, source coverage, and an interpretation warning that ETF portfolio weight is not ETF ownership of the company.

For the current snapshot, NVIDIA returns 37 observed ETF exposures. Its SMH record reports a portfolio weight of `0.177539`, displayed as `17.7539%`, with `as_of` explicitly unavailable from the provider.

## Boundary

This endpoint projects the current `top_holdings_only` snapshot. It does not claim complete ETF membership and does not infer inclusion, removal, buying, selling, or historical weight changes.
