#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.etf_holdings_history import build_etf_holdings_history


if __name__ == "__main__":
    print(build_etf_holdings_history(Path(__file__).resolve().parents[1])["summary"])
