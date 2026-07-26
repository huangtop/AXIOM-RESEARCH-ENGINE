#!/usr/bin/env python3
from __future__ import annotations
import argparse
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from axiom_engine.automation import format_automation_status

def main() -> int:
    parser = argparse.ArgumentParser(description="Show AXIOM automation operations status")
    parser.add_argument("--output-dir", default="data/generated/automation")
    args = parser.parse_args()
    path = Path(args.output_dir)
    if not path.is_absolute():
        path = ROOT / path
    print(format_automation_status(path))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
