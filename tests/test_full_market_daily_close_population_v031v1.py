from __future__ import annotations

import json

from scripts.refresh_yahoo_daily_close import load_primary_symbols


def test_population_uses_one_primary_active_security_per_company(tmp_path):
    root = tmp_path / "universe"
    root.mkdir()
    (root / "companies.json").write_text(json.dumps([
        {"company_id": "company:1", "primary_security_id": "security:1"},
        {"company_id": "company:2", "primary_security_id": None},
        {"company_id": "company:3", "primary_security_id": None},
    ]), encoding="utf-8")
    (root / "securities.json").write_text(json.dumps([
        {"security_id": "security:1", "company_id": "company:1", "ticker": "AAA", "status": "active", "primary_listing": True},
        {"security_id": "security:1b", "company_id": "company:1", "ticker": "AAA.W", "status": "active", "primary_listing": False},
        {"security_id": "security:2", "company_id": "company:2", "ticker": "BBB", "status": "active", "primary_listing": True},
        {"security_id": "security:3", "company_id": "company:3", "ticker": "OLD", "status": "inactive", "primary_listing": True},
    ]), encoding="utf-8")
    assert load_primary_symbols(root) == ["AAA", "BBB"]


def test_real_population_symbol_list_is_not_a_maintained_cohort():
    symbols = load_primary_symbols(__import__("pathlib").Path("data/universe"))
    assert len(symbols) > 6000
    assert "NVDA" in symbols
