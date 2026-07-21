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


def seed_reference_data(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "classifications.json").write_text(
        json.dumps([
            {
                "classification_id": "sector:technology",
                "classification_type": "sector",
                "name": "Technology",
                "taxonomy_path": ["sector:technology"],
            }
        ]),
        encoding="utf-8",
    )
    (root / "valuation_profile_catalog.json").write_text(
        json.dumps([
            {
                "profile_id": "valuation_profile:mature-platform",
                "name": "Mature Platform",
                "description_zh_tw": "成熟平台",
                "lifecycle_stages": ["mature"],
                "profitability_states": ["profitable"],
                "model_policy": [
                    {"model_type": "forward_pe", "applicability": "primary", "priority": 1}
                ],
            }
        ]),
        encoding="utf-8",
    )
    for filename in ("companies.json", "securities.json", "valuation_profile_assignments.json"):
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
                "classification_ids": ["sector:technology"],
                "valuation_profile_ids": ["valuation_profile:mature-platform"],
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
        "valuation_profile_assignments": [
            {
                "assignment_id": "valuation_profile_assignment:US-ACME-primary",
                "company_id": "company:US-ACME",
                "profile_id": "valuation_profile:mature-platform",
                "applicability": "primary",
                "priority": 1,
                "method": "imported",
            }
        ],
    }


def test_json_dry_run_does_not_write(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_reference_data(universe)
    source = tmp_path / "import.json"
    source.write_text(json.dumps(valid_payload()), encoding="utf-8")

    report = UniverseImporter(universe).import_file(source, dry_run=True)

    assert report.incoming_companies == 1
    assert report.output_companies == 1
    assert report.written_files == ()
    assert json.loads((universe / "companies.json").read_text()) == []


def test_json_import_writes_all_canonical_files(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_reference_data(universe)
    source = tmp_path / "import.json"
    source.write_text(json.dumps(valid_payload()), encoding="utf-8")

    report = UniverseImporter(universe).import_file(source, dry_run=False)

    assert len(report.written_files) == 3
    assert json.loads((universe / "companies.json").read_text())[0]["company_id"] == "company:US-ACME"


def test_csv_contract_supports_pipe_lists_and_metadata(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_reference_data(universe)
    source = tmp_path / "import.csv"
    source.write_text(
        "record_type,company_id,legal_name,country,research_level,classification_ids,valuation_profile_ids,metadata\n"
        'company,company:US-ACME,Acme Corporation,US,basic,sector:technology,valuation_profile:mature-platform,"{""source"":""test""}"\n',
        encoding="utf-8",
    )

    bundle = UniverseImporter(universe).read(source)

    assert bundle.companies[0].classification_ids == ["sector:technology"]
    assert bundle.companies[0].metadata == {"source": "test"}


def test_conflicting_merge_fails_by_default(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_reference_data(universe)
    payload = valid_payload()
    (universe / "companies.json").write_text(
        json.dumps([{**payload["companies"][0], "legal_name": "Old Acme"}]),
        encoding="utf-8",
    )
    source = tmp_path / "import.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(UniverseImportConflictError):
        UniverseImporter(universe).import_file(source)


def test_replace_conflict_policy_reports_warning(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_reference_data(universe)
    payload = valid_payload()
    (universe / "companies.json").write_text(
        json.dumps([{**payload["companies"][0], "legal_name": "Old Acme"}]),
        encoding="utf-8",
    )
    source = tmp_path / "import.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    report = UniverseImporter(
        universe,
        mode=ImportMode.MERGE,
        conflict_policy=ConflictPolicy.REPLACE,
    ).import_file(source)

    assert report.warnings == ("replaced existing company: company:US-ACME",)


def test_invalid_reference_is_rejected_before_write(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_reference_data(universe)
    payload = valid_payload()
    payload["companies"][0]["classification_ids"] = ["sector:missing"]
    source = tmp_path / "import.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Exception, match="missing classification"):
        UniverseImporter(universe).import_file(source, dry_run=False)
    assert json.loads((universe / "companies.json").read_text()) == []


def test_unknown_json_key_is_rejected(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    seed_reference_data(universe)
    source = tmp_path / "import.json"
    source.write_text(json.dumps({"companies": [], "unexpected": []}), encoding="utf-8")

    with pytest.raises(UniverseImportFormatError, match="unknown top-level"):
        UniverseImporter(universe).read(source)
