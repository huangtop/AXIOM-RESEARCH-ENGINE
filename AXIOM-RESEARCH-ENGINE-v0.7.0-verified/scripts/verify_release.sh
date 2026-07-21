#!/usr/bin/env bash
set -euo pipefail
python -c "import axiom_engine, axiom_engine.io; print('version:', axiom_engine.__version__); print('io import: OK')"
python -m ruff check .
python -m pytest -q
axiom validate
axiom research --company-id company:US-NVDA >/dev/null
axiom industry --company-id company:US-NVDA --source-id demand_driver:CLOUD-AI-CAPEX --target-id company:US-NVDA >/dev/null
axiom value >/dev/null
axiom etf --etf-id etf:AXSM >/dev/null
axiom impact --shock-id shock:CLOUD-AI-CAPEX-DOWN-15 >/dev/null
axiom impact --shock-id shock:HBM4-SUPPLY-DOWN-20 >/dev/null
axiom build-public >/dev/null
echo "AXIOM v0.7.0 release verification: PASS"
