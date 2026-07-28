from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

import pytest

from axiom_engine.fair_value_snapshot import (
    FairValueSnapshotAPIError,
    FairValueSnapshotNotFound,
    FairValueSnapshotService,
)
from axiom_engine.valuation_http import ValuationWSGIApp


def snapshot_payload() -> dict:
    return {
        "schema_version": "fair-value-snapshot.v030.14.0",
        "version": "V030.14.0",
        "generated_at": "2026-07-27T09:14:14+00:00",
        "as_of_date": "2026-07-27",
        "summary": {"company_count": 1, "valuation_card_ready_count": 1},
        "companies": [
            {
                "company_id": "company:US-NVDA",
                "symbol": "NVDA",
                "company_name": "NVIDIA Corporation",
                "currency": "USD",
                "as_of_date": "2026-07-27",
                "current_price": 170.0,
                "snapshot_state": "ready",
                "models": {
                    "dcf": {"status": "ready", "fair_value": 190.0},
                    "peer": {"status": "ready", "fair_value": 200.0},
                    "historical": {"status": "blocked", "reason": "no_benchmark"},
                },
                "composite": {
                    "status": "ready",
                    "fair_value": 195.0,
                    "normalized_weights": {"dcf": 0.5, "peer": 0.5},
                },
                "valuation_card": {
                    "current_price": 170.0,
                    "fair_value": 195.0,
                    "range_low": 180.0,
                    "range_high": 210.0,
                    "upside": 0.147,
                    "rating": "Undervalued",
                    "confidence": "medium",
                },
            }
        ],
        "indexes": {"symbol_to_position": {"NVDA": 0}},
    }


@pytest.fixture
def snapshot_path(tmp_path: Path) -> Path:
    path = tmp_path / "fair_value_snapshot.json"
    path.write_text(json.dumps(snapshot_payload()), encoding="utf-8")
    return path


def test_lists_compact_company_summaries(snapshot_path: Path):
    result = FairValueSnapshotService(snapshot_path).list_companies()
    assert result["endpoint_mode"] == "fair_value_snapshot"
    assert result["summary"]["company_count"] == 1
    assert result["companies"] == [
        {
            "company_id": "company:US-NVDA",
            "symbol": "NVDA",
            "company_name": "NVIDIA Corporation",
            "currency": "USD",
            "as_of_date": "2026-07-27",
            "snapshot_state": "ready",
            "current_price": 170.0,
            "fair_value": 195.0,
            "upside": 0.147,
            "rating": "Undervalued",
            "confidence": "medium",
        }
    ]


def test_reads_one_company_case_insensitively(snapshot_path: Path):
    result = FairValueSnapshotService(snapshot_path).get_company("nvda")
    assert result["symbol"] == "NVDA"
    assert result["snapshot_version"] == "V030.14.0"
    assert result["models"]["historical"]["status"] == "blocked"


def test_unknown_symbol_has_explicit_error(snapshot_path: Path):
    with pytest.raises(FairValueSnapshotNotFound, match="TSLA"):
        FairValueSnapshotService(snapshot_path).get_company("TSLA")


def test_missing_snapshot_has_explicit_error(tmp_path: Path):
    with pytest.raises(FairValueSnapshotAPIError, match="not found"):
        FairValueSnapshotService(tmp_path / "missing.json").list_companies()


def invoke_get(app: ValuationWSGIApp, path: str):
    observed = {}
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "CONTENT_TYPE": "",
        "CONTENT_LENGTH": "0",
        "wsgi.input": BytesIO(),
    }

    def start(status, headers):
        observed.update(status=status, headers=dict(headers))

    body = b"".join(app(environ, start))
    return observed, json.loads(body)


def test_http_exposes_list_and_single_company_routes(snapshot_path: Path):
    app = ValuationWSGIApp(fair_value_service=FairValueSnapshotService(snapshot_path))
    list_observed, listing = invoke_get(app, "/v1/fair-values")
    item_observed, item = invoke_get(app, "/v1/fair-values/NVDA")
    assert list_observed["status"] == "200 OK"
    assert len(listing["companies"]) == 1
    assert item_observed["status"] == "200 OK"
    assert item["valuation_card"]["fair_value"] == 195.0


def test_http_returns_404_for_symbol_outside_snapshot(snapshot_path: Path):
    app = ValuationWSGIApp(fair_value_service=FairValueSnapshotService(snapshot_path))
    observed, payload = invoke_get(app, "/v1/fair-values/UNKNOWN")
    assert observed["status"] == "404 Not Found"
    assert payload["error"] == "fair_value_not_found"
