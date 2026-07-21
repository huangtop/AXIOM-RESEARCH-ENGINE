# ETF Foundation v0.6

AXIOM v0.6 maps company-level research into ETF-level outputs through three layers:

1. `ETFHolding`: ETF → company/security with an as-of weight.
2. `ETFThemeExposure`: derived from holding weight × company industry exposure weight.
3. `ETFValuationSnapshot`: holding-weighted upside using available company valuation books, with an explicit coverage ratio.

## Causal direction rule

Industry Graph edges used for propagation follow **cause → effect**. The v0.5 seed edge was corrected from:

`Vera Rubin → Cloud AI CapEx (depends_on)`

to:

`Cloud AI CapEx → Vera Rubin (drives_demand_for)`

This makes path traversal, shock propagation, and ETF impact analysis directionally consistent.

## Demo data

`AXSM` and `AXAI` are synthetic research baskets, not tradable products or current market holdings. They exist only to validate the schema and calculation pipeline.
