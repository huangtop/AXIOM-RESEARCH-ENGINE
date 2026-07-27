import json
from pathlib import Path

from axiom_engine.identity.core import build_identity_mapping, normalize_cik, normalize_symbol, write_identity_mapping


def fixture_repo(tmp_path: Path, yahoo_symbols=None):
    (tmp_path / "data/universe").mkdir(parents=True)
    (tmp_path / "data/generated/company").mkdir(parents=True)
    companies = [{
        "company_id": "company:US-CIK0000000123",
        "legal_name": "Example Inc",
        "display_name": "Example",
        "primary_security_id": "security:NASDAQ-EXM",
        "metadata": {"cik": 123},
    }]
    securities = [{
        "security_id": "security:NASDAQ-EXM",
        "company_id": "company:US-CIK0000000123",
        "exchange": "NASDAQ",
        "ticker": "EXM",
        "currency": "USD",
        "primary_listing": True,
    }]
    (tmp_path / "data/universe/companies.json").write_text(json.dumps(companies))
    (tmp_path / "data/universe/securities.json").write_text(json.dumps(securities))
    payload = {"symbols": {s: {} for s in (yahoo_symbols or [])}}
    (tmp_path / "data/generated/company/yahoo_company_snapshot.json").write_text(json.dumps(payload))
    return tmp_path


def test_normalizers():
    assert normalize_symbol(" brk.b ") == "BRK-B"
    assert normalize_cik("CIK0000000123") == "0000000123"


def test_builds_canonical_indexes(tmp_path):
    report = build_identity_mapping(fixture_repo(tmp_path, ["EXM"]))
    assert report["indexes"]["symbol_to_company_id"]["EXM"] == "company:US-CIK0000000123"
    assert report["indexes"]["cik_to_company_id"]["0000000123"] == "company:US-CIK0000000123"


def test_marks_yahoo_cache_link(tmp_path):
    report = build_identity_mapping(fixture_repo(tmp_path, ["EXM"]))
    assert report["records"][0]["provider_links"]["yahoo"]["linked"] is True


def test_missing_yahoo_cache_is_not_identity_failure(tmp_path):
    report = build_identity_mapping(fixture_repo(tmp_path))
    assert report["records"][0]["identity_state"] == "resolved"
    assert report["records"][0]["provider_links"]["yahoo"]["linked"] is False


def test_reports_unmapped_yahoo_symbol(tmp_path):
    report = build_identity_mapping(fixture_repo(tmp_path, ["UNKNOWN"]))
    assert report["diagnostics"]["yahoo_unmapped_symbols"] == ["UNKNOWN"]


def test_write_outputs(tmp_path):
    report = build_identity_mapping(fixture_repo(tmp_path, ["EXM"]))
    output = tmp_path / "out/map.json"
    diagnostic = tmp_path / "out/diagnostic.json"
    write_identity_mapping(report, output, diagnostic)
    assert json.loads(output.read_text())["version"] == "V030.10.4"
    assert json.loads(diagnostic.read_text())["symbol_collisions"] == {}


def test_discovers_per_symbol_cache_when_canonical_snapshot_is_empty(tmp_path):
    root = fixture_repo(tmp_path)
    cache_root = root / "data/generated/provider_cache/yahoo/company_snapshot"
    cache_root.mkdir(parents=True)
    (cache_root / "EXM.json").write_text(json.dumps({"symbol": "EXM"}))
    report = build_identity_mapping(root)
    assert report["summary"]["yahoo_cached_symbol_count"] == 1
    assert report["summary"]["yahoo_canonical_symbol_count"] == 0
    assert report["summary"]["yahoo_per_symbol_cache_count"] == 1
    assert report["records"][0]["provider_links"]["yahoo"]["cache_present"] is True


def test_per_symbol_cache_uses_filename_when_payload_is_invalid(tmp_path):
    root = fixture_repo(tmp_path)
    cache_root = root / "data/generated/provider_cache/yahoo/company_snapshot"
    cache_root.mkdir(parents=True)
    (cache_root / "EXM.json").write_text("not-json")
    report = build_identity_mapping(root)
    assert report["summary"]["yahoo_cached_symbol_count"] == 1


def test_enriches_missing_universe_cik_from_registry_symbol(tmp_path):
    root = fixture_repo(tmp_path, ["BRK-B"])
    companies_path = root / "data/universe/companies.json"
    securities_path = root / "data/universe/securities.json"
    companies_path.write_text(json.dumps([{
        "company_id": "company:US-NYSE-BRK.B",
        "legal_name": "Berkshire Hathaway Inc.",
        "primary_security_id": "security:NYSE-BRK.B",
        "metadata": {},
    }]))
    securities_path.write_text(json.dumps([{
        "security_id": "security:NYSE-BRK.B",
        "company_id": "company:US-NYSE-BRK.B",
        "exchange": "NYSE",
        "ticker": "BRK.B",
        "currency": "USD",
        "primary_listing": True,
    }]))
    (root / "data/company_registry").mkdir(parents=True)
    (root / "data/company_registry/companies.json").write_text(json.dumps([{
        "company_id": "company:US-CIK0001067983",
        "metadata": {"cik": "0001067983"},
    }]))
    (root / "data/company_registry/securities.json").write_text(json.dumps([{
        "security_id": "security:NYSE-BRK-B",
        "company_id": "company:US-CIK0001067983",
        "ticker": "BRK.B",
    }]))

    report = build_identity_mapping(root)
    record = next(row for row in report["records"] if row["primary_symbol"] == "BRK-B")
    assert record["cik"] == "0001067983"
    assert record["identity_state"] == "resolved"
    assert report["indexes"]["cik_to_company_id"]["0001067983"] == "company:US-NYSE-BRK.B"
