from pathlib import Path

from axiom_engine.etf_company_cards import build_etf_company_cards, write_etf_company_cards


root = Path(__file__).resolve().parents[1]
report = build_etf_company_cards(root)
write_etf_company_cards(report, root / "data/generated/etf_company_cards")
print(report["summary"])
