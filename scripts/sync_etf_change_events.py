from __future__ import annotations

import argparse
import json
from pathlib import Path

from axiom_engine.etf_change_events import (
    build_canonical_etf_change_events,
    sync_etf_change_cache,
    write_canonical_etf_change_events,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync and project ETF-ENGINE-V2 change events")
    parser.add_argument("--live", action="store_true", help="Allow HTTPS reads from ETF-ENGINE-V2")
    parser.add_argument("--force", action="store_true", help="Ignore the provider cache TTL")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sync = sync_etf_change_cache(root, allow_live=args.live, force=args.force)
    if sync.get("state") is None:
        print(json.dumps({"sync": sync, "projection": None}, ensure_ascii=False, indent=2))
        return
    report = build_canonical_etf_change_events(root)
    write_canonical_etf_change_events(
        report,
        root / "data/generated/canonical_etf_change_events",
    )
    print(json.dumps({"sync": sync, "projection": report["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
