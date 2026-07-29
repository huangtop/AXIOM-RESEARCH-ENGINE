from __future__ import annotations

import json
import os
from http import HTTPStatus
from typing import Any, Callable, Iterable

from axiom_engine.cached_close import JsonCachedPreviousCloseProvider
from axiom_engine.config import PREVIOUS_CLOSE_CACHE
from axiom_engine.fair_value_snapshot import (
    FairValueSnapshotAPIError,
    FairValueSnapshotNotFound,
    FairValueSnapshotService,
)
from axiom_engine.full_market_coverage import (
    FullMarketCoverageError,
    FullMarketCoverageNotFound,
    FullMarketCoverageService,
)
from axiom_engine.etf_exposure_api import ETFExposureAPIError, ETFExposureNotFound, ETFExposureService
from axiom_engine.etf_change_api import ETFChangeAPIError, ETFChangeNotFound, ETFChangeService
from axiom_engine.etf_company_card_api import (
    ETFCompanyCardAPIError,
    ETFCompanyCardNotFound,
    ETFCompanyCardService,
)
from axiom_engine.previous_close import PreviousCloseError, YahooPreviousCloseAdapter
from axiom_engine.theme_sector_inference import (
    ThemeSectorInferenceError,
    ThemeSectorInferenceNotFound,
    ThemeSectorInferenceService,
)
from axiom_engine.valuation_api import (
    BackendValuationAPIService,
    LegacyValuationAPIService,
    ValuationAPIError,
)

StartResponse = Callable[[str, list[tuple[str, str]]], Any]


