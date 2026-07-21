# Migration: v0.5 → v0.6

## Breaking semantic correction

Replace `industry_edge:RUBIN-DEPENDS-CLOUD-CAPEX` with `industry_edge:CLOUD-CAPEX-DRIVES-RUBIN`.

- source: `demand_driver:CLOUD-AI-CAPEX`
- target: `product_architecture:NVDA-VERA-RUBIN`
- type: `drives_demand_for`

Consumers that stored the old edge ID must migrate references in graph snapshots.

## New collections

- `data/etf/etf_profiles.json`
- `data/etf/etf_holdings.json`
- `data/etf/etf_theme_exposures.json`
- `data/etf/etf_valuation_snapshots.json`

## New CLI

```bash
axiom etf --etf-id etf:AXSM
```
