from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from axiom_engine.models.core import Security
from axiom_engine.models.valuation import ScenarioType, ValuationScenario
from axiom_engine.previous_close import DailyClose
from axiom_engine.repository import RepositoryBundle
from axiom_engine.valuation_api import (
    BackendValuationAPIService,
    ValuationAPIError,
    _resolve_scenario,
    _resolve_security,
    _with_previous_close,
)


class CloseProvider:
    def previous_close(self, symbol, *, as_of=None):
        return DailyClose(symbol, date(2026, 7, 21), Decimal("205.47"), "USD", "America/New_York", "fixture")


def empty_bundle(**changes):
    values = {field: [] for field in RepositoryBundle.__dataclass_fields__}
    values.update(changes)
    return RepositoryBundle(**values)


def test_production_endpoint_rejects_frontend_financial_payload():
    service = BackendValuationAPIService(CloseProvider(), lambda: empty_bundle())
    with pytest.raises(ValuationAPIError, match="does not accept financial inputs"):
        service.calculate({"symbol": "NVDA", "research_payload": {"forward_eps": 6}})


def test_resolves_symbol_from_canonical_security_repository():
    security = Security(
        security_id="security:nvda",
        company_id="company:nvidia",
        ticker="NVDA",
        exchange="NASDAQ",
        currency="USD",
    )
    assert _resolve_security(empty_bundle(securities=[security]), "NVDA") == security


def test_latest_company_scenario_is_selected_when_not_explicit():
    older = ValuationScenario(
        scenario_id="old", company_id="company:nvidia", research_period="FY2025",
        revision=1, name="old", scenario_type=ScenarioType.base,
        as_of_date=date(2025, 1, 1),
    )
    latest = older.model_copy(update={"scenario_id": "latest", "revision": 2, "as_of_date": date(2026, 7, 21)})
    assert _resolve_scenario(empty_bundle(valuation_scenarios=[older, latest]), "company:nvidia", None) == latest


def test_previous_close_is_injected_only_as_market_price_fact():
    close = CloseProvider().previous_close("NVDA")
    bundle = empty_bundle()
    updated = _with_previous_close(
        bundle,
        "company:nvidia",
        "security:nvda",
        close,
        valuation_date=date(2026, 7, 19),
    )
    fact = updated.financial_facts[0]
    assert fact.metric == "market_price"
    assert fact.value == 205.47
    assert fact.period_end == date(2026, 7, 19)
    assert close.session_date.isoformat() in fact.fact_id
    assert fact.formula_version == "previous_regular_close.v1"


def test_api_reference_price_equals_every_completed_model_market_price():
    service = BackendValuationAPIService(CloseProvider())
    result = service.calculate({"symbol": "NVDA"})
    reference = Decimal(result["reference_price"])
    completed = [
        model for model in result["models"].values() if model["status"] == "completed"
    ]
    assert completed
    assert all(Decimal(str(model["inputs"]["market_price"])) == reference for model in completed)
    assert all(result["reference_price_date"] in item["input_refs"][-1] for item in result["executions"] if item["status"] == "completed")
