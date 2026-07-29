from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from axiom_engine.canonical_etf_exposure import CanonicalETFExposureError, build_canonical_etf_exposure


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _fixture(tmp_path: Path, *, bridge_snapshot: str = "s1") -> Path:
    state = {"current_snapshot_id":"s1","provider_generated_at":"2026-07-28T00:00:00+00:00","cached_at":"2026-07-29T00:00:00+00:00","holdings_index_sha256":"abc","manifest_sha256":"def","holdings_coverage":"top_holdings_only","source_repository":"huangtop/ETF-ENGINE-V2","holdings_index_url":"https://example.test/holdings_index.json"}
    holdings = {
        "NVDA":[{"etf_id":"US-SMH","ticker":"SMH","name":"VanEck Semiconductor ETF","name_en":"VanEck Semiconductor ETF","weight":0.177539}],
        "2330.TW":[{"etf_id":"TW-0050","ticker":"0050","name":"ETF","weight":0.5}],
    }
    _write(tmp_path, "data/generated/provider_cache/etf_engine_v2/state.json", state)
    _write(tmp_path, "data/generated/provider_cache/etf_engine_v2/snapshots/s1/manifest.json", {"schema_version":"2.2"})
    _write(tmp_path, "data/generated/provider_cache/etf_engine_v2/snapshots/s1/holdings_index.json", holdings)
    _write(tmp_path, "data/generated/etf_identity_bridge/identity_bridge.json", {
        "schema_version":"etf-security-identity-bridge.v031e.1","source_snapshot":{"snapshot_id":bridge_snapshot},
        "records":[
            {"holding_symbol":"NVDA","status":"resolved_exact","reason_code":"UNIQUE_ACTIVE_COMMON_EQUITY_MATCH","security_id":"security:NASDAQ-NVDA","company_id":"company:NVDA"},
            {"holding_symbol":"2330.TW","status":"unsupported_market","reason_code":"MARKET_NOT_PRESENT_IN_AXIOM_REGISTRY","security_id":None,"company_id":None,"source_etf_ids":["TW-0050"]},
        ]
    })
    return tmp_path


def test_builds_canonical_weight_and_provenance_without_fabricating_as_of(tmp_path: Path):
    report = build_canonical_etf_exposure(_fixture(tmp_path), now=NOW)
    exposure = report["exposures"][0]
    assert exposure["company_id"] == "company:NVDA"
    assert exposure["portfolio_weight"] == 0.177539
    assert exposure["portfolio_weight_percent"] == 17.7539
    assert exposure["as_of"] is None
    assert exposure["as_of_status"] == "unavailable_provider_did_not_supply"
    assert exposure["source_status"] == "top_holdings_only"
    assert report["provenance"][0]["content_sha256"] == "abc"
    assert report["summary"]["valuation_readiness_consumed"] is False


def test_preserves_unresolved_exposure_in_coverage_audit(tmp_path: Path):
    report = build_canonical_etf_exposure(_fixture(tmp_path))
    assert report["summary"]["source_etf_exposure_count"] == 2
    assert report["summary"]["canonical_etf_exposure_count"] == 1
    assert report["summary"]["unresolved_etf_exposure_count"] == 1
    assert report["coverage_audit"]["unresolved_symbols"][0]["holding_symbol"] == "2330.TW"


def test_rejects_bridge_from_different_provider_snapshot(tmp_path: Path):
    with pytest.raises(CanonicalETFExposureError, match="snapshots do not match"):
        build_canonical_etf_exposure(_fixture(tmp_path, bridge_snapshot="old"))


def test_generated_snapshot_contains_nvda_smh_exposure():
    root = Path(__file__).parents[1]
    exposures = json.loads((root / "data/generated/canonical_etf_exposure/etf_exposures.json").read_text())
    row = next(item for item in exposures if item["holding_symbol"] == "NVDA" and item["etf_id"] == "US-SMH")
    assert row["company_id"] == "company:US-CIK0001045810"
    assert row["portfolio_weight_percent"] == 17.7539
