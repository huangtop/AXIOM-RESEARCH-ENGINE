from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from axiom_engine.etf_identity_bridge import build_etf_identity_bridge


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _fixture(tmp_path: Path) -> Path:
    policy = json.loads((Path(__file__).parents[1] / "config/etf_identity_bridge.v031e.1.json").read_text())
    _write(tmp_path, "config/etf_identity_bridge.v031e.1.json", policy)
    securities = [
        {"security_id":"security:NASDAQ-NVDA","company_id":"company:NVDA","ticker":"NVDA","exchange":"NASDAQ","status":"active","primary_listing":True,"metadata":{}},
        {"security_id":"security:NYSE-BRK.B","company_id":"company:BRK.B","ticker":"BRK.B","exchange":"NYSE","status":"active","primary_listing":True,"metadata":{}},
        {"security_id":"security:NASDAQ-NEW","company_id":"company:NEW","ticker":"NEW","exchange":"NASDAQ","status":"active","primary_listing":True,"metadata":{"previous_tickers":["OLD"]}},
        {"security_id":"security:NASDAQ-DUP1","company_id":"company:DUP1","ticker":"DUP","exchange":"NASDAQ","status":"active","primary_listing":True,"metadata":{}},
        {"security_id":"security:NYSE-DUP2","company_id":"company:DUP2","ticker":"DUP","exchange":"NYSE","status":"active","primary_listing":True,"metadata":{}},
        {"security_id":"security:NASDAQ-W","company_id":"company:W","ticker":"W","exchange":"NASDAQ","status":"active","primary_listing":True,"metadata":{}},
    ]
    _write(tmp_path, "data/universe/securities.json", securities)
    normalized = [{"security_id":row["security_id"],"instrument_type":"warrant" if row["ticker"] == "W" else "common_or_ordinary_equity"} for row in securities]
    _write(tmp_path, "data/generated/security_identity/security_identity_normalization.json", {"schema_version":"security-identity-normalization.v031v.2","securities":normalized})
    holdings = {symbol:[{"etf_id":"US-TEST","ticker":"TEST","weight":0.1}] for symbol in ("NVDA","BRK-B","OLD","DUP","W","2330.TW","MISS")}
    _write(tmp_path, "data/generated/provider_cache/etf_engine_v2/state.json", {"current_snapshot_id":"s1","provider_generated_at":"2026-07-28T00:00:00+00:00","holdings_index_sha256":"abc","holdings_coverage":"top_holdings_only"})
    _write(tmp_path, "data/generated/provider_cache/etf_engine_v2/snapshots/s1/manifest.json", {"schema_version":"2.2"})
    _write(tmp_path, "data/generated/provider_cache/etf_engine_v2/snapshots/s1/holdings_index.json", holdings)
    return tmp_path


def test_resolves_exact_class_share_and_verified_registry_alias(tmp_path: Path):
    report = build_etf_identity_bridge(_fixture(tmp_path), now=NOW)
    rows = {row["holding_symbol"]: row for row in report["records"]}
    assert rows["NVDA"]["status"] == "resolved_exact"
    assert rows["NVDA"]["company_id"] == "company:NVDA"
    assert rows["BRK-B"]["status"] == "resolved_alias"
    assert rows["BRK-B"]["matched_registry_symbol"] == "BRK.B"
    assert rows["OLD"]["reason_code"] == "VERIFIED_REGISTRY_TICKER_ALIAS"


def test_preserves_ambiguous_unsupported_unresolved_and_non_equity(tmp_path: Path):
    report = build_etf_identity_bridge(_fixture(tmp_path))
    rows = {row["holding_symbol"]: row for row in report["records"]}
    assert rows["DUP"]["status"] == "ambiguous"
    assert len(rows["DUP"]["candidate_security_ids"]) == 2
    assert rows["2330.TW"]["status"] == "unsupported_market"
    assert rows["MISS"]["status"] == "unresolved"
    assert rows["W"]["status"] == "unresolved"
    assert rows["W"]["company_id"] is None
    assert report["summary"]["name_based_matching_used"] is False
    assert report["summary"]["valuation_readiness_consumed"] is False


def test_real_snapshot_preserves_every_holding_symbol_and_resolves_nvda():
    root = Path(__file__).parents[1]
    report = json.loads((root / "data/generated/etf_identity_bridge/identity_bridge.json").read_text())
    assert report["summary"]["holding_symbol_count"] == len(report["records"])
    assert report["summary"]["holding_symbol_count"] == len(report["indexes"]["holding_symbol_to_position"])
    nvda = report["records"][report["indexes"]["holding_symbol_to_position"]["NVDA"]]
    assert nvda["security_id"] == "security:NASDAQ-NVDA"
    assert nvda["company_id"] == "company:US-CIK0001045810"
