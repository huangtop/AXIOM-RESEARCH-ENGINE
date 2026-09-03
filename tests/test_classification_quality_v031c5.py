from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.classification_quality import build_classification_quality_audit


ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_audit_reports_requested_quality_dimensions(tmp_path: Path):
    policy = json.loads((ROOT / "config/classification_quality.v031c.5.json").read_text())
    _write(tmp_path, "config/classification_quality.v031c.5.json", policy)
    _write(tmp_path, "data/generated/canonical_business_evidence/business_evidence.json", [{"company_id":"company:1"}])
    _write(tmp_path, "data/generated/company_signals/company_signals.json", {"records":[{
        "company_id":"company:1","signals":[{"signal_id":"technology:artificial_intelligence","dimension":"technology"}]
    }, {"company_id":"company:2","signals":[]}]})
    _write(tmp_path, "data/generated/knowledge_inference/knowledge_inference.json", {"records":[{
        "company_id":"company:1","status":"knowledge_available","knowledge":[{
            "knowledge_id":"theme:ai_infrastructure","dimension":"theme","confidence":0.50,
            "derivation_type":"rule_inference","source_business_evidence_ids":["e:1"]
        }]
    }, {"company_id":"company:2","status":"signals_only","knowledge":[]}]})
    _write(tmp_path, "data/generated/research_relevance_gate/research_relevance_gate.json", {
        "summary":{"status_counts":{"priority_candidate":2}},
        "records":[{"company_id":"company:1","status":"priority_candidate","deep_inference_required":True},{"company_id":"company:2","status":"priority_candidate","deep_inference_required":True}]
    })
    _write(tmp_path, "data/generated/research_eligibility/research_eligibility.json", {
        "summary":{"selected_research_company_count":0},
        "records":[{"company_id":"company:1","research_universe_status":"not_eligible"},{"company_id":"company:2","research_universe_status":"not_eligible"}]
    })
    report = build_classification_quality_audit(tmp_path)
    flags = report["summary"]["flag_counts"]
    assert flags["LOW_CONFIDENCE_CLASSIFICATION"] == 1
    assert flags["OVERBROAD_AI_CLASSIFICATION"] == 1
    assert flags["SINGLE_EVIDENCE_CLASSIFICATION"] == 1
    assert flags["SIGNALS_WITHOUT_UPPER_CLASSIFICATION"] == 1
    assert report["summary"]["business_evidence_coverage_ratio"] == 0.5
