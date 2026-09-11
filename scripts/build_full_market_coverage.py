import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.full_market_coverage import (  # noqa: E402
    build_full_market_coverage,
    write_full_market_coverage,
)


def _load_symbols(path: Path) -> list[str]:
    return [
        line.strip().upper()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build full-market valuation cards, optionally for an incremental symbol set."
    )
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbols-file", type=Path)
    args = parser.parse_args()

    symbols = list(args.symbols)
    if args.symbols_file:
        symbols.extend(_load_symbols(args.symbols_file))
    symbols = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
    incremental = bool(symbols)

    root = ROOT
    output = root / "data/generated/full_market_coverage/full_market_coverage.json"
    report = build_full_market_coverage(
        root,
        symbols=symbols if incremental else None,
    )
    write_full_market_coverage(
        report,
        output,
        incremental=incremental,
    )
    print(report["summary"])


if __name__ == "__main__":
    main()
