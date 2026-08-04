import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.full_market_coverage import (  # noqa: E402
    build_full_market_coverage,
    write_full_market_coverage,
)


def main() -> None:
    root = ROOT
    report = build_full_market_coverage(root)
    write_full_market_coverage(report, root / "data/generated/full_market_coverage/full_market_coverage.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
