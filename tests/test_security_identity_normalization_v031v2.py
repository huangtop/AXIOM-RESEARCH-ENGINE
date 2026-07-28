from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.security_identity import build_security_identity_normalization


ROOT = Path(__file__).resolve().parents[1]


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "data/universe"
    root.mkdir(parents=True)
    (root / "companies.json").write_text(json.dumps([
        {"company_id": "company:operating"},
        {"company_id": "company:warrant-shell"},
        {"company_id": "company:preferred-shell"},
    ]), encoding="utf-8")
    (root / "securities.json").write_text(json.dumps([
        {"security_id": "security:common", "company_id": "company:operating", "ticker": "AAA", "exchange": "NYSE", "metadata": {"security_name": "Alpha Common Stock", "source_ids": ["source:1"]}},
        {"security_id": "security:warrant-linked", "company_id": "company:operating", "ticker": "AAA.W", "exchange": "NYSE", "metadata": {"security_name": "Alpha Warrants"}},
        {"security_id": "security:warrant", "company_id": "company:warrant-shell", "ticker": "BBB.W", "exchange": "NYSE", "metadata": {"security_name": "Beta Redeemable Warrants"}},
        {"security_id": "security:preferred", "company_id": "company:preferred-shell", "ticker": "CCC$A", "exchange": "NYSE", "metadata": {"security_name": "Gamma Series A Preferred Stock"}},
    ]), encoding="utf-8")
    return tmp_path


def test_instrument_only_shells_are_excluded_but_linked_warrant_does_not_exclude_company(tmp_path):
    report = build_security_identity_normalization(_fixture(tmp_path))
    by_company = {row["company_id"]: row for row in report["companies"]}
    by_security = {row["security_id"]: row for row in report["securities"]}
    assert by_company["company:operating"]["valuation_scope_status"] == "included"
    assert by_company["company:warrant-shell"]["reason_code"] == "NON_COMPANY_INSTRUMENT_ONLY"
    assert by_company["company:preferred-shell"]["valuation_scope_status"] == "excluded"
    assert by_security["security:warrant"]["instrument_type"] == "warrant"
    assert by_security["security:preferred"]["instrument_type"] == "preferred_stock"


def test_real_registry_is_classified_without_a_ticker_membership_list():
    report = build_security_identity_normalization(ROOT)
    assert report["summary"]["registry_company_count"] == 6464
    assert report["summary"]["registry_security_count"] == 7451
    assert report["summary"]["excluded_company_count"] > 0
    assert report["summary"]["instrument_type_counts"]["warrant"] > 0
    assert report["summary"]["instrument_type_counts"]["unit"] > 0
    assert report["summary"]["instrument_type_counts"]["preferred_stock"] > 0
