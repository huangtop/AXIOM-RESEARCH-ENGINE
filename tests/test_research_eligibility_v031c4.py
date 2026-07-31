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
    catalog = json.loads((ROOT / "config/research_theme_catalog.v031c.5.1.json").read_text())
    _write(tmp_path, "config/research_eligibility.v031c.4.json", policy)
    _write(tmp_path, "config/research_theme_catalog.v031c.5.1.json", catalog)
    knowledge = [
        {"knowledge_id":"theme:ai_infrastructure","dimension":"theme","confidence":0.85,"derivation_type":"rule_inference","source_business_evidence_ids":["e:1"],"source_signal_ids":["signal:gpu","signal:ai"]},
        {"knowledge_id":"sector:ai_compute","dimension":"sector","confidence":0.80,"derivation_type":"rule_inference","source_business_evidence_ids":["e:1"],"source_signal_ids":["signal:gpu"]},
        {"knowledge_id":"cluster:accelerator_silicon","dimension":"cluster","confidence":0.75,"derivation_type":"rule_inference","source_business_evidence_ids":["e:1"],"source_signal_ids":["signal:gpu"]},
        {"knowledge_id":"supply_chain_role:designer","dimension":"supply_chain_role","confidence":0.70,"derivation_type":"observed_signal","source_business_evidence_ids":["e:1"],"source_signal_ids":["signal:designer"]},
    ]
    _write(tmp_path, "data/generated/knowledge_inference/knowledge_inference.json", {"schema_version":"multidimensional-knowledge-inference.v031c.3","records":[{"company_id":"company:1","status":"knowledge_available","knowledge":knowledge},{"company_id":"company:2","status":"business_evidence_unavailable","knowledge":[]}]})
    _write(tmp_path, "data/universe/securities.json", [{"company_id":"company:1","ticker":"TEST","primary_listing":True}])
    _write(tmp_path, "data/generated/security_identity/security_identity_normalization.json", {"companies":[{"company_id":"company:1","valuation_scope_status":"included"},{"company_id":"company:2","valuation_scope_status":"included"}]})
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
    assert record["decisions"]["news"]["reason_code"] == "NO_ENABLED_CATALOG_THEME"


def test_non_company_or_non_common_equity_is_excluded_from_every_research_action(tmp_path: Path):
    root = _fixture(tmp_path)
    identity_path = root / "data/generated/security_identity/security_identity_normalization.json"
    identity = json.loads(identity_path.read_text())
    identity["companies"][0]["valuation_scope_status"] = "excluded"
    identity_path.write_text(json.dumps(identity))
    record = build_research_eligibility(root)["records"][0]
    assert record["instrument_scope"]["operating_company_common_equity"] is False
    assert all(not decision["qualified"] for decision in record["decisions"].values())
    assert {decision["reason_code"] for decision in record["decisions"].values()} == {
        "OPERATING_COMPANY_COMMON_EQUITY_REQUIRED"
    }


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
    assert decision["unmet_reason_codes"] == ["NO_ENABLED_CATALOG_THEME", "SECTOR_SCORE_BELOW_THRESHOLD"]


def test_autonomous_theme_requires_ai_driving_evidence_not_generic_automaker(tmp_path: Path):
    root = _fixture(tmp_path)
    path = root / "data/generated/knowledge_inference/knowledge_inference.json"
    payload = json.loads(path.read_text())
    payload["records"][0]["knowledge"] = [
        {"knowledge_id":"theme:autonomous_vehicles","dimension":"theme","confidence":0.90,"derivation_type":"rule_inference","source_business_evidence_ids":["e:1"],"source_signal_ids":["technology:autonomous_driving"]},
        {"knowledge_id":"sector:autonomous_driving","dimension":"sector","confidence":0.85,"derivation_type":"rule_inference","source_business_evidence_ids":["e:1"],"source_signal_ids":["technology:autonomous_driving"]}
    ]
    path.write_text(json.dumps(payload))
    record = build_research_eligibility(root)["records"][0]
    assert record["matched_catalog_theme_ids"] == []
    assert record["decisions"]["news"]["reason_code"] == "NO_ENABLED_CATALOG_THEME"

    payload["records"][0]["knowledge"].append({
        "knowledge_id":"technology:full_self_driving","dimension":"technology","confidence":0.80,
        "derivation_type":"observed_signal","source_business_evidence_ids":["e:1"],"source_signal_ids":["technology:full_self_driving"]
    })
    path.write_text(json.dumps(payload))
    record = build_research_eligibility(root)["records"][0]
    assert record["matched_catalog_theme_ids"] == ["theme:autonomous_vehicles"]
    assert record["decisions"]["news"]["qualified"] is True


