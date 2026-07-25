from __future__ import annotations
import json
from pathlib import Path
from axiom_engine.valuation_readiness import build_valuation_readiness, validate_valuation_readiness


def dump(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture(tmp_path: Path):
    dump(tmp_path/"data/universe/companies.json", [
        {"company_id":"company:A","display_name":"A","primary_security_id":"security:A"},
        {"company_id":"company:B","display_name":"B","primary_security_id":"security:B"},
        {"company_id":"company:C","display_name":"C","primary_security_id":"security:C"},
    ])
    dump(tmp_path/"data/universe/securities.json", [
        {"security_id":"security:A","company_id":"company:A","ticker":"AAA","primary_listing":True},
        {"security_id":"security:B","company_id":"company:B","ticker":"BBB","primary_listing":True},
        {"security_id":"security:C","company_id":"company:C","ticker":"CCC","primary_listing":True},
    ])
    dump(tmp_path/"data/market/market_snapshots.json", [
        {"company_id":"company:A","price":100,"shares_outstanding":10},
        {"company_id":"company:B","price":20,"shares_outstanding":10},
    ])
    dump(tmp_path/"data/estimates/consensus_estimates.json", [
        {"company_id":"company:A","metric":"forward_eps","value":5},
        {"company_id":"company:A","metric":"forward_eps_growth","value":0.2},
        {"company_id":"company:A","metric":"forward_revenue","value":1000},
        {"company_id":"company:B","metric":"forward_eps","value":2},
    ])
    dump(tmp_path/"data/financials/financial_facts.json", [
        {"company_id":"company:A","concept":"ebitda","value":100},
        {"company_id":"company:A","concept":"stockholders_equity","value":500},
    ])


def test_build_all_companies_and_statuses(tmp_path):
    fixture(tmp_path)
    result=build_valuation_readiness(repository_root=tmp_path,write=True,strict=True)
    assert result["universe_company_count"] == 3
    rows=json.loads((tmp_path/"data/generated/valuation_readiness/company_readiness.json").read_text())
    by_id={row["company_id"]:row for row in rows}
    assert by_id["company:A"]["status"] == "ready"
    assert "forward_pe" in by_id["company:A"]["eligible_models"]
    assert by_id["company:B"]["status"] == "partial"
    assert by_id["company:C"]["status"] == "blocked"


def test_blocked_models_have_reason_codes(tmp_path):
    fixture(tmp_path)
    build_valuation_readiness(repository_root=tmp_path,write=True)
    rows=json.loads((tmp_path/"data/generated/valuation_readiness/company_readiness.json").read_text())
    for row in rows:
        for blocked in row["blocked_models"]:
            assert blocked["reasons"]
            assert all(reason["code"] for reason in blocked["reasons"])


def test_validator_passes_complete_artifacts(tmp_path):
    fixture(tmp_path)
    build_valuation_readiness(repository_root=tmp_path,write=True)
    result=validate_valuation_readiness(repository_root=tmp_path,strict=True)
    assert result["valid"] is True
    assert result["readiness_record_count"] == 3


def test_missing_model_input_does_not_crash_company(tmp_path):
    fixture(tmp_path)
    dump(tmp_path/"data/estimates/consensus_estimates.json", [{"company_id":"company:A","metric":"forward_eps","value":"bad"}])
    result=build_valuation_readiness(repository_root=tmp_path,write=True)
    assert result["universe_company_count"] == 3
