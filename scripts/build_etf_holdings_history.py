#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.etf_holdings_history import build_etf_holdings_history  # noqa: E402


if __name__ == "__main__":
    print(build_etf_holdings_history(ROOT)["summary"])
