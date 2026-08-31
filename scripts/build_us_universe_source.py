from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.universe_import import ImportMode, UniverseImporter  # noqa: E402
from axiom_engine.universe_repository import UniverseRepository  # noqa: E402
from axiom_engine.us_universe_import import transform_us_source_records  # noqa: E402
from axiom_engine.us_universe_sources import OfficialUSUniverseSourceClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an official US listing source snapshot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--universe-dir", type=Path, default=Path("data/universe"))
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Reconcile the canonical universe after writing the official snapshot",
    )
    parser.add_argument("--write", action="store_true", help="Write canonical changes")
    parser.add_argument(
        "--user-agent",
        required=True,
        help="Descriptive contact user agent, for example 'AXIOM research@example.com'",
    )
    args = parser.parse_args()
    snapshot = OfficialUSUniverseSourceClient(user_agent=args.user_agent).build_snapshot()
    target = snapshot.write_json(args.output)
    print(f"wrote {len(snapshot.records)} records to {target}")
    if args.reconcile:
        existing = UniverseRepository.from_directory(args.universe_dir)
        before_companies = {item.company_id for item in existing.list_companies()}
        before_securities = {item.security_id for item in existing.list_securities()}
        bundle = transform_us_source_records(snapshot.records)
        after_companies = {item.company_id for item in bundle.companies}
        after_securities = {item.security_id for item in bundle.securities}
        UniverseImporter(args.universe_dir, mode=ImportMode.REPLACE).apply(
            bundle, source_path=target, dry_run=not args.write
        )
        dangling_count = 0
        if args.write:
            dangling_count = len(
                UniverseRepository.from_directory(args.universe_dir).integrity_errors()
            )
        print(json.dumps({
            "before_company_count": len(before_companies),
            "before_security_count": len(before_securities),
            "official_current_count": len(snapshot.records),
            "added_company_count": len(after_companies - before_companies),
            "added_security_count": len(after_securities - before_securities),
            "deleted_company_count": len(before_companies - after_companies),
            "deleted_security_count": len(before_securities - after_securities),
            "after_company_count": len(after_companies),
            "after_security_count": len(after_securities),
            "dangling_reference_count": dangling_count,
            "dry_run": not args.write,
        }, indent=2))


if __name__ == "__main__":
    main()
