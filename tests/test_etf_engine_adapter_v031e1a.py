from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from axiom_engine.etf_engine_adapter import ETFEngineContractError, load_cached_etf_engine_snapshot, sync_etf_engine_cache


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _write_config(root: Path) -> None:
    path = root / "config/etf_engine_source.v031e.1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schema_version":"etf-engine-source-contract.v031e.1","version":"V031E.1A","provider_id":"etf-engine-v2",
        "repository":"huangtop/ETF-ENGINE-V2","branch":"main","base_url":"https://example.test/data/public",
        "manifest_path":"manifest.json","holdings_index_path":"holdings_index.json","required_provider_schema_version":"2.2",
        "cache_ttl_hours":24,"source_mode":"read_only","holdings_coverage":"top_holdings_only"
    }))


def _payloads(weight: float = 0.177539):
    manifest = {"schema_version":"2.2","generated_at":"2026-07-29T00:00:00+00:00","etf_count":1,"holding_symbols":1,"overlap_pairs":0,"markets":{"US":1}}
    holdings = {"NVDA":[{"etf_id":"US-SMH","ticker":"SMH","name":"VanEck Semiconductor ETF","weight":weight}]}
    return {"manifest.json":json.dumps(manifest).encode(), "holdings_index.json":json.dumps(holdings).encode()}


def _fetcher(payloads, calls):
    def fetch(url: str) -> bytes:
        calls.append(url)
        return payloads[url.rsplit("/", 1)[-1]]
    return fetch


def test_updates_immutable_snapshot_and_loads_last_known_good(tmp_path: Path):
    _write_config(tmp_path)
    calls = []
    report = sync_etf_engine_cache(tmp_path, allow_live=True, now=NOW, fetcher=_fetcher(_payloads(), calls))
    assert report["status"] == "updated"
    assert report["state"]["source_mode"] == "read_only"
    assert report["state"]["summary"]["holding_exposure_count"] == 1
    assert len(report["state"]["manifest_sha256"]) == 64
    snapshot = load_cached_etf_engine_snapshot(tmp_path / "data/generated/provider_cache/etf_engine_v2")
    assert snapshot["holdings_index"]["NVDA"][0]["weight"] == 0.177539
    assert len(calls) == 2


def test_fresh_cache_avoids_all_network_requests(tmp_path: Path):
    _write_config(tmp_path)
    calls = []
    fetcher = _fetcher(_payloads(), calls)
    sync_etf_engine_cache(tmp_path, allow_live=True, now=NOW, fetcher=fetcher)
    report = sync_etf_engine_cache(tmp_path, allow_live=True, now=NOW + timedelta(hours=1), fetcher=fetcher)
    assert report["status"] == "cache_fresh"
    assert len(calls) == 2


def test_unchanged_manifest_does_not_redownload_holdings(tmp_path: Path):
    _write_config(tmp_path)
    calls = []
    fetcher = _fetcher(_payloads(), calls)
    sync_etf_engine_cache(tmp_path, allow_live=True, now=NOW, fetcher=fetcher)
    report = sync_etf_engine_cache(tmp_path, allow_live=True, force=True, now=NOW + timedelta(days=2), fetcher=fetcher)
    assert report["status"] == "unchanged"
    assert len(calls) == 3


def test_invalid_update_retains_last_known_good_snapshot(tmp_path: Path):
    _write_config(tmp_path)
    sync_etf_engine_cache(tmp_path, allow_live=True, now=NOW, fetcher=_fetcher(_payloads(), []))
    invalid = _payloads(weight=1.5)
    manifest = json.loads(invalid["manifest.json"])
    manifest["generated_at"] = "2026-07-30T00:00:00+00:00"
    invalid["manifest.json"] = json.dumps(manifest).encode()
    report = sync_etf_engine_cache(tmp_path, allow_live=True, force=True, now=NOW + timedelta(days=1), fetcher=_fetcher(invalid, []))
    assert report["status"] == "stale_fallback"
    assert report["used_last_known_good"] is True
    snapshot = load_cached_etf_engine_snapshot(tmp_path / "data/generated/provider_cache/etf_engine_v2")
    assert snapshot["holdings_index"]["NVDA"][0]["weight"] == 0.177539


def test_contract_rejects_wrong_schema_without_existing_cache(tmp_path: Path):
    _write_config(tmp_path)
    payloads = _payloads()
    manifest = json.loads(payloads["manifest.json"])
    manifest["schema_version"] = "9.9"
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with pytest.raises(ETFEngineContractError, match="schema version mismatch"):
        sync_etf_engine_cache(tmp_path, allow_live=True, now=NOW, fetcher=_fetcher(payloads, []))


def test_live_disabled_never_calls_provider(tmp_path: Path):
    _write_config(tmp_path)
    report = sync_etf_engine_cache(tmp_path, allow_live=False, fetcher=lambda _: (_ for _ in ()).throw(AssertionError()))
    assert report["status"] == "unavailable_live_disabled"
