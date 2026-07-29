from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.etf_change_api import ETFChangeService
from axiom_engine.valuation_http import ValuationWSGIApp


def _write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _service(root: Path) -> ETFChangeService:
    event = {"canonical_event_id":"etf-change:e1","etf_id":"US-QQQ","etf_ticker":"QQQ","holding_symbol":"MU","security_id":"security:NASDAQ-MU","company_id":"company:MU","change_type":"EXITED_TOP_HOLDINGS","coverage":"top_holdings_only","official_membership_change":False}
    _write(root, "data/generated/canonical_etf_change_events/manifest.json", {"schema_version":"canonical-etf-change-events.v031e.3","source_snapshot":{"provider_generated_at":"2026-07-29T00:00:00Z"}})
    _write(root, "data/generated/canonical_etf_change_events/events.json", [event])
    _write(root, "data/generated/canonical_etf_change_events/indexes.json", {"company_id_to_event_positions":{"company:MU":[0]},"etf_id_to_event_positions":{"US-QQQ":[0]}})
    _write(root, "data/universe/companies.json", [{"company_id":"company:MU","display_name":"Micron Technology"}])
    _write(root, "data/universe/securities.json", [{"security_id":"security:NASDAQ-MU","company_id":"company:MU","ticker":"MU","status":"active"}])
    return ETFChangeService(root=root)


def _get(app, path: str):
    status = []
    body = b"".join(app({"REQUEST_METHOD":"GET","PATH_INFO":path}, lambda value, headers: status.append(value)))
    return status[0], json.loads(body)


def test_company_and_etf_views_share_same_canonical_event(tmp_path: Path):
    service = _service(tmp_path)
    company = service.company("MU")
    etf = service.etf("QQQ")
    assert company["events"][0]["canonical_event_id"] == etf["events"][0]["canonical_event_id"]
    assert "not official index membership" in company["source"]["interpretation"]


def test_wsgi_routes_company_and_etf_views(tmp_path: Path):
    app = ValuationWSGIApp(etf_change_service=_service(tmp_path))
    company_status, company = _get(app, "/v1/companies/MU/etf-events")
    etf_status, etf = _get(app, "/v1/etfs/QQQ/changes")
    assert company_status.startswith("200") and company["company"]["ticker"] == "MU"
    assert etf_status.startswith("200") and etf["etf"]["ticker"] == "QQQ"
