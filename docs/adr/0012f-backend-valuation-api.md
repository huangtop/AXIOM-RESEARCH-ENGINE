# ADR 0012F — Backend Valuation API (corrected)

## Decision

`POST /v1/valuations` is the production endpoint. It accepts only security identity,
scenario selection and valuation time. It resolves canonical securities, SEC-derived
financial facts, estimates, valuation profiles and assumptions from `RepositoryBundle`,
then delegates model execution to `services.valuation.run_valuation_book`.

The previous completed close is injected as the canonical `market_price` fact for the
selected security/date. No other fundamental or estimate may be supplied by the client.

Legacy PHP formula parity remains available only at:

`POST /v1/debug/valuations/legacy-parity`

That endpoint is for regression/debugging and must not be used by production frontends.
