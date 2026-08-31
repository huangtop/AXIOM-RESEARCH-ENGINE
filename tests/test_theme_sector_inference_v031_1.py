from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.theme_sector_inference import ThemeSectorInferenceService, build_theme_sector_inference
from axiom_engine.valuation_http import ValuationWSGIApp


ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture_root(tmp_path: Path, *, provenance: bool = True, relationship: bool = False) -> Path:
    policy = json.loads((ROOT / "config/theme_sector_inference.v031.1.json").read_text(encoding="utf-8"))
    _write(tmp_path, "config/theme_sector_inference.v031.1.json", policy)
    _write(tmp_path, "data/universe/companies.json", [{"company_id": "company:1", "display_name": "Optical Transceiver Holdings"}])
    _write(tmp_path, "data/universe/securities.json", [{"company_id": "company:1", "ticker": "TEST", "primary_listing": True}])
    _write(tmp_path, "data/company_registry/business_descriptions.json", [{"description_id": "description:1", "company_id": "company:1", "business_description": "Designs optical transceiver products.", "provenance_ids": ["filing:1"] if provenance else []}])
    _write(tmp_path, "data/company_registry/official_classifications.json", [])
    _write(tmp_path, "data/company_registry/provenance.json", [{"provenance_id": "filing:1"}])
    _write(tmp_path, "data/canonical/evidence.json", [{"evidence_id": "evidence:1", "review_status": "approved"}])
    _write(tmp_path, "data/industry/industry_exposures.json", [])
    _write(tmp_path, "data/industry/industry_edges.json", [{"edge_id": "edge:1", "source_entity_id": "company:1", "target_entity_id": "entity:ai-networking", "description_zh_tw": "AI networking optical transceiver supplier", "confidence": 0.8, "evidence_ids": ["evidence:1"] if relationship else []}])
    return tmp_path


def _get(app, path):
    observed = {}

    def start_response(status, headers):
        observed["status"] = status

    body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": path}, start_response))
    return observed, json.loads(body)


def test_real_population_is_complete_and_unverified_seed_relationships_are_rejected():
    payload = build_theme_sector_inference(ROOT)
    companies = json.loads((ROOT / "data/universe/companies.json").read_text())
    assert payload["summary"]["company_count"] == len(companies)
    assert payload["summary"]["selected_research_company_count"] == 0
    assert payload["summary"]["rejected_evidence_count"] == 10
    assert len(payload["records"]) == len(companies)


def test_description_requires_provenance_and_never_infers_from_company_name(tmp_path):
    payload = build_theme_sector_inference(_fixture_root(tmp_path, provenance=False))
    record = payload["records"][0]
    assert record["themes"] == []
    assert record["research_universe_status"] == "not_eligible"
    assert record["analysis_policy"]["news"]["enabled"] is False
    assert {row["code"] for row in payload["diagnostics"]["rejected_evidence"]} == {"DESCRIPTION_PROVENANCE_MISSING_OR_UNVERIFIED", "RELATIONSHIP_EVIDENCE_MISSING"}


def test_provenance_bearing_description_drives_theme_and_news_policy(tmp_path):
    payload = build_theme_sector_inference(_fixture_root(tmp_path))
    record = payload["records"][0]
    assert record["themes"][0]["theme_id"] == "theme:artificial-intelligence"
    assert record["sectors"][0]["sector_id"] == "sector:ai-networking"
    assert record["research_universe_status"] == "selected"
    assert record["analysis_policy"]["news"]["enabled"] is True
    assert record["analysis_policy"]["etf"]["enabled"] is False
    assert record["analysis_policy"]["industry_chain"]["enabled"] is False


def test_verified_relationship_enables_industry_chain_analysis(tmp_path):
    payload = build_theme_sector_inference(_fixture_root(tmp_path, provenance=False, relationship=True))
    record = payload["records"][0]
    assert record["analysis_policy"]["industry_chain"] == {"enabled": True, "reason_code": "VERIFIED_RELATIONSHIP_PRESENT"}
    assert payload["summary"]["rejected_evidence_count"] == 1


def test_http_exposes_generated_research_universe_and_company_policy(tmp_path):
    service = ThemeSectorInferenceService(root=_fixture_root(tmp_path))
    app = ValuationWSGIApp(theme_sector_service=service)
    listing_response, listing = _get(app, "/v1/research-universe")
    policy_response, policy = _get(app, "/v1/companies/TEST/research-policy")
    missing_response, missing = _get(app, "/v1/companies/MISSING/research-policy")
    assert listing_response["status"] == "200 OK"
    assert [row["ticker"] for row in listing["companies"]] == ["TEST"]
    assert policy_response["status"] == "200 OK"
    assert policy["ticker"] == "TEST"
    assert missing_response["status"] == "404 Not Found"
    assert missing["error"] == "company_not_found"
