#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OVERVIEW_ROOT = ROOT / "data/generated/company_overview"
OUTPUT = ROOT / "data/valuation/company_routing.json"
AI_THEMES = {
    "theme:ai_infrastructure",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    index = _load(OVERVIEW_ROOT / "index.json")
    companies: dict[str, dict[str, Any]] = {}
    for filename in sorted(set((index.get("ticker_to_file") or {}).values())):
        overview = _load(OVERVIEW_ROOT / "per-company" / str(filename))
        company_id = str(overview.get("company_id") or "")
        if not company_id:
            continue
        theme_id = str((((overview.get("path") or {}).get("theme") or {}).get("id")) or "")
        companies[company_id] = {
            "ai_research_company": theme_id in AI_THEMES,
            "valuation": ((overview.get("routing") or {}).get("valuation") or {}),
        }

    payload = {
        "schema_version": "valuation-routing-snapshot.v1",
        "update_mode": "manual",
        "companies": dict(sorted(companies.items())),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print({"company_count": len(companies), "output": str(OUTPUT.relative_to(ROOT))})


if __name__ == "__main__":
    main()
