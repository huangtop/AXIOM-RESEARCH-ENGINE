import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generated_overviews_publish_every_evidence_backed_theme_sector_path():
    knowledge = json.loads(
        (ROOT / "data/generated/knowledge_inference/knowledge_inference.json").read_text()
    )
    index = json.loads((ROOT / "data/generated/company_overview/index.json").read_text())
    identity = json.loads(
        (ROOT / "data/generated/security_identity/security_identity_normalization.json").read_text()
    )
    eligible_company_ids = {
        str(row["company_id"])
        for row in identity.get("securities") or []
        if row.get("valuation_eligible") is True
    }
    expected_company_ids = {
        str(row["company_id"])
        for row in knowledge.get("records") or []
        if any(
            item.get("dimension") == "theme" and item.get("source_business_evidence_ids")
            for item in row.get("knowledge") or []
        )
        and any(
            item.get("dimension") == "sector" and item.get("source_business_evidence_ids")
            for item in row.get("knowledge") or []
        )
    }
    published_company_ids = {
        json.loads(path.read_text())["company_id"]
        for path in (ROOT / "data/generated/company_overview/per-company").glob("*.json")
    }
    assert expected_company_ids & eligible_company_ids <= published_company_ids
    assert len(published_company_ids) == index["summary"]["company_count"]
    assert index["summary"]["classified_count"] == index["summary"]["company_count"]
    assert index["summary"]["company_count"] >= 120


def test_mu_uses_specific_ai_memory_path_instead_of_generic_semiconductors():
    overview = json.loads(
        (ROOT / "data/generated/company_overview/per-company/MU.json").read_text()
    )
    assert overview["path"]["theme"]["id"] == "theme:ai_infrastructure"
    assert overview["path"]["sector"]["id"] == "sector:ai_memory"
    assert overview["evidence"][0]["form"] == "10-K"
