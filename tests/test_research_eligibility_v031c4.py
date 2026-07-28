from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.research_eligibility import ResearchEligibilityError, build_research_eligibility


ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    policy = json.loads((ROOT / "config/research_eligibility.v031c.4.json").read_text())
    _write(tmp_path, "config/research_eligibility.v031c.4.json", policy)
    knowledge = [
        {"knowledge_id":"theme:ai_infrastructure","dimension":"theme","confidence":0.85,"derivation_type":"rule_inference","source_business_evidence_ids":["e:1"],"source_signal_ids":["signal:gpu","signal:ai"]},
        {"knowledge_id":"sector:ai_compute","dimension":"sector","confidence":0.80,"derivation_type":"rule_inference","source_business_evidence_ids":["e:1"],"source_signal_ids":["signal:gpu"]},
        {"knowledge_id":"cluster:accelerator_silicon","dimension":"cluster","confidence":0.75,"derivation_type":"rule_inference","source_business_evidence_ids":["e:1"],"source_signal_ids":["signal:gpu"]},
        {"knowledge_id":"supply_chain_role:designer","dimension":"supply_chain_role","confidence":0.70,"derivation_type":"observed_signal","source_business_evidence_ids":["e:1"],"source_signal_ids":["signal:designer"]},
    ]
    _write(tmp_path, "data/generated/knowledge_inference/knowledge_inference.json", {"schema_version":"multidimensional-knowledge-inference.v031c.3","records":[{"company_id":"company:1","status":"knowledge_available","knowledge":knowledge},{"company_id":"company:2","status":"business_evidence_unavailable","knowledge":[]}]})
    _write(tmp_path, "data/universe/securities.json", [{"company_id":"company:1","ticker":"TEST","primary_listing":True}])
    _write(tmp_path, "data/generated/security_identity/security_identity_normalization.json", {"companies":[{"company_id":"company:1","valuation_scope_status":"included"},{"company_id":"company:2","valuation_scope_status":"excluded"}]})
    return tmp_path


def test_independent_actions_are_enabled_from_knowledge_not_valuation(tmp_path: Path):
    report = build_research_eligibility(_fixture(tmp_path))
    record = report["records"][0]
    assert record["ticker"] == "TEST"
    assert all(decision["enabled"] for decision in record["decisions"].values())
    assert record["research_universe_status"] == "selected"
    assert report["policy"]["valuation_readiness_consumed"] is False


def test_unavailable_company_remains_present_with_reason_codes(tmp_path: Path):
    record = build_research_eligibility(_fixture(tmp_path))["records"][1]
    assert record["research_universe_status"] == "not_eligible"
    assert record["decisions"]["news"]["reason_code"] == "THEME_SCORE_BELOW_THRESHOLD"
    assert "ACTIVE_COMMON_EQUITY_UNAVAILABLE" in record["decisions"]["etf"]["unmet_reason_codes"]


def test_generic_ai_theme_without_sector_is_not_research_eligible(tmp_path: Path):
    root = _fixture(tmp_path)
    path = root / "data/generated/knowledge_inference/knowledge_inference.json"
    payload = json.loads(path.read_text())
    payload["records"][0]["knowledge"] = [{
        "knowledge_id":"theme:artificial_intelligence","dimension":"theme","confidence":0.90,
        "derivation_type":"rule_inference","source_business_evidence_ids":["e:1"]
    }]
    path.write_text(json.dumps(payload))
    decision = build_research_eligibility(root)["records"][0]["decisions"]["news"]
    assert decision["enabled"] is False
    assert decision["unmet_reason_codes"] == ["SECTOR_SCORE_BELOW_THRESHOLD"]


def test_research_rank_cap_is_automatic_not_ticker_membership(tmp_path: Path):
    root = _fixture(tmp_path)
    policy_path = root / "config/research_eligibility.v031c.4.json"
    policy = json.loads(policy_path.read_text())
    policy["research_universe"]["maximum_selected_companies"] = 1
    policy_path.write_text(json.dumps(policy))
    payload = json.loads((root / "data/generated/knowledge_inference/knowledge_inference.json").read_text())
    payload["records"].append({**payload["records"][0], "company_id":"company:3"})
    _write(root, "data/generated/knowledge_inference/knowledge_inference.json", payload)
    _write(root, "data/universe/securities.json", [{"company_id":"company:1","ticker":"ONE","primary_listing":True},{"company_id":"company:3","ticker":"THREE","primary_listing":True}])
    _write(root, "data/generated/security_identity/security_identity_normalization.json", {"companies":[{"company_id":"company:1","valuation_scope_status":"included"},{"company_id":"company:3","valuation_scope_status":"included"}]})
    report = build_research_eligibility(root)
    assert report["summary"]["eligible_company_count"] == 2
    assert report["summary"]["selected_research_company_count"] == 1
    assert sum(row["research_universe_status"] == "eligible_not_selected" for row in report["records"]) == 1


def test_policy_rejects_ticker_membership(tmp_path: Path):
    root = _fixture(tmp_path)
    path = root / "config/research_eligibility.v031c.4.json"
    policy = json.loads(path.read_text())
    policy["tickers"] = ["NVDA"]
    path.write_text(json.dumps(policy))
    with pytest.raises(ResearchEligibilityError, match="membership is forbidden"):
        build_research_eligibility(root)


def test_real_population_remains_full_market_and_not_valuation_gated():
    report = build_research_eligibility(ROOT)
    assert report["summary"]["company_count"] == 6464
    assert report["policy"]["valuation_readiness_consumed"] is False
