from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path

from axiom_engine.canonical_valuation import run_batch_valuation, validate_canonical_valuation, valuation_readiness


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _bundle(root: Path, count: int = 1) -> tuple[Path, Path]:
    fdir, edir = root / "financial", root / "estimate"
    facts, estimates, assumptions = [], [], []
    for n in range(count):
        cid = f"company:US-T{n:03d}"
        for metric, value, statement, period_type in [
            ("free_cash_flow", "1000000000", "cash_flow", "duration"),
            ("cash_and_cash_equivalents", "500000000", "balance_sheet", "instant"),
            ("total_debt", "200000000", "balance_sheet", "instant"),
            ("diluted_shares_outstanding", "100000000", "operating_metric", "instant"),
        ]:
            row = {"financial_fact_id": f"financial_fact:{n}:{metric}", "company_id": cid, "metric": metric, "value": value, "unit": "shares" if metric == "diluted_shares_outstanding" else "currency", "period_type": period_type, "period_end": "2025-12-31", "fiscal_year": 2025, "fiscal_period": "FY", "statement": statement, "provenance_ids": [f"provenance:f:{n}"]}
            if row["unit"] == "currency": row["currency"] = "USD"
            if period_type == "duration": row["period_start"] = "2025-01-01"
            facts.append(row)
        estimates.append({"estimate_id": f"estimate:{n}:eps", "company_id": cid, "metric": "eps_diluted", "value": "5", "unit": "currency", "currency": "USD", "period_end": "2027-12-31", "fiscal_year": 2027, "fiscal_period": "FY", "estimate_kind": "consensus_mean", "provenance_ids": [f"provenance:e:{n}"]})
        for metric, value in [("fcf_growth_rate", "0.08"), ("discount_rate", "0.10"), ("terminal_growth_rate", "0.03"), ("forward_pe", "20")]:
            assumptions.append({"assumption_id": f"forward_assumption:{n}:{metric}", "company_id": cid, "metric": metric, "value": value, "unit": "ratio", "effective_date": "2026-07-23", "horizon_years": 5, "assumption_type": "research_assumption", "status": "approved", "provenance_ids": [f"provenance:a:{n}"]})
    _write(fdir / "financial_facts.json", facts)
    _write(edir / "estimates.json", estimates)
    _write(edir / "forward_assumptions.json", assumptions)
    return fdir, edir


def test_dry_run_default(tmp_path):
    fdir, edir = _bundle(tmp_path)
    out = tmp_path / "out"
    report = run_batch_valuation(financial_dir=fdir, estimate_dir=edir, output_dir=out, as_of_date=date(2026, 7, 23))
    assert report.completed == 1 and not out.exists()


def test_writes_and_validates_bundle(tmp_path):
    fdir, edir = _bundle(tmp_path)
    out = tmp_path / "out"
    report = run_batch_valuation(financial_dir=fdir, estimate_dir=edir, output_dir=out, as_of_date=date(2026, 7, 23), dry_run=False)
    assert report.completed == 1
    stats = validate_canonical_valuation(out)
    assert stats == {"company_count": 1, "completed": 1, "partial": 0, "unavailable": 0}


def test_completed_result_has_two_models(tmp_path):
    fdir, edir = _bundle(tmp_path)
    out = tmp_path / "out"
    run_batch_valuation(financial_dir=fdir, estimate_dir=edir, output_dir=out, dry_run=False)
    result = json.loads((out / "valuation_results.json").read_text())[0]
    assert result["status"] == "completed"
    assert {x["model_name"] for x in result["models"]} == {"discounted_cash_flow", "forward_earnings_multiple"}
    assert float(result["blended_fair_value_per_share"]) > 0


def test_100_company_acceptance_fixture(tmp_path):
    fdir, edir = _bundle(tmp_path, 100)
    readiness = valuation_readiness(financial_dir=fdir, estimate_dir=edir, required_company_count=100)
    assert readiness.acceptance_passed
    assert readiness.companies_ready == 100
    report = run_batch_valuation(financial_dir=fdir, estimate_dir=edir)
    assert report.companies_requested == 100 and report.completed == 100


def test_proposed_assumptions_are_not_used(tmp_path):
    fdir, edir = _bundle(tmp_path)
    assumptions = json.loads((edir / "forward_assumptions.json").read_text())
    assumptions[0]["status"] = "proposed"
    _write(edir / "forward_assumptions.json", assumptions)
    readiness = valuation_readiness(financial_dir=fdir, estimate_dir=edir, required_company_count=1)
    assert not readiness.acceptance_passed
    assert "discounted_cash_flow" not in readiness.items[0].ready_models


def test_no_current_price_or_upside_in_output(tmp_path):
    fdir, edir = _bundle(tmp_path)
    out = tmp_path / "out"
    run_batch_valuation(financial_dir=fdir, estimate_dir=edir, output_dir=out, dry_run=False)
    text = (out / "valuation_results.json").read_text().lower()
    assert "current_price" not in text
    assert "upside" not in text
    assert "analyst_target" not in text


def test_no_legacy_valuation_imports():
    root = Path(__file__).parents[1] / "src" / "axiom_engine" / "canonical_valuation"
    forbidden = {"services.valuation", "legacy_valuation", "yfinance", "research_report"}
    imports = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(x.name for x in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module: imports.add(node.module)
    assert not any(any(item in name for item in forbidden) for name in imports)


def test_deterministic_company_order(tmp_path):
    fdir, edir = _bundle(tmp_path, 3)
    out = tmp_path / "out"
    run_batch_valuation(financial_dir=fdir, estimate_dir=edir, output_dir=out, dry_run=False)
    rows = json.loads((out / "valuation_results.json").read_text())
    assert [row["company_id"] for row in rows] == sorted(row["company_id"] for row in rows)
