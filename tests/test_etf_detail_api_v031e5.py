from __future__ import annotations

import json

import pytest

from axiom_engine.etf_change_api import ETFChangeAPIError, ETFChangeNotFound
from axiom_engine.etf_company_card_api import ETFCompanyCardNotFound
from axiom_engine.etf_detail_api import ETFDetailNotFound, ETFDetailService
from axiom_engine.valuation_http import ValuationWSGIApp


CARD = {
    "etf_id": "US-QQQ",
    "etf_ticker": "QQQ",
    "etf_name": "Invesco QQQ Trust",
    "company": {"company_id": "company:MU", "display_name": "Micron Technology"},
    "security": {"security_id": "security:NASDAQ-MU", "ticker": "MU"},
    "exposure": {"portfolio_weight": 0.05, "portfolio_weight_percent": 5.0},
    "valuation": {"status": "ready", "fair_value": "125"},
}


class Cards:
    def get(self, ticker):
        if ticker == "MISSING":
            raise ETFCompanyCardNotFound("missing")
        return {
            "etf": {"etf_id": "US-QQQ", "ticker": "QQQ"},
            "status": "available",
            "reason_code": None,
            "summary": {"company_card_count": 1, "valuation_available_count": 1, "valuation_unavailable_count": 0},
            "source": {"etf_holdings": "canonical", "valuation": "AXIOM"},
            "company_cards": [CARD],
        }


class Changes:
    mode = "available"

    def etf(self, ticker):
        if self.mode == "missing":
            raise ETFChangeNotFound("no transition")
        if self.mode == "broken":
            raise ETFChangeAPIError("broken projection")
        return {
            "source": {"name": "ETF-ENGINE-V2", "coverage": "top_holdings_only"},
            "events": [
                {"change_type": "UNCHANGED", "holding_symbol": "NVDA"},
                {"change_type": "EXITED_TOP_HOLDINGS", "holding_symbol": "MU"},
            ],
        }


def _service(mode="available"):
    changes = Changes()
    changes.mode = mode
    return ETFDetailService(company_card_service=Cards(), change_service=changes)


def _get(app, path: str):
    status = []
    body = b"".join(app({"REQUEST_METHOD":"GET","PATH_INFO":path}, lambda value, headers: status.append(value)))
    return status[0], json.loads(body)


def test_detail_combines_profile_cards_and_material_changes():
    payload = _service().get("QQQ")
    assert payload["etf"]["name"] == "Invesco QQQ Trust"
    assert payload["holdings"]["summary"]["observed_portfolio_weight_percent"] == 5.0
    assert payload["changes"]["summary"]["observed_event_count"] == 2
    assert payload["changes"]["summary"]["material_change_count"] == 1
    assert payload["changes"]["events"][0]["holding_symbol"] == "MU"
    assert payload["source"]["write_back_to_etf_engine"] is False


@pytest.mark.parametrize(
    ("mode", "reason"),
    [("missing", "NO_TOP_HOLDINGS_TRANSITION_OBSERVED"), ("broken", "ETF_CHANGE_PROJECTION_UNAVAILABLE")],
)
def test_detail_survives_missing_or_broken_change_projection(mode, reason):
    payload = _service(mode).get("QQQ")
    assert payload["status"] == "available"
    assert payload["components"]["company_cards"] == "available"
    assert payload["changes"]["reason_code"] == reason


def test_unknown_etf_is_not_found():
    with pytest.raises(ETFDetailNotFound):
        _service().get("MISSING")


def test_wsgi_exposes_single_etf_detail_route():
    app = ValuationWSGIApp(etf_detail_service=_service())
    status, payload = _get(app, "/v1/etfs/QQQ")
    assert status.startswith("200")
    assert payload["etf"]["ticker"] == "QQQ"
    assert payload["holdings"]["company_cards"][0]["security"]["ticker"] == "MU"
