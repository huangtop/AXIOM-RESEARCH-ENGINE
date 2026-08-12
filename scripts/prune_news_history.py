#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.history_retention import prune_dated_snapshots  # noqa: E402


def main() -> None:
    config = json.loads((ROOT / "config/news_refresh.v1.json").read_text())
    removed = prune_dated_snapshots(
        ROOT / config["history_root"], retention_days=int(config["history_retention_days"])
    )
    print({"retention_days": config["history_retention_days"], "pruned_snapshots": removed})


if __name__ == "__main__":
    main()
