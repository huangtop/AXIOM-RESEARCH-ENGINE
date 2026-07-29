#!/usr/bin/env python3
import argparse
from pathlib import Path

from axiom_engine.etf_engine_adapter import sync_etf_engine_cache


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = sync_etf_engine_cache(root, allow_live=args.allow_live, force=args.force)
    print(report)


if __name__ == "__main__":
    main()
