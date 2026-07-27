from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.financial_bridge.core import FinancialBridgeError, build_financial_bridge, write_financial_bridge


def _write(root: Path, rel: str, payload) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _identity():
    return {
        "records": [{"company_id": "company:1", "cik": "0000000001", "primary_symbol": "AAA", "display_name": "A", "identity_state": "resolved"}],
        "indexes": {"cik_to_company_id": {"0000000001": "company:1"}},
    }


def _fact(**overrides):
    row = {
        "financial_fact_id": "fact:1",
        "company_id": "company:1",
        "metric": "revenue",
        "value": "100.50",
        "unit": "currency",
        "currency": "USD",
        "period_type": "duration",
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "fiscal_year": 2024,
        "fiscal_period": "FY",
        "statement": "income_statement",
        "form_type": "10-K",
        "accession_number": "x",
        "audited": True,
        "provenance_ids": ["p1"],
        "metadata": {"xbrl_tag": "Revenue"},
    }
    row.update(overrides)
    return row


def test_builds_canonical_company_snapshot(tmp_path: Path):
    _write(tmp_path, "facts.json", [_fact()])
    _write(tmp_path, "identity.json", _identity())
    report = build_financial_bridge(tmp_path, financial_facts_path="facts.json", identity_map_path="identity.json")
    assert report["summary"]["canonical_fact_count"] == 1
    company = report["companies"][0]
    assert company["primary_symbol"] == "AAA"
    assert company["metrics"]["revenue"]["value"] == 100.5


def test_selects_latest_fact_per_metric_without_dropping_history(tmp_path: Path):
    facts = [_fact(), _fact(financial_fact_id="fact:2", value="120", period_end="2025-12-31", fiscal_year=2025)]
    _write(tmp_path, "facts.json", facts)
    _write(tmp_path, "identity.json", _identity())
    report = build_financial_bridge(tmp_path, financial_facts_path="facts.json", identity_map_path="identity.json")
    company = report["companies"][0]
    assert company["fact_count"] == 2
    assert company["metrics"]["revenue"]["value"] == 120


def test_maps_company_by_cik_when_source_company_id_differs(tmp_path: Path):
    fact = _fact(company_id="legacy:1", metadata={"financial_facts_cik": "1", "xbrl_tag": "Revenue"})
    _write(tmp_path, "facts.json", [fact])
    _write(tmp_path, "identity.json", _identity())
    report = build_financial_bridge(tmp_path, financial_facts_path="facts.json", identity_map_path="identity.json")
    assert report["companies"][0]["company_id"] == "company:1"


def test_reports_unmapped_invalid_and_duplicate_rows(tmp_path: Path):
    facts = [_fact(), _fact(), _fact(financial_fact_id="fact:bad", company_id="unknown"), {"bad": True}]
    _write(tmp_path, "facts.json", facts)
    _write(tmp_path, "identity.json", _identity())
    report = build_financial_bridge(tmp_path, financial_facts_path="facts.json", identity_map_path="identity.json")
    assert report["summary"]["duplicate_fact_id_count"] == 1
    assert report["summary"]["unmapped_company_count"] == 1
    assert report["summary"]["invalid_row_count"] == 1


def test_rejects_missing_identity_map(tmp_path: Path):
    _write(tmp_path, "facts.json", [_fact()])
    with pytest.raises(FinancialBridgeError):
        build_financial_bridge(tmp_path, financial_facts_path="facts.json", identity_map_path="missing.json")


def test_writes_output_and_diagnostic(tmp_path: Path):
    _write(tmp_path, "facts.json", [_fact()])
    _write(tmp_path, "identity.json", _identity())
    report = build_financial_bridge(tmp_path, financial_facts_path="facts.json", identity_map_path="identity.json")
    write_financial_bridge(report, tmp_path / "out.json", tmp_path / "diag.json")
    assert json.loads((tmp_path / "out.json").read_text())["version"] == "V030.11.0"
    assert json.loads((tmp_path / "diag.json").read_text())["summary"]["canonical_company_count"] == 1