def test_research_rank_cap_is_automatic_not_ticker_membership(tmp_path: Path):
    root = _fixture(tmp_path)
    policy_path = root / "config/research_eligibility.v031c.4.json"
    policy = json.loads(policy_path.read_text())
    policy["research_universe"]["maximum_selected_companies"] = 1
    policy_path.write_text(json.dumps(policy))
    catalog_path = root / "config/research_theme_catalog.v031c.5.1.json"
    catalog = json.loads(catalog_path.read_text())
    catalog["tier_limits"] = {"active_intelligence":1,"supply_chain":1,"deep_research":1}
    catalog["tier_minimum_scores"] = {"active_intelligence":0,"supply_chain":0,"deep_research":0}
    catalog_path.write_text(json.dumps(catalog))
    payload = json.loads((root / "data/generated/knowledge_inference/knowledge_inference.json").read_text())
    payload["records"].append({**payload["records"][0], "company_id":"company:3"})
    _write(root, "data/generated/knowledge_inference/knowledge_inference.json", payload)
    _write(root, "data/universe/securities.json", [{"company_id":"company:1","ticker":"ONE","primary_listing":True},{"company_id":"company:3","ticker":"THREE","primary_listing":True}])
    _write(root, "data/generated/security_identity/security_identity_normalization.json", {"companies":[{"company_id":"company:1","valuation_scope_status":"included"},{"company_id":"company:3","valuation_scope_status":"included"}]})
    report = build_research_eligibility(root)
    assert report["summary"]["eligible_company_count"] == 2
    assert report["summary"]["selected_research_company_count"] == 1
    assert sum(row["research_universe_status"] == "eligible_not_selected" for row in report["records"]) == 1


def test_tier_minimum_score_does_not_force_fill_active_limit(tmp_path: Path):
    root = _fixture(tmp_path)
    catalog_path = root / "config/research_theme_catalog.v031c.5.1.json"
    catalog = json.loads(catalog_path.read_text())
    catalog["tier_limits"]["active_intelligence"] = 80
    catalog["tier_minimum_scores"]["active_intelligence"] = 1.0
    catalog_path.write_text(json.dumps(catalog))
    report = build_research_eligibility(root)
    assert report["summary"]["active_intelligence_company_count"] == 0
    assert report["summary"]["eligible_company_count"] == 1
    assert report["records"][0]["decisions"]["news"]["qualified"] is True
    assert report["records"][0]["decisions"]["news"]["enabled"] is False


def test_policy_rejects_ticker_membership(tmp_path: Path):
    root = _fixture(tmp_path)
    path = root / "config/research_eligibility.v031c.4.json"
    policy = json.loads(path.read_text())
    policy["tickers"] = ["NVDA"]
    path.write_text(json.dumps(policy))
    with pytest.raises(ResearchEligibilityError, match="membership is forbidden"):
        build_research_eligibility(root)


def test_theme_catalog_rejects_ticker_membership(tmp_path: Path):
    root = _fixture(tmp_path)
    path = root / "config/research_theme_catalog.v031c.5.1.json"
    catalog = json.loads(path.read_text())
    catalog["themes"][0]["symbols"] = ["TSLA"]
    path.write_text(json.dumps(catalog))
    with pytest.raises(ResearchEligibilityError, match="membership is forbidden"):
        build_research_eligibility(root)


def test_digital_assets_remain_classifiable_but_have_no_research_actions():
    catalog = json.loads((ROOT / "config/research_theme_catalog.v031c.5.1.json").read_text())
    theme = next(item for item in catalog["themes"] if item["theme_id"] == "theme:digital_assets")
    assert theme["actions"] == {"news": False, "etf": False, "supply_chain": False, "deep_research": False}


def test_real_population_remains_full_market_and_not_valuation_gated():
    report = build_research_eligibility(ROOT)
    assert report["summary"]["company_count"] == 6464
    assert report["summary"]["active_intelligence_company_count"] <= 80
    assert report["summary"]["supply_chain_company_count"] <= 200
    assert report["summary"]["deep_research_company_count"] <= 40
    assert report["policy"]["valuation_readiness_consumed"] is False
