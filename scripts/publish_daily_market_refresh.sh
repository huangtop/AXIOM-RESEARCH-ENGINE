#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

archive_root="data/generated/provider_cache/yahoo/daily_close"
cache_file="data/generated/market/previous_close_cache.json"
report_file="data/generated/market/daily_close_refresh_report.json"

retry_root="$(mktemp -d)"
trap 'rm -rf "$retry_root"' EXIT

preserve_market_inputs() {
  mkdir -p "$retry_root/daily_close"
  cp -R "$archive_root/." "$retry_root/daily_close/"
  cp "$cache_file" "$retry_root/previous_close_cache.json"

  if [[ -f "$report_file" ]]; then
    cp "$report_file" "$retry_root/daily_close_refresh_report.json"
  fi
}

restore_market_inputs() {
  mkdir -p "$archive_root"
  rm -rf "$archive_root"/*
  cp -R "$retry_root/daily_close/." "$archive_root/"
  cp "$retry_root/previous_close_cache.json" "$cache_file"

  if [[ -f "$retry_root/daily_close_refresh_report.json" ]]; then
    cp "$retry_root/daily_close_refresh_report.json" "$report_file"
  fi
}

stage_market_outputs() {
  git add -f "$archive_root"
  git add "$cache_file"

  if [[ -f "$report_file" ]]; then
    git add "$report_file"
  fi
}

preserve_market_inputs

for attempt in 1 2 3; do
  git fetch origin main

  # If main advanced while Yahoo was running, keep the completed market
  # download, move to the new main, then restore only the market artifacts.
  # Valuation/publication artifacts are intentionally not rebuilt here.
  if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
    echo "main advanced during refresh; restoring market-only artifacts on origin/main (attempt $attempt)"
    git reset --hard origin/main
    restore_market_inputs
  fi

  stage_market_outputs

  if git diff --cached --quiet; then
    echo "No market changes to publish."
    exit 0
  fi

  git commit -m "chore(data): refresh production daily market data"

  if git push origin HEAD:main; then
    exit 0
  fi

  echo "main changed before push; retrying from the latest main"
done

echo "Unable to publish market refresh after 3 race-safe attempts." >&2
exit 1