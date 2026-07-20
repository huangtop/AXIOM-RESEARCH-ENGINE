#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
PATCH_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$ROOT" && pwd)"

if [[ ! -f "$ROOT/pyproject.toml" || ! -d "$ROOT/src/axiom_engine" ]]; then
  echo "錯誤：$ROOT 看起來不是 AXIOM 專案根目錄。" >&2
  exit 1
fi

printf '套用 AXIOM v0.3.0 patch 到：%s\n' "$ROOT"

# Remove files from the old v0.1 architecture that conflict with v0.3 imports/tests.
rm -f \
  "$ROOT/src/axiom_engine/models/bundle.py" \
  "$ROOT/src/axiom_engine/models/common.py" \
  "$ROOT/src/axiom_engine/models/entity.py" \
  "$ROOT/src/axiom_engine/models/evidence.py" \
  "$ROOT/src/axiom_engine/models/market.py" \
  "$ROOT/src/axiom_engine/models/relation.py" \
  "$ROOT/src/axiom_engine/models/security.py" \
  "$ROOT/src/axiom_engine/models/source.py" \
  "$ROOT/src/axiom_engine/services/repository.py" \
  "$ROOT/tests/test_models.py" \
  "$ROOT/tests/test_public_builder.py" \
  "$ROOT/.github/workflows/build-public.yml"

rm -rf \
  "$ROOT/src/axiom_engine/providers" \
  "$ROOT/src/axiom_engine/utils" \
  "$ROOT/data/normalized" \
  "$ROOT/data/seed" \
  "$ROOT/data/state" \
  "$ROOT/schemas" \
  "$ROOT/.pytest_cache" \
  "$ROOT/.ruff_cache"

# Generated/public output must be rebuilt under the new schema.
rm -rf "$ROOT/data/generated" "$ROOT/data/public"
mkdir -p "$ROOT/data/generated" "$ROOT/data/public"
touch "$ROOT/data/generated/.gitkeep"

# Copy patch payload. Exclude this script and guide.
(
  cd "$PATCH_DIR"
  tar --exclude='./apply_patch.sh' --exclude='./UPGRADE-v0.3.0.md' -cf - .
) | (
  cd "$ROOT"
  tar -xf -
)

# Editable installs can otherwise keep stale package metadata and bytecode.
find "$ROOT/src" "$ROOT/tests" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$ROOT/src/axiom_research_engine.egg-info"

cat <<'MSG'
Patch 已套用。

接著請在專案根目錄執行：

  deactivate 2>/dev/null || true
  rm -rf .venv
  python3 -m venv .venv
  source .venv/bin/activate
  python3 -m pip install --upgrade pip
  python3 -m pip install -e '.[dev]'
  axiom validate
  axiom value
  axiom build-public
  pytest -q
  ruff check .
MSG
