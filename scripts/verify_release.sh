#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -c 'import axiom_engine; assert axiom_engine.__version__ == "0.4.0"; print("version:", axiom_engine.__version__)'
"$PYTHON_BIN" -c 'from axiom_engine.io import read_json, write_json; print("io import: OK")'
ruff check .
pytest -q
axiom validate
axiom research --company-id company:US-NVDA >/dev/null
axiom value >/dev/null
axiom build-public >/dev/null

echo "AXIOM v0.4.0 release verification: PASS"
