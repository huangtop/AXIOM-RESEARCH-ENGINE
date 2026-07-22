from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any, Mapping, Protocol

from axiom_engine.legacy_valuation_parity import (
    LegacyValuationInputs,
    LegacyValuationModel,
    LegacyValuationParityEngine,
)
from axiom_engine.models.valuation import FactQuality, FinancialFact, PeriodType
from axiom_engine.previous_close import DailyClose, DailyCloseProvider
from axiom_engine.repository import RepositoryBundle, load_bundle
from axiom_engine.services.valuation import run_valuation_book


class ValuationAPIError(ValueError):
    """Raised when the public valuation request contract is invalid."""


class RepositoryProvider(Protocol):
    def __call__(self) -> RepositoryBundle: ...


@dataclass(frozen=True, slots=True)
class BackendValuationAPIService:
    """Production API facade over AXIOM's canonical repository valuation chain.

    The client supplies identity and scenario selection only. Financial facts,
    SEC-derived fundamentals, estimates, valuation profiles and assumptions are
    always resolved from the backend RepositoryBundle.
    """

    close_provider: DailyCloseProvider
    repository_provider: RepositoryProvider = load_bundle

    def calculate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        symbol = _required_text(request, "symbol").upper()
        unknown = sorted(set(request) - {"symbol", "scenario_id", "as_of", "refresh"})
        if unknown:
            raise ValuationAPIError(
                "production endpoint does not accept financial inputs or overrides; "
                f"unsupported field(s): {', '.join(unknown)}"
            )

        bundle = self.repository_provider()
        security = _resolve_security(bundle, symbol)
        scenario = _resolve_scenario(bundle, security.company_id, request.get("scenario_id"))
        close = self.close_provider.previous_close(symbol, as_of=_parse_as_of(request.get("as_of")))
        effective = _with_previous_close(
            bundle,
            security.company_id,
            security.security_id,
            close,
            valuation_date=scenario.as_of_date,
        )

        executions, snapshots, book = run_valuation_book(
            effective,
            company_id=security.company_id,
            security_id=security.security_id,
            scenario_id=scenario.scenario_id,
        )
        snapshot_by_id = {item.valuation_snapshot_id: item for item in snapshots}
        models: dict[str, Any] = {}
        for entry in book.entries:
            snapshot = snapshot_by_id.get(entry.snapshot_id or "")
            models[entry.model_type] = {
                "status": entry.status,
                "applicability": entry.applicability.value,
                "fair_value": _number_text(entry.fair_value_per_share),
                "upside": _number_text(entry.upside),
                "confidence": _number_text(entry.confidence),
                "blend_weight": _number_text(entry.blend_weight),
                "inputs": _serialize(snapshot.model_inputs) if snapshot else None,
                "outputs": _serialize(snapshot.model_outputs) if snapshot else None,
                "warnings": list(entry.warnings),
                "reason_zh_tw": entry.reason_zh_tw,
            }

        return {
            "api_version": "1.1",
            "engine": "axiom_repository_valuation",
            "endpoint_mode": "production",
            "symbol": symbol,
            "company_id": security.company_id,
            "security_id": security.security_id,
            "scenario_id": scenario.scenario_id,
            "scenario_type": scenario.scenario_type.value,
            "available_scenarios": [
                {
                    "scenario_id": item.scenario_id,
                    "scenario_type": item.scenario_type.value,
                    "name": item.name,
                }
                for item in sorted(
                    (x for x in bundle.valuation_scenarios if x.company_id == security.company_id),
                    key=lambda x: (x.as_of_date, x.revision, x.scenario_type.value),
                )
            ],
            "valuation_as_of": scenario.as_of_date.isoformat(),
            "reference_price_date": close.session_date.isoformat(),
            "reference_price": _number_text(close.close),
            "price_type": "previous_regular_close",
            "currency": close.currency or security.currency,
            "data_provenance": {
                "fundamentals": "canonical.financial_facts (SEC 10-K/10-Q derived)",
                "estimates": "canonical.estimates",
                "profiles": "canonical.valuation_profiles",
                "assumptions": "canonical.valuation_assumptions",
                "market_price": close.provider,
            },
            "models": models,
            "summary": {
                "blended_fair_value": _number_text(book.blended_fair_value),
                "blended_upside": _number_text(book.blended_upside),
                "completed_models": sum(1 for item in book.entries if item.status == "completed"),
                "total_models": len(book.entries),
            },
            "executions": [_serialize(item.model_dump(mode="json")) for item in executions],
        }


def _resolve_security(bundle: RepositoryBundle, symbol: str):
    matches = [item for item in bundle.securities if item.active and item.ticker.upper() == symbol]
    if not matches:
        raise ValuationAPIError(f"security not found in canonical repository: {symbol}")
    if len(matches) > 1:
        raise ValuationAPIError(f"symbol is ambiguous in canonical repository: {symbol}")
    return matches[0]


def _resolve_scenario(bundle: RepositoryBundle, company_id: str, requested: Any):
    candidates = [item for item in bundle.valuation_scenarios if item.company_id == company_id]
    if requested not in (None, ""):
        scenario_id = str(requested).strip()
        candidates = [item for item in candidates if item.scenario_id == scenario_id]
        if not candidates:
            raise ValuationAPIError(
                f"valuation scenario not found for company {company_id}: {scenario_id}"
            )
        return candidates[0]
    if not candidates:
        raise ValuationAPIError(f"no valuation scenario configured for company: {company_id}")
    base_candidates = [item for item in candidates if item.scenario_type.value == "base"]
    preferred = base_candidates or candidates
    return max(preferred, key=lambda item: (item.as_of_date, item.revision, item.scenario_id))


