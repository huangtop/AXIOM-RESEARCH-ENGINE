from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from axiom_engine.universe_import import ImportMode, UniverseImporter
from axiom_engine.universe_repository import UniverseRepository


def migrate(source: Path, data_root: Path, legacy_universe: Path) -> dict[str, object]:
    universe_dir = data_root / "universe"
    taxonomy_dir = data_root / "taxonomy"
    universe_dir.mkdir(parents=True, exist_ok=True)
    taxonomy_dir.mkdir(parents=True, exist_ok=True)

    for filename in ("classifications.json", "valuation_profile_catalog.json"):
        source_path = legacy_universe / filename
        target_path = taxonomy_dir / filename
        if not target_path.exists():
            if not source_path.is_file():
                raise FileNotFoundError(f"required taxonomy file is missing: {source_path}")
            shutil.copy2(source_path, target_path)

    report = UniverseImporter(data_root, mode=ImportMode.REPLACE).import_file(
        source, dry_run=False
    )
    repo = UniverseRepository.from_directory(data_root, validate=True)
    return {
        "companies": len(repo.list_companies()),
        "securities": len(repo.list_securities()),
        "written_files": [str(path) for path in report.written_files],
        "layout": "canonical",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate official Universe into canonical data layout")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--legacy-universe", type=Path, default=Path("data/universe"))
    args = parser.parse_args()
    print(json.dumps(migrate(args.source, args.data_root, args.legacy_universe), indent=2))


if __name__ == "__main__":
    main()
