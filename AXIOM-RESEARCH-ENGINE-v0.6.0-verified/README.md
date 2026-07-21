# AXIOM Research Engine v0.6.0

Evidence-based company research, Industry Graph, valuation, and ETF exposure foundation.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
rehash
```

## Verify

```bash
./scripts/verify_release.sh
```

## Core commands

```bash
axiom validate
axiom research --company-id company:US-NVDA
axiom industry --company-id company:US-NVDA
axiom industry --company-id company:US-NVDA \
  --source-id demand_driver:CLOUD-AI-CAPEX \
  --target-id company:US-NVDA
axiom value
axiom etf --etf-id etf:AXSM
axiom build-public
```

## v0.6 ETF mapping

- ETF holdings map funds to companies and securities.
- Theme exposure is derived from holding weight × company industry exposure.
- ETF valuation aggregates available company valuation upside and reports coverage.
- Industry propagation follows cause → effect.

The included `AXSM` and `AXAI` datasets are synthetic research baskets, not tradable ETFs or current holdings.
