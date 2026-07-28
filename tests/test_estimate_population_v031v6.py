import json
from pathlib import Path

from axiom_engine.estimate_population import build_estimate_population


def test_projects_provider_evidence_into_canonical_estimates(tmp_path: Path):
    snapshot = {"symbols": {"AAA": {"fetched_at": "2026-07-28T00:00:00+00:00", "currency": "USD", "forward_eps": "5", "forward_eps_growth": "0.2", "forward_revenue": "1000", "ebitda_ttm": "80"}}}
    securities = [{"ticker": "AAA", "company_id": "company:1", "security_id": "security:1"}]
    (tmp_path / "data/generated/company").mkdir(parents=True)
    (tmp_path / "data/universe").mkdir(parents=True)
    (tmp_path / "data/generated/company/yahoo_company_snapshot.json").write_text(json.dumps(snapshot))
    (tmp_path / "data/universe/securities.json").write_text(json.dumps(securities))
    report = build_estimate_population(tmp_path)
    assert {row["metric"] for row in report["estimates"]} == {"forward_eps", "forward_eps_growth", "forward_revenue", "ebitda_ttm"}
    assert all(row["provider"] == "yahoo_finance" and row["source_record_id"] for row in report["estimates"])


def test_does_not_emit_missing_or_unresolved_estimates(tmp_path: Path):
    snapshot = {"symbols": {"UNKNOWN": {"forward_eps": "4"}, "AAA": {"forward_eps": None}}}
    (tmp_path / "data/generated/company").mkdir(parents=True)
    (tmp_path / "data/universe").mkdir(parents=True)
    (tmp_path / "data/generated/company/yahoo_company_snapshot.json").write_text(json.dumps(snapshot))
    (tmp_path / "data/universe/securities.json").write_text(json.dumps([{"ticker": "AAA", "company_id": "c1", "security_id": "s1"}]))
    assert build_estimate_population(tmp_path)["estimates"] == []
