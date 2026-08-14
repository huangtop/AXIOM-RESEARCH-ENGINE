from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.company_analysis import build_company_analyses
from axiom_engine.company_signals import build_company_signals


ROOT = Path(__file__).resolve().parents[1]
IDS = {
    "NVDA": "company:US-CIK0001045810",
    "SILC": "company:US-CIK0000916793",
    "FLEX": "company:US-CIK0000866374",
}
TEN_TICKERS = {"NVDA", "SILC", "FLEX", "MU", "COHU", "SMCI", "HPE", "JBL", "ADI", "GFS"}


def _records():
    company_ids = set(IDS.values())
    signals = build_company_signals(ROOT, company_ids=company_ids)
    report = build_company_analyses(ROOT, company_ids=company_ids, signals_payload=signals)
    return {row["ticker"]: row for row in report["records"]}


def test_generates_traceable_analysis_without_company_specific_policy():
    policy = json.loads((ROOT / "config/company_analysis.v1.json").read_text())
    serialized = json.dumps(policy).upper()
    assert not any(ticker in serialized for ticker in IDS)
    records = _records()
    assert set(records) == set(IDS)
    for row in records.values():
        assert row["generation_mode"] == "deterministic_evidence_template"
        assert row["summary"]["evidence_ids"]
        assert row["summary"]["signal_ids"]
        assert row["offerings"]


def test_flex_is_manufacturing_and_not_ai_compute():
    flex = _records()["FLEX"]
    text = flex["summary"]["text"]
    assert "電子製造" in text
    assert "GPU" not in text
    assert "製造" in flex["classification"]["supply_chain_role"]


def test_silc_sells_networking_infrastructure():
    silc = _records()["SILC"]
    assert "高效能網路與資料基礎設施" in silc["summary"]["text"]
    assert "AI 核心算力" not in silc["summary"]["text"]


def test_nvda_has_gpu_and_data_center_in_evidence_backed_summary():
    nvda = _records()["NVDA"]
    assert "GPU" in nvda["summary"]["text"]
    assert "資料中心" in nvda["summary"]["text"]
    assert nvda["classification"]["sector"] == "AI 核心算力"


def test_expands_to_ten_in_scope_technology_companies_without_ticker_rules():
    securities = json.loads((ROOT / "data/universe/securities.json").read_text())
    company_ids = {
        str(row["company_id"])
        for row in securities
        if str(row.get("ticker") or "").upper() in TEN_TICKERS
    }
    signals = build_company_signals(ROOT, company_ids=company_ids)
    report = build_company_analyses(ROOT, company_ids=company_ids, signals_payload=signals)
    records = {row["ticker"]: row for row in report["records"]}
    assert set(records) == TEN_TICKERS
    assert report["scope"]["contains_company_membership"] is False
    for row in records.values():
        assert row["summary"]["evidence_ids"]
        assert row["offerings"]
        overview = json.loads(
            (ROOT / "data/generated/company_overview/per-company" / f"{row['ticker']}.json").read_text()
        )
        assert overview["classification_lock"] == {
            "status": "locked",
            "update_mode": "manual_override_only",
        }
        assert overview["classification_source"] in {
            "curated_core_override",
            "reviewed_automatic_inference",
        }


def test_excludes_company_when_supply_chain_decision_is_disabled(tmp_path: Path):
    company_ids = {"company:US-CIK0001321655"}  # Palantir is currently company-page only.
    signals = build_company_signals(ROOT, company_ids=company_ids)
    report = build_company_analyses(ROOT, company_ids=company_ids, signals_payload=signals)
    assert report["records"] == []


def test_excludes_legacy_lock_without_reviewed_evidence_source():
    securities = json.loads((ROOT / "data/universe/securities.json").read_text())
    company_ids = {
        str(row["company_id"])
        for row in securities
        if str(row.get("ticker") or "").upper() == "VRT"
    }
    signals = build_company_signals(ROOT, company_ids=company_ids)
    report = build_company_analyses(ROOT, company_ids=company_ids, signals_payload=signals)
    assert report["records"] == []
