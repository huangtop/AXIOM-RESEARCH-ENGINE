import json
from pathlib import Path

from axiom_engine.bridge_qa import build_bridge_qa, write_bridge_qa


def fixture(tmp_path: Path):
    identity = {"records": [{"company_id": "company:1", "cik": "0000000001", "primary_symbol": "AAA"}]}
    bridge = {
        "summary": {"canonical_fact_count": 1},
        "companies": [{"company_id": "company:1", "cik": "0000000001", "primary_symbol": "AAA", "facts": [{"financial_fact_id": "f1", "metric": "revenue", "value": 100, "unit": "currency", "currency": "USD", "period_end": "2025-12-31", "source": {"provider": "sec_companyfacts"}}]}],
    }
    timeline = {"companies": [{"company_id": "company:1", "cik": "0000000001", "primary_symbol": "AAA", "freshness_state": "current", "annual_periods": [{"period_end": "2025-12-31"}], "quarterly_periods": [], "ttm": {"state": "annual_proxy", "metrics": {"revenue": {"value": 100}}}, "instant_metrics": {}}]}
    router = {"summary": {"provider_metric_counts": {"sec_companyfacts": 1, "yahoo_finance": 1}, "missing_metric_count": 1}, "companies": [{"company_id": "company:1", "cik": "0000000001", "primary_symbol": "AAA", "metrics": {"revenue": {"value": 100, "provider": "sec_companyfacts", "confidence": "medium", "source_state": "primary", "fallback_reason": None}, "forward_eps": {"value": 5.5, "provider": "yahoo_finance", "confidence": "medium", "source_state": "fallback", "fallback_reason": "sec_metric_missing", "source_field": "forward_eps"}}}], "diagnostics": {"missing_metrics": [{"company_id": "company:1", "metric": "ebitda", "reason": "missing_in_sec_and_yahoo"}]}}
    for name, payload in (("i.json", identity), ("b.json", bridge), ("t.json", timeline), ("r.json", router)):
        (tmp_path / name).write_text(json.dumps(payload))


def build(tmp_path: Path):
    return build_bridge_qa(tmp_path, identity_path="i.json", bridge_path="b.json", timeline_path="t.json", router_path="r.json")


def test_clean_pipeline_passes(tmp_path):
    fixture(tmp_path)
    report = build(tmp_path)
    assert report["status"] == "pass"
    assert report["summary"]["critical_issue_count"] == 0


def test_identity_mismatch_fails(tmp_path):
    fixture(tmp_path)
    payload = json.loads((tmp_path / "r.json").read_text())
    payload["companies"][0]["primary_symbol"] = "BBB"
    (tmp_path / "r.json").write_text(json.dumps(payload))
    report = build(tmp_path)
    assert report["status"] == "fail"
    assert "symbol_mismatch" in report["summary"]["issue_code_counts"]


def test_sec_precedence_violation_fails(tmp_path):
    fixture(tmp_path)
    payload = json.loads((tmp_path / "r.json").read_text())
    payload["companies"][0]["metrics"]["revenue"] = {"value": 999, "provider": "yahoo_finance", "confidence": "medium", "source_state": "fallback", "fallback_reason": "sec_metric_missing", "source_field": "revenue_ttm"}
    payload["summary"]["provider_metric_counts"] = {"sec_companyfacts": 0, "yahoo_finance": 2}
    (tmp_path / "r.json").write_text(json.dumps(payload))
    report = build(tmp_path)
    assert report["status"] == "fail"
    assert "sec_precedence_violation" in report["summary"]["issue_code_counts"]


def test_incomplete_missing_reason_fails(tmp_path):
    fixture(tmp_path)
    payload = json.loads((tmp_path / "r.json").read_text())
    payload["diagnostics"]["missing_metrics"][0].pop("reason")
    (tmp_path / "r.json").write_text(json.dumps(payload))
    report = build(tmp_path)
    assert report["status"] == "fail"


def test_summary_count_mismatch_fails(tmp_path):
    fixture(tmp_path)
    payload = json.loads((tmp_path / "b.json").read_text())
    payload["summary"]["canonical_fact_count"] = 2
    (tmp_path / "b.json").write_text(json.dumps(payload))
    report = build(tmp_path)
    assert report["status"] == "fail"


def test_missing_currency_is_warning_only(tmp_path):
    fixture(tmp_path)
    payload = json.loads((tmp_path / "b.json").read_text())
    payload["companies"][0]["facts"][0]["currency"] = None
    (tmp_path / "b.json").write_text(json.dumps(payload))
    report = build(tmp_path)
    assert report["status"] == "pass"
    assert report["summary"]["warning_issue_count"] == 1


def test_write_report(tmp_path):
    fixture(tmp_path)
    report = build(tmp_path)
    write_bridge_qa(report, tmp_path / "out.json")
    assert json.loads((tmp_path / "out.json").read_text())["version"] == "V030.11.3"
