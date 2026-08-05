from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from axiom_engine.etf_holdings_history import build_etf_holdings_history


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_static(root: Path) -> None:
    _write(root / "config/etf_holdings_refresh.v031e.6.json", {
        "materiality": {"absolute_weight_change": 0.001, "relative_share_change": 0.05},
        "focus_etfs": ["QQQ", "DRAM"],
    })
    _write(root / "data/generated/etf_identity_bridge/identity_bridge.json", {
        "records": [{"holding_symbol": "MU", "status": "resolved_exact", "security_id": "security:MU", "company_id": "company:MU"}]
    })
    _write(root / "data/generated/publication_gate/company_catalog.json", {
        "companies": [{"company_id": "company:MU", "scope_axes": {"research_page": True}}]
    })


def _provider(root: Path, date: str, qqq_weight: float | None, qqq_shares: int | None, dram_weight: float | None = None) -> None:
    holdings = {}
    rows = []
    if qqq_weight is not None:
        rows.append({"etf_id": "US-QQQ", "ticker": "QQQ", "name": "Invesco QQQ", "weight": qqq_weight, "shares": qqq_shares})
    if dram_weight is not None:
        rows.append({"etf_id": "US-DRAM", "ticker": "DRAM", "name": "Theme ETF", "weight": dram_weight})
    if rows:
        holdings["MU"] = rows
    raw = json.dumps(holdings, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    snapshot_id = date.replace("-", "") + "-fixture"
    cache = root / "data/generated/provider_cache/etf_engine_v2"
    _write(cache / "state.json", {"current_snapshot_id": snapshot_id, "holdings_index_sha256": digest})
    _write(cache / "snapshots" / snapshot_id / "manifest.json", {"generated_at": f"{date}T22:00:00Z"})
    _write(cache / "snapshots" / snapshot_id / "holdings_index.json", holdings)


def test_daily_snapshots_diff_weights_shares_and_write_company_projection(tmp_path: Path):
    _seed_static(tmp_path)
    _provider(tmp_path, "2026-08-03", 0.010, 100, None)
    first = build_etf_holdings_history(tmp_path, now=datetime(2026, 8, 3, tzinfo=timezone.utc))
    assert first["summary"]["baseline_only"] is True
    _provider(tmp_path, "2026-08-04", 0.012, 120, 0.03)
    second = build_etf_holdings_history(tmp_path, now=datetime(2026, 8, 4, tzinfo=timezone.utc))
    by_etf = {row["etf_ticker"]: row for row in second["events"]}
    assert by_etf["QQQ"]["change_type"] == "WEIGHT_INCREASED"
    assert by_etf["QQQ"]["delta_shares"] == 20
    assert by_etf["DRAM"]["change_type"] == "ENTERED_TOP_HOLDINGS"
    assert by_etf["DRAM"]["shares_status"] == "not_provided_by_source"
    assert len(second["triggers"]) == 2
    company = json.loads((tmp_path / "data/generated/canonical_etf_change_events/per-company/MU.json").read_text())
    assert company["comparison"] == {"previous_date": "2026-08-03", "current_date": "2026-08-04"}
    assert {row["etf_ticker"] for row in company["fund_observations"]} >= {"QQQ", "DRAM"}


def test_non_research_company_does_not_trigger_news_ai(tmp_path: Path):
    _seed_static(tmp_path)
    _write(tmp_path / "data/generated/publication_gate/company_catalog.json", {"companies": []})
    _provider(tmp_path, "2026-08-03", 0.010, 100)
    build_etf_holdings_history(tmp_path)
    _provider(tmp_path, "2026-08-04", None, None)
    report = build_etf_holdings_history(tmp_path)
    assert report["events"][0]["change_type"] == "EXITED_TOP_HOLDINGS"
    assert report["triggers"] == []


def test_same_provider_snapshot_is_noop(tmp_path: Path):
    _seed_static(tmp_path)
    _provider(tmp_path, "2026-08-03", 0.010, None)
    build_etf_holdings_history(tmp_path)
    report = build_etf_holdings_history(tmp_path)
    assert report["summary"]["status"] == "unchanged"
