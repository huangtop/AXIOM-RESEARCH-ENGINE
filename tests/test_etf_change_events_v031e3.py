from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from axiom_engine.etf_change_events import build_canonical_etf_change_events, sync_etf_change_cache


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _config(root: Path) -> None:
    _write(root / "config/etf_engine_changes.v031e.3.json", {
        "schema_version":"etf-engine-change-source-contract.v031e.3","provider_id":"etf-engine-v2",
        "repository":"huangtop/ETF-ENGINE-V2","base_url":"https://example.test/history/holdings",
        "manifest_path":"manifest.json","latest_changes_path":"latest_changes.json",
        "required_provider_schema_version":"1.0","cache_ttl_hours":24,"source_mode":"read_only",
        "holdings_coverage":"top_holdings_only","accepted_etf_market_prefixes":["US-"]
    })


def _provider():
    manifest = {"schema_version":"1.0","generated_at":"2026-07-29T00:00:00Z","coverage":"top_holdings_only"}
    base = {"event_id":"e1","holding_symbol":"MU","previous_weight":0.01,"current_weight":None,"delta_weight":-0.01,"change_type":"EXITED_TOP_HOLDINGS","previous_observed_at":"2026-07-28T00:00:00Z","current_observed_at":"2026-07-29T00:00:00Z"}
    latest = {"schema_version":"1.0","coverage":"top_holdings_only","selection":"latest_transition_per_etf","changes":[{**base,"etf_id":"US-QQQ"},{**base,"event_id":"tw1","etf_id":"TW-0050","holding_symbol":"2330.TW"},{**base,"event_id":"bad","etf_id":"US-SMH","holding_symbol":"UNKNOWN"}]}
    return {"manifest.json":json.dumps(manifest).encode(), "latest_changes.json":json.dumps(latest).encode()}


def test_cache_and_project_us_events_with_identity_diagnostics(tmp_path: Path):
    _config(tmp_path)
    payloads = _provider()
    result = sync_etf_change_cache(tmp_path, allow_live=True, now=NOW, fetcher=lambda url: payloads[url.rsplit("/", 1)[-1]])
    assert result["status"] == "updated"
    _write(tmp_path / "data/generated/etf_identity_bridge/identity_bridge.json", {
        "schema_version":"etf-security-identity-bridge.v031e.1",
        "records":[{"holding_symbol":"MU","status":"resolved_exact","reason_code":"UNIQUE_ACTIVE_COMMON_EQUITY_MATCH","security_id":"security:NASDAQ-MU","company_id":"company:MU"}]
    })
    report = build_canonical_etf_change_events(tmp_path, now=NOW)
    assert report["events"][0]["company_id"] == "company:MU"
    assert report["events"][0]["official_membership_change"] is False
    assert report["summary"]["non_us_events_excluded"] == 1
    assert report["summary"]["unresolved_event_count"] == 1
    assert report["summary"]["valuation_readiness_consumed"] is False


def test_live_disabled_does_not_fetch(tmp_path: Path):
    _config(tmp_path)
    result = sync_etf_change_cache(tmp_path, allow_live=False, fetcher=lambda _: (_ for _ in ()).throw(AssertionError()))
    assert result["status"] == "unavailable_live_disabled"
