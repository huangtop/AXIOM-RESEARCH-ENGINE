from pathlib import Path

from axiom_engine.full_market_coverage import build_full_market_coverage, write_full_market_coverage


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_full_market_coverage(root)
    write_full_market_coverage(report, root / "data/generated/full_market_coverage/full_market_coverage.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
