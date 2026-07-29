#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.etf_identity_bridge import build_etf_identity_bridge, write_etf_identity_bridge


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_etf_identity_bridge(root)
    write_etf_identity_bridge(report, root / "data/generated/etf_identity_bridge")
    print(report["summary"])


if __name__ == "__main__":
    main()
