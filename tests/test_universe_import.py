from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.universe_import import (
    ConflictPolicy,
    ImportMode,
    UniverseImportConflictError,
    UniverseImportFormatError,
    UniverseImporter,
)


def seed_universe(root: Path) -> None:
    root.mkdir(parents=True)
    for filename in ("companies.json", "securities.json"):
        (root / filename).write_text("[]\n", encoding="utf-8")


def valid_payload() -> dict:
    return {
        "schema_version": "1.0.0",
        "companies": [
            {
                "company_id": "company:US-ACME",
                "legal_name": "Acme Corporation",
                "country": "US",
                "primary_security_id": "security:NASDAQ-ACME",
                "research_level": "basic",
            }
        ],
        "securities": [
            {
                "security_id": "security:NASDAQ-ACME",
                "company_id": "company:US-ACME",
                "exchange": "NASDAQ",
                "ticker": "ACME",
                "currency": "USD",
                "primary_listing": True,
            }
        ],
    }


def test_json_dry_run_does_not_write(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_universe(universe)
    source = tmp_path / "import.json"
    source.write_text(json.dumps(valid_payload()), encoding="utf-8")
    report = UniverseImporter(universe).import_file(source, dry_run=True)
    assert report.incoming_companies == 1
    assert report.output_companies == 1
    assert report.written_files == ()
    assert json.loads((universe / "companies.json").read_text()) == []


def test_json_import_writes_two_canonical_files(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_universe(universe)
    source = tmp_path / "import.json"
    source.write_text(json.dumps(valid_payload()), encoding="utf-8")
    report = UniverseImporter(universe).import_file(source, dry_run=False)
    assert {path.name for path in report.written_files} == {"companies.json", "securities.json"}
    assert (
        json.loads((universe / "companies.json").read_text())[0]["company_id"] == "company:US-ACME"
    )


def test_csv_contract_supports_aliases_and_metadata(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_universe(universe)
    source = tmp_path / "import.csv"
    source.write_text(
        "record_type,company_id,legal_name,country,research_level,aliases,metadata\n"
        'company,company:US-ACME,Acme Corporation,US,basic,Acme|ACME,"{""source"":""test""}"\n',
        encoding="utf-8",
    )
    bundle = UniverseImporter(universe).read(source)
    assert bundle.companies[0].aliases == ["Acme", "ACME"]
    assert bundle.companies[0].metadata == {"source": "test"}


def test_conflicting_merge_fails_by_default(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_universe(universe)
    payload = valid_payload()
    (universe / "companies.json").write_text(
        json.dumps([{**payload["companies"][0], "legal_name": "Old Acme"}])
    )
    source = tmp_path / "import.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(UniverseImportConflictError):
        UniverseImporter(universe).import_file(source)


def test_replace_conflict_policy_reports_warning(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_universe(universe)
    payload = valid_payload()
    (universe / "companies.json").write_text(
        json.dumps([{**payload["companies"][0], "legal_name": "Old Acme"}])
    )
    source = tmp_path / "import.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    report = UniverseImporter(
        universe, mode=ImportMode.MERGE, conflict_policy=ConflictPolicy.REPLACE
    ).import_file(source)
    assert report.warnings == ("replaced existing company: company:US-ACME",)


def test_invalid_security_reference_is_rejected_before_write(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_universe(universe)
    payload = valid_payload()
    payload["securities"][0]["company_id"] = "company:US-MISSING"
    source = tmp_path / "import.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Exception, match="references missing company"):
        UniverseImporter(universe).import_file(source, dry_run=False)
    assert json.loads((universe / "companies.json").read_text()) == []


def test_retired_assignment_key_is_rejected(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_universe(universe)
    source = tmp_path / "import.json"
    source.write_text(
        json.dumps({"companies": [], "securities": [], "valuation_profile_assignments": []})
    )
    with pytest.raises(UniverseImportFormatError, match="unknown top-level"):
        UniverseImporter(universe).read(source)
