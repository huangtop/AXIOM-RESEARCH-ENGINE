from __future__ import annotations

import argparse
from pathlib import Path

from axiom_engine.us_universe_sources import OfficialUSUniverseSourceClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an official US listing source snapshot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--user-agent",
        required=True,
        help="Descriptive contact user agent, for example 'AXIOM research@example.com'",
    )
    args = parser.parse_args()
    snapshot = OfficialUSUniverseSourceClient(user_agent=args.user_agent).build_snapshot()
    target = snapshot.write_json(args.output)
    print(f"wrote {len(snapshot.records)} records to {target}")


if __name__ == "__main__":
    main()
