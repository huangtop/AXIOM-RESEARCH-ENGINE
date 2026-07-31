#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.publication_gate import build_publication_catalog, write_publication_catalog


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_publication_catalog(root)
    write_publication_catalog(report, root / "data/generated/publication_gate/company_catalog.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
