#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

cache_file="data/generated/market/previous_close_cache.json"
report_file="data/generated/market/daily_close_refresh_report.json"
retry_root="$(mktemp -d)"
trap 'rm -rf "$retry_root"' EXIT

preserve_market_inputs() {
  cp "$cache_file" "$retry_root/previous_close_cache.json"
  if [[ -f "$report_file" ]]; then
    cp "$report_file" "$retry_root/daily_close_refresh_report.json"
  fi
}

restore_market_inputs() {
  cp "$retry_root/previous_close_cache.json" "$cache_file"
  if [[ -f "$retry_root/daily_close_refresh_report.json" ]]; then
    cp "$retry_root/daily_close_refresh_report.json" "$report_file"
  fi
}

rebuild_generated_outputs() {
  python scripts/build_full_market_coverage.py
  python scripts/build_coverage_policy.py
  python scripts/build_publication_catalog.py
  pytest -q \
    tests/test_full_market_daily_close_population_v031v1.py \
    tests/test_full_market_coverage_v031.py \
    tests/test_publication_gate_v031f2.py
}

stage_generated_outputs() {
  git add -f data/generated/provider_cache/yahoo/daily_close
  git add \
    data/generated/market \
    data/generated/full_market_coverage \
    data/generated/coverage_policy \
    data/generated/publication_gate
}

preserve_market_inputs

for attempt in 1 2 3; do
  git fetch origin main

  # Generated content-hash shards cannot be meaningfully rebased. If main
  # advanced while Yahoo was running, retain the completed market download,
  # move to the new main, and deterministically rebuild all derived artifacts.
  if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
    echo "main advanced during refresh; rebuilding on origin/main (attempt $attempt)"
    git reset --hard origin/main
    restore_market_inputs
    rebuild_generated_outputs
  fi

  stage_generated_outputs
  if git diff --cached --quiet; then
    echo "No generated market changes to publish."
    exit 0
  fi

  git commit -m "chore(data): refresh production daily market artifacts"
  if git push origin HEAD:main; then
    exit 0
  fi

  echo "main changed before push; retrying from the latest main"
done

echo "Unable to publish market refresh after 3 race-safe rebuild attempts." >&2
exit 1
