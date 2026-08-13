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


def test_incremental_refresh_preserves_other_company_estimates(tmp_path: Path):
    snapshot = {"symbols": {"AAA": {"fetched_at": "2026-08-04", "currency": "USD", "forward_eps": "5"}}}
    (tmp_path / "data/generated/company").mkdir(parents=True)
    (tmp_path / "data/universe").mkdir(parents=True)
    (tmp_path / "data/estimate_data").mkdir(parents=True)
    (tmp_path / "data/generated/company/yahoo_company_snapshot.json").write_text(json.dumps(snapshot))
    (tmp_path / "data/universe/securities.json").write_text(json.dumps([{"ticker": "AAA", "company_id": "company:1", "security_id": "security:1"}]))
    (tmp_path / "data/estimate_data/consensus_estimates.json").write_text(json.dumps([
        {"company_id": "company:OTHER", "metric": "forward_eps", "value": "9"},
        {"company_id": "company:1", "metric": "forward_eps", "value": "1"},
    ]))
    rows = build_estimate_population(tmp_path)["estimates"]
    by_key = {(row["company_id"], row["metric"]): row for row in rows}
    assert by_key[("company:OTHER", "forward_eps")]["value"] == "9"
    assert by_key[("company:1", "forward_eps")]["value"] == "5"


def test_rejects_split_adjustment_mismatch_and_extreme_peg_growth(tmp_path: Path):
    snapshot = {"symbols": {
        "MU": {
            "fetched_at": "2026-07-28", "currency": "USD", "market_cap": "927276924928",
            "shares_outstanding": "1129393151", "forward_eps": "73.44403",
            "forward_pe": "5.340461", "forward_eps_growth": "13.685", "forward_revenue": "129779271370",
        },
    }}
    (tmp_path / "data/generated/company").mkdir(parents=True)
    (tmp_path / "data/universe").mkdir(parents=True)
    (tmp_path / "data/generated/company/yahoo_company_snapshot.json").write_text(json.dumps(snapshot))
    (tmp_path / "data/universe/securities.json").write_text(json.dumps([
        {"ticker": "MU", "company_id": "company:mu", "security_id": "security:mu"},
    ]))
    report = build_estimate_population(tmp_path)
    assert {row["metric"] for row in report["estimates"]} == {"forward_revenue"}
    reasons = {row["reason"] for row in report["diagnostics"]["rejected_symbols"]}
    assert "forward_eps_per_share_basis_inconsistent" in reasons
    assert "forward_eps_growth_per_share_basis_inconsistent" in reasons
