#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.publication_gate import (  # noqa: E402
    build_publication_catalog,
    write_publication_catalog,
)


def main() -> None:
    root = ROOT
    report = build_publication_catalog(root)
    write_publication_catalog(report, root / "data/generated/publication_gate/company_catalog.json")
    print(report["summary"])


if __name__ == "__main__":
    main()
