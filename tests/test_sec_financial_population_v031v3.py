from __future__ import annotations

import json
from datetime import datetime, timezone

from axiom_engine.sec_financial_population import build_sec_financial_population


def _fact(label, value, unit="USD"):
    return {"label": label, "units": {unit: [{"val": value, "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "fy": 2025, "fp": "FY", "accn": "0001-26-1"}]}}


def _root(tmp_path):
    universe = tmp_path / "data/universe"
    universe.mkdir(parents=True)
    universe.joinpath("companies.json").write_text(json.dumps([
        {"company_id": "company:1", "metadata": {"cik": 1}},
        {"company_id": "company:excluded", "metadata": {"cik": 2}},
    ]), encoding="utf-8")
    identity = tmp_path / "data/generated/security_identity"
    identity.mkdir(parents=True)
    identity.joinpath("security_identity_normalization.json").write_text(json.dumps({"companies": [
        {"company_id": "company:1", "valuation_scope_status": "included"},
        {"company_id": "company:excluded", "valuation_scope_status": "excluded"},
    ]}), encoding="utf-8")
    cache = tmp_path / "data/generated/provider_cache/sec/companyfacts"
    cache.mkdir(parents=True)
    payload = {"facts": {"us-gaap": {
        "Revenues": _fact("Revenue", 1000),
        "NetIncomeLoss": _fact("Net income", 100),
        "StockholdersEquity": _fact("Equity", 500),
        "CommonStockSharesOutstanding": _fact("Shares", 100, "shares"),
    }}}
    cache.joinpath("CIK0000000001.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def test_population_consumes_only_normalized_valuation_scope_and_derives_book_value(tmp_path):
    report = build_sec_financial_population(_root(tmp_path), now=datetime(2026, 7, 28, tzinfo=timezone.utc))
    assert report["summary"]["cik_scope_company_count"] == 1
    assert report["summary"]["companies_with_financial_facts"] == 1
    facts = {row["metric"]: row for row in report["financial_facts"]}
    assert facts["revenue"]["value"] == "1000"
    assert facts["book_value_per_share"]["value"] == "5"
    assert facts["book_value_per_share"]["source"]["formula_version"] == "book_value_per_share.v031v.3"
    assert "ebitda" not in facts


def test_missing_companyfacts_is_diagnostic_not_zero(tmp_path):
    root = _root(tmp_path)
    (root / "data/generated/provider_cache/sec/companyfacts/CIK0000000001.json").unlink()
    report = build_sec_financial_population(root)
    assert report["financial_facts"] == []
    assert report["diagnostics"][0]["reason_code"] == "SEC_COMPANYFACTS_NOT_AVAILABLE"
