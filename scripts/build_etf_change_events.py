from pathlib import Path

from axiom_engine.etf_change_events import build_canonical_etf_change_events, write_canonical_etf_change_events


root = Path(__file__).resolve().parents[1]
report = build_canonical_etf_change_events(root)
write_canonical_etf_change_events(report, root / "data/generated/canonical_etf_change_events")
print(report["summary"])
