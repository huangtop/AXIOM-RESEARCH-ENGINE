import json
from datetime import date
from pathlib import Path

import pytest

from axiom_engine.valuation_input import ValuationInputError, build_valuation_input_snapshot, write_valuation_input_snapshot


def write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixtures(tmp_path):
    write(tmp_path / "router.json", {"schema_version": "financial-source-router.v030.11.2", "companies": [
        {"company_id": "company:1", "cik": "1", "primary_symbol": "AAA", "display_name": "AAA Inc", "freshness_state": "current", "routing_state": "sec_primary_yahoo_fallback", "metrics": {"revenue": {"value": 10, "provider": "sec_companyfacts"}, "forward_eps": {"value": 2, "provider": "yahoo_finance"}}},
        {"company_id": "company:2", "cik": "2", "primary_symbol": "BBB", "display_name": "BBB Inc", "freshness_state": "stale", "routing_state": "sec_primary", "metrics": {"revenue": {"value": 20, "provider": "sec_companyfacts"}}}
    ]})
    write(tmp_path / "qa.json", {"schema_version": "bridge-qa-report.v030.11.3", "status": "pass"})
    write(tmp_path / "market.json", {"schema_version": "1.0", "symbols": {"AAA": {"close": "123.45", "session_date": "2026-07-24", "currency": "USD", "provider": "yahoo_finance"}}})


def build(tmp_path):
    fixtures(tmp_path)
    return build_valuation_input_snapshot(tmp_path, router_path="router.json", qa_path="qa.json", market_path="market.json", as_of=date(2026, 7, 27))


def test_merges_router_and_completed_close(tmp_path):
    report = build(tmp_path)
    aaa = report["companies"][0]
    assert aaa["company_id"] == "company:1"
    assert aaa["input_state"] == "ready"
    assert aaa["market"]["previous_close"]["value"] == 123.45
    assert aaa["financial_metrics"]["revenue"]["provider"] == "sec_companyfacts"


def test_keeps_financial_only_company(tmp_path):
    report = build(tmp_path)
    bbb = report["companies"][1]
    assert bbb["input_state"] == "financial_only"
    assert bbb["market"] == {}
    assert report["summary"]["missing_market_company_count"] == 1


def test_summary_and_capabilities(tmp_path):
    report = build(tmp_path)
    assert report["summary"]["valuation_ready_company_count"] == 1
    assert report["summary"]["provider_metric_counts"] == {"sec_companyfacts": 2, "yahoo_finance": 1}
    assert report["companies"][0]["capabilities"]["has_forward_eps"] is True


def test_requires_passing_bridge_qa(tmp_path):
    fixtures(tmp_path)
    write(tmp_path / "qa.json", {"status": "fail"})
    with pytest.raises(ValuationInputError):
        build_valuation_input_snapshot(tmp_path, router_path="router.json", qa_path="qa.json", market_path="market.json")


def test_invalid_market_is_diagnostic(tmp_path):
    fixtures(tmp_path)
    write(tmp_path / "market.json", {"symbols": {"AAA": {"close": "NaN", "session_date": "2026-07-24"}}})
    report = build_valuation_input_snapshot(tmp_path, router_path="router.json", qa_path="qa.json", market_path="market.json", as_of=date(2026, 7, 27))
    assert report["summary"]["invalid_market_company_count"] == 1
    assert report["companies"][0]["input_state"] == "financial_only"


def test_falls_back_to_legacy_previous_close_cache(tmp_path):
    fixtures(tmp_path)
    (tmp_path / "market.json").unlink()
    write(tmp_path / "data/cache/previous_closes.json", {"symbols": {"AAA": {"close": "99", "session_date": "2026-07-24"}}})
    report = build_valuation_input_snapshot(tmp_path, router_path="router.json", qa_path="qa.json", market_path="missing.json", as_of=date(2026, 7, 27))
    assert report["companies"][0]["market"]["previous_close"]["value"] == 99


def test_write_outputs_snapshot_and_diagnostic(tmp_path):
    report = build(tmp_path)
    output = tmp_path / "out/snapshot.json"
    diagnostic = tmp_path / "out/diagnostic.json"
    write_valuation_input_snapshot(report, output, diagnostic)
    assert json.loads(output.read_text())["schema_version"] == "valuation-input-snapshot.v030.12.0"
    assert json.loads(diagnostic.read_text())["missing_market"][0]["symbol"] == "BBB"