def _with_previous_close(
    bundle: RepositoryBundle,
    company_id: str,
    security_id: str,
    close: DailyClose,
    *,
    valuation_date: date,
) -> RepositoryBundle:
    facts = [
        item
        for item in bundle.financial_facts
        if not (
            item.company_id == company_id
            and item.security_id == security_id
            and item.metric == "market_price"
            and item.period_end == valuation_date
        )
    ]
    facts.append(
        FinancialFact(
            fact_id=(
                f"market_price:{security_id}:{valuation_date.isoformat()}:"
                f"previous_close:{close.session_date.isoformat()}"
            ),
            company_id=company_id,
            security_id=security_id,
            metric="market_price",
            value=float(close.close),
            unit=close.currency or "USD",
            period_type=PeriodType.instant,
            period_end=valuation_date,
            quality=FactQuality.reported,
            source_ids=[close.provider],
            formula_version="previous_regular_close.v1",
        )
    )
    return replace(bundle, financial_facts=facts)


@dataclass(frozen=True, slots=True)
class LegacyValuationAPIService:
    """Debug-only parity endpoint. Never use as the production data path."""

    close_provider: DailyCloseProvider
    engine: LegacyValuationParityEngine = LegacyValuationParityEngine()

    def calculate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        symbol = _required_text(request, "symbol").upper()
        payload = request.get("research_payload")
        if not isinstance(payload, Mapping):
            raise ValuationAPIError("research_payload must be an object")
        close = _parse_close(request.get("previous_close"), symbol)
        if close is None:
            close = self.close_provider.previous_close(symbol, as_of=_parse_as_of(request.get("as_of")))
        inputs = LegacyValuationInputs.from_legacy_payload(symbol, payload, close)
        overrides = request.get("overrides", {})
        if not isinstance(overrides, Mapping):
            raise ValuationAPIError("overrides must be an object")
        inputs = _apply_overrides(inputs, overrides)
        results = self.engine.calculate_all(inputs)
        models = {
            item.model.value: {
                "status": item.status,
                "fair_value": _number_text(item.display_value),
                "fair_value_full_precision": _number_text(item.fair_value_per_share),
                "message": item.reason,
            }
            for item in results
        }
        values = [item.display_value for item in results if item.display_value is not None]
        return {
            "api_version": "1.1",
            "engine": "legacy_valuation_parity",
            "endpoint_mode": "debug_only",
            "symbol": symbol,
            "valuation_as_of": close.session_date.isoformat(),
            "reference_price": _number_text(close.close),
            "price_type": "previous_regular_close",
            "models": models,
            "summary": _legacy_summary(values, close.close),
        }


def _apply_overrides(inputs: LegacyValuationInputs, overrides: Mapping[str, Any]) -> LegacyValuationInputs:
    mapping = {
        "target_peg": "target_peg", "target_pe": "target_pe", "target_ps": "target_ps",
        "target_pb": "target_pb", "target_ev_ebitda": "target_ev_ebitda",
        "milestone_success_probability": "milestone_success_probability",
        "success_probability": "milestone_success_probability",
        "success_multiple": "milestone_success_multiple", "failure_multiple": "milestone_failure_multiple",
    }
    unknown = sorted(set(overrides) - set(mapping))
    if unknown:
        raise ValuationAPIError(f"unsupported override(s): {', '.join(unknown)}")
    changes: dict[str, Decimal] = {}
    for name, raw in overrides.items():
        value = _decimal(raw, name)
        if name in {"success_probability", "milestone_success_probability"}:
            if not Decimal("0") <= value <= Decimal("1"):
                raise ValuationAPIError("success probability must be between 0 and 1")
        elif value <= 0:
            raise ValuationAPIError(f"{name} must be positive")
        changes[mapping[name]] = value
    return replace(inputs, **changes)


def _parse_close(value: Any, symbol: str) -> DailyClose | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValuationAPIError("previous_close must be an object")
    close_symbol = str(value.get("symbol", symbol)).strip().upper()
    if close_symbol != symbol:
        raise ValuationAPIError("previous_close symbol must match request symbol")
    try:
        session_date = date.fromisoformat(_required_text(value, "session_date"))
    except ValueError as exc:
        raise ValuationAPIError("previous_close.session_date must be YYYY-MM-DD") from exc
    return DailyClose(
        close_symbol,
        session_date,
        _decimal(value.get("close"), "previous_close.close"),
        _optional_text(value.get("currency")),
        _optional_text(value.get("exchange_timezone")),
        _optional_text(value.get("provider")) or "request_fixture",
    )


def _parse_as_of(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValuationAPIError("as_of must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValuationAPIError("as_of must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValuationAPIError("as_of must include a timezone")
    return parsed


def _legacy_summary(values: list[Decimal], reference: Decimal) -> dict[str, Any]:
    if not values:
        return {"available_models": 0, "median_fair_value": None, "upside_percent": None}
    med = Decimal(str(median(values)))
    upside = ((med / reference) - Decimal("1")) * Decimal("100")
    return {
        "available_models": len(values),
        "median_fair_value": _number_text(med),
        "upside_percent": _number_text(upside.quantize(Decimal("0.01"))),
    }


def _required_text(mapping: Mapping[str, Any], key: str) -> str:
    text = str(mapping.get(key, "")).strip()
    if not text:
        raise ValuationAPIError(f"{key} is required")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValuationAPIError(f"{name} must be numeric") from exc
    if not result.is_finite():
        raise ValuationAPIError(f"{name} must be finite")
    return result


def _number_text(value: Any) -> str | None:
    if value is None:
        return None
    return format(Decimal(str(value)), "f")


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _number_text(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, LegacyValuationModel):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value