class ValuationWSGIApp:
    def __init__(
        self,
        production_service: BackendValuationAPIService | None = None,
        legacy_service: LegacyValuationAPIService | None = None,
        fair_value_service: FairValueSnapshotService | None = None,
        full_market_service: FullMarketCoverageService | None = None,
        theme_sector_service: ThemeSectorInferenceService | None = None,
        etf_exposure_service: ETFExposureService | None = None,
        etf_change_service: ETFChangeService | None = None,
        etf_company_card_service: ETFCompanyCardService | None = None,
    ) -> None:
        cached_close_provider = JsonCachedPreviousCloseProvider(PREVIOUS_CLOSE_CACHE)
        yahoo_close_provider = YahooPreviousCloseAdapter()
        self.production_service = production_service or BackendValuationAPIService(
            cached_close_provider
        )
        # Debug-only parity endpoint may still fetch when explicitly requested.
        self.legacy_service = legacy_service or LegacyValuationAPIService(yahoo_close_provider)
        self.fair_value_service = fair_value_service or FairValueSnapshotService()
        self.full_market_service = full_market_service or FullMarketCoverageService()
        self.theme_sector_service = theme_sector_service or ThemeSectorInferenceService()
        self.etf_exposure_service = etf_exposure_service or ETFExposureService()
        self.etf_change_service = etf_change_service or ETFChangeService()
        self.etf_company_card_service = etf_company_card_service or ETFCompanyCardService()

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        if method == "OPTIONS" and (
            path in {
                "/v1/valuations",
                "/v1/debug/valuations/legacy-parity",
                "/v1/fair-values",
                "/v1/companies",
                "/v1/research-universe",
            }
            or path.startswith("/v1/fair-values/")
            or (path.startswith("/v1/companies/") and path.endswith("/valuation-card"))
            or (path.startswith("/v1/companies/") and path.endswith("/research-policy"))
            or (path.startswith("/v1/companies/") and path.endswith("/etf-exposure"))
            or (path.startswith("/v1/companies/") and path.endswith("/etf-events"))
            or (path.startswith("/v1/etfs/") and path.endswith("/changes"))
            or (path.startswith("/v1/etfs/") and path.endswith("/company-cards"))
        ):
            return self._respond(start_response, HTTPStatus.NO_CONTENT, {})
        if method == "GET" and path == "/health":
            return self._respond(start_response, HTTPStatus.OK, {"status": "ok"})
        if method == "GET" and path == "/v1/fair-values":
            try:
                return self._respond(
                    start_response, HTTPStatus.OK, self.fair_value_service.list_companies()
                )
            except FairValueSnapshotAPIError as exc:
                return self._respond(
                    start_response,
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "snapshot_unavailable", "message": str(exc)},
                )
        if method == "GET" and path == "/v1/companies":
            try:
                return self._respond(start_response, HTTPStatus.OK, self.full_market_service.list())
            except FullMarketCoverageError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "full_market_coverage_unavailable", "message": str(exc)})
        if method == "GET" and path == "/v1/research-universe":
            try:
                return self._respond(
                    start_response, HTTPStatus.OK, self.theme_sector_service.selected()
                )
            except ThemeSectorInferenceError as exc:
                return self._respond(
                    start_response,
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "theme_sector_inference_unavailable", "message": str(exc)},
                )
        if method == "GET" and path.startswith("/v1/companies/") and path.endswith("/research-policy"):
            symbol = path.removeprefix("/v1/companies/").removesuffix("/research-policy").strip("/")
            try:
                return self._respond(
                    start_response, HTTPStatus.OK, dict(self.theme_sector_service.get(symbol))
                )
            except ThemeSectorInferenceNotFound as exc:
                return self._respond(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    {"error": "company_not_found", "message": str(exc)},
                )
            except ThemeSectorInferenceError as exc:
                return self._respond(
                    start_response,
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "theme_sector_inference_unavailable", "message": str(exc)},
                )
        if method == "GET" and path.startswith("/v1/companies/") and path.endswith("/valuation-card"):
            symbol = path.removeprefix("/v1/companies/").removesuffix("/valuation-card").strip("/")
            try:
                return self._respond(start_response, HTTPStatus.OK, self.full_market_service.get(symbol))
            except FullMarketCoverageNotFound as exc:
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "company_not_found", "message": str(exc)})
            except FullMarketCoverageError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "full_market_coverage_unavailable", "message": str(exc)})
        if method == "GET" and path.startswith("/v1/companies/") and path.endswith("/etf-exposure"):
            symbol = path.removeprefix("/v1/companies/").removesuffix("/etf-exposure").strip("/")
            try:
                return self._respond(start_response, HTTPStatus.OK, self.etf_exposure_service.get(symbol))
            except ETFExposureNotFound as exc:
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "company_not_found", "message": str(exc)})
            except ETFExposureAPIError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "etf_exposure_unavailable", "message": str(exc)})
        if method == "GET" and path.startswith("/v1/companies/") and path.endswith("/etf-events"):
            symbol = path.removeprefix("/v1/companies/").removesuffix("/etf-events").strip("/")
            try:
                return self._respond(start_response, HTTPStatus.OK, self.etf_change_service.company(symbol))
            except ETFChangeNotFound as exc:
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "company_not_found", "message": str(exc)})
            except ETFChangeAPIError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "etf_events_unavailable", "message": str(exc)})
        if method == "GET" and path.startswith("/v1/etfs/") and path.endswith("/changes"):
            symbol = path.removeprefix("/v1/etfs/").removesuffix("/changes").strip("/")
            try:
                return self._respond(start_response, HTTPStatus.OK, self.etf_change_service.etf(symbol))
            except ETFChangeNotFound as exc:
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "etf_not_found", "message": str(exc)})
            except ETFChangeAPIError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "etf_events_unavailable", "message": str(exc)})
        if method == "GET" and path.startswith("/v1/etfs/") and path.endswith("/company-cards"):
            symbol = path.removeprefix("/v1/etfs/").removesuffix("/company-cards").strip("/")
            try:
                return self._respond(start_response, HTTPStatus.OK, self.etf_company_card_service.get(symbol))
            except ETFCompanyCardNotFound as exc:
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "etf_not_found", "message": str(exc)})
            except ETFCompanyCardAPIError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "etf_company_cards_unavailable", "message": str(exc)})
        if method == "GET" and path.startswith("/v1/fair-values/"):
            symbol = path.removeprefix("/v1/fair-values/")
            try:
                return self._respond(
                    start_response, HTTPStatus.OK, self.fair_value_service.get_company(symbol)
                )
            except FairValueSnapshotNotFound as exc:
                return self._respond(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    {"error": "fair_value_not_found", "message": str(exc)},
                )
            except FairValueSnapshotAPIError as exc:
                return self._respond(
                    start_response,
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "snapshot_unavailable", "message": str(exc)},
                )
        if method != "POST":
            return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        try:
            request = _read_json(environ)
            if path == "/v1/valuations":
                payload = self.production_service.calculate(request)
            elif path == "/v1/debug/valuations/legacy-parity":
                payload = self.legacy_service.calculate(request)
            else:
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except ValuationAPIError as exc:
            return self._respond(
                start_response,
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_request", "message": str(exc)},
            )
        except PreviousCloseError as exc:
            return self._respond(
                start_response,
                HTTPStatus.BAD_GATEWAY,
                {"error": "market_data_unavailable", "message": str(exc)},
            )
        except Exception as exc:
            return self._respond(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal_error", "message": type(exc).__name__},
            )
        return self._respond(start_response, HTTPStatus.OK, payload)

    @staticmethod
    def _respond(
        start_response: StartResponse,
        status: HTTPStatus,
        payload: dict[str, Any],
    ) -> list[bytes]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        allowed_origin = os.getenv("AXIOM_CORS_ORIGIN", "*")
        start_response(
            f"{status.value} {status.phrase}",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("Access-Control-Allow-Origin", allowed_origin),
                ("Access-Control-Allow-Headers", "Content-Type"),
                ("Access-Control-Allow-Methods", "POST, GET, OPTIONS"),
            ],
        )
        return [body]


def _read_json(environ: dict[str, Any]) -> dict[str, Any]:
    if "application/json" not in str(environ.get("CONTENT_TYPE", "")):
        raise ValuationAPIError("Content-Type must be application/json")
    try:
        length = int(environ.get("CONTENT_LENGTH", "0") or 0)
    except (TypeError, ValueError) as exc:
        raise ValuationAPIError("invalid Content-Length") from exc
    if length <= 0 or length > 1_000_000:
        raise ValuationAPIError("request body size is invalid")
    try:
        payload = json.loads(environ["wsgi.input"].read(length).decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValuationAPIError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValuationAPIError("request body must be a JSON object")
    return payload


app = ValuationWSGIApp()
