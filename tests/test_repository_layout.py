from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.repository_layout import CanonicalRepositoryLayout
from axiom_engine.universe_import import UniverseImporter
from axiom_engine.universe_repository import UniverseRepository


def _write(path: Path, payload: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_canonical(root: Path) -> None:
    _write(root / "universe/companies.json", [])
    _write(root / "universe/securities.json", [])


def test_layout_resolves_canonical_root(tmp_path: Path) -> None:
    _seed_canonical(tmp_path)
    layout = CanonicalRepositoryLayout.resolve(tmp_path)
    assert not layout.legacy
    assert layout.universe_dir == tmp_path / "universe"


def test_layout_preserves_legacy_universe_directory(tmp_path: Path) -> None:
    legacy = tmp_path / "universe"
    legacy.mkdir()
    layout = CanonicalRepositoryLayout.resolve(legacy)
    assert layout.legacy
    assert layout.universe_dir == legacy


def test_repository_loads_canonical_root(tmp_path: Path) -> None:
    _seed_canonical(tmp_path)
    repo = UniverseRepository.from_directory(tmp_path)
    assert repo.list_companies() == ()
    assert repo.list_securities() == ()


def test_importer_writes_only_universe_partition(tmp_path: Path) -> None:
    _seed_canonical(tmp_path)
    source = tmp_path / "import.json"
    source.write_text(
        json.dumps(
            {
                "companies": [{"company_id": "company:US-X", "legal_name": "X", "country": "US"}],
                "securities": [],
            }
        ),
        encoding="utf-8",
    )
    report = UniverseImporter(tmp_path).import_file(source, dry_run=False)
    assert {path.parent for path in report.written_files} == {tmp_path / "universe"}
    assert {path.name for path in report.written_files} == {"companies.json", "securities.json"}


def test_reconciliation_does_not_require_or_recreate_retired_sidecars(tmp_path: Path) -> None:
    _seed_canonical(tmp_path)
    source = tmp_path / "import.json"
    source.write_text(
        json.dumps({"companies": [], "securities": []}),
        encoding="utf-8",
    )

    UniverseImporter(tmp_path).import_file(source, dry_run=False)

    retired_paths = (
        tmp_path / "universe/classifications.json",
        tmp_path / "universe/valuation_profile_assignments.json",
        tmp_path / "universe/valuation_profile_catalog.json",
        tmp_path / "taxonomy/classifications.json",
        tmp_path / "taxonomy/valuation_profile_catalog.json",
    )
    assert all(not path.exists() for path in retired_paths)
