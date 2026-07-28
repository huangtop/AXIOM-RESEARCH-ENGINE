from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from axiom_engine.knowledge_inference import KnowledgeInferenceError, build_knowledge_inference


ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    policy = json.loads((ROOT / "config/knowledge_inference.v031c.3.json").read_text())
    _write(tmp_path, "config/knowledge_inference.v031c.3.json", policy)
    _write(tmp_path, "data/generated/company_signals/company_signals.json", {
        "schema_version": "company-signals.v031c.2",
        "records": [{"company_id":"company:1","status":"signals_available","signals":[{
            "signal_id":"technology:high_bandwidth_memory","dimension":"technology","canonical_name":"High Bandwidth Memory","confidence":0.75,
            "source_business_evidence_ids":["business-evidence:1"]
        }]}, {"company_id":"company:2","status":"business_evidence_unavailable","signals":[]}]
    })
    return tmp_path


def test_chains_signal_to_cluster_sector_and_theme_with_rebuildable_paths(tmp_path: Path):
    report = build_knowledge_inference(_fixture(tmp_path), now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    knowledge = {row["knowledge_id"]: row for row in report["records"][0]["knowledge"]}
    assert {"cluster:high_bandwidth_memory", "sector:ai_memory", "theme:ai_infrastructure", "theme:artificial_intelligence"} <= knowledge.keys()
    path = knowledge["theme:ai_infrastructure"]["inference_paths"][0]
    assert path["rule_id"] == "rule:theme-ai-infrastructure"
    assert path["source_signal_ids"] == ["technology:high_bandwidth_memory"]
    assert path["source_business_evidence_ids"] == ["business-evidence:1"]


def test_company_without_signals_remains_present_and_unclassified(tmp_path: Path):
    record = build_knowledge_inference(_fixture(tmp_path))["records"][1]
    assert record["company_id"] == "company:2"
    assert record["status"] == "business_evidence_unavailable"
    assert record["knowledge"] == []


def test_rejects_ticker_membership_in_inference_policy(tmp_path: Path):
    root = _fixture(tmp_path)
    path = root / "config/knowledge_inference.v031c.3.json"
    policy = json.loads(path.read_text())
    policy["rules"][0]["tickers"] = ["NVDA"]
    path.write_text(json.dumps(policy))
    with pytest.raises(KnowledgeInferenceError, match="membership is forbidden"):
        build_knowledge_inference(root)


def test_real_population_preserves_full_registry_scope():
    report = build_knowledge_inference(ROOT)
    assert report["summary"]["company_count"] == 6464
    assert len(report["records"]) == 6464
    assert report["policy"]["contains_ticker_membership"] is False
