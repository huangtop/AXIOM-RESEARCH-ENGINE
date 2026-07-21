#!/usr/bin/env bash
set -euo pipefail
TARGET="${1:-.}"
PATCH_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ ! -f "$TARGET/pyproject.toml" || ! -d "$TARGET/src/axiom_engine" ]]; then
  echo "ERROR: target is not an AXIOM repository: $TARGET" >&2; exit 2
fi
CURRENT=$(grep -E '^version = ' "$TARGET/pyproject.toml" | head -1 || true)
echo "Target: $TARGET ($CURRENT)"
BACKUP="$TARGET/.axiom-backup-v0.4.0-$(date +%Y%m%d%H%M%S)"
mkdir -p "$BACKUP"
for f in pyproject.toml README.md src/axiom_engine data/canonical/entities.json data/valuation/estimates.json tests; do
  [[ -e "$TARGET/$f" ]] && cp -a "$TARGET/$f" "$BACKUP/$(basename "$f")"
done
cp -a "$PATCH_DIR/files/." "$TARGET/"
find "$TARGET" -type d -name '__pycache__' -prune -exec rm -rf {} + || true
rm -rf "$TARGET/.pytest_cache"
echo "Patch applied. Backup: $BACKUP"
echo "Next: cd '$TARGET' && python -m pip install -e '.[dev]' && axiom validate && pytest -q && ruff check ."
