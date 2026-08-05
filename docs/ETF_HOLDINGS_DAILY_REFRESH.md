# ETF holdings daily refresh

`Daily ETF Holdings Refresh` polls the read-only ETF-ENGINE-V2 projection after US
market data is expected to settle. The provider timestamp, rather than the polling
date, identifies a snapshot. Re-polling identical provider content is a no-op.

The pipeline writes:

- immutable per-fund snapshots under
  `data/generated/canonical_etf_holdings_history/snapshots/<date>/funds/`;
- latest-versus-previous observed changes under
  `data/generated/canonical_etf_change_events/`;
- lightweight company projections under
  `data/generated/canonical_etf_change_events/per-company/`;
- material research-company triggers at
  `data/generated/event_triggers/etf_changes.json`.

The upstream contract is currently `top_holdings_only`. Absence therefore means
"not observed in the published top holdings", not proof that a fund owns zero
shares. Share changes remain `not_provided_by_source` when the provider supplies
weights but no share count; the pipeline never estimates missing shares.

This workflow does not invoke the news pipeline. The event-driven news workflow
may consume the trigger artifact, which keeps the two release streams independent.
