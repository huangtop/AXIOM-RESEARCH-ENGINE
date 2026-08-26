from __future__ import annotations

import json
import hashlib
import os
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable, Iterable

from axiom_engine.coverage_policy import (
    CoveragePolicyError,
    CoveragePolicyNotFound,
    CoveragePolicyService,
    CoveragePublicationDenied,
)
from axiom_engine.company_overview import CompanyOverviewError, CompanyOverviewNotFound, CompanyOverviewService
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
from axiom_engine.etf_detail_api import ETFDetailAPIError, ETFDetailNotFound, ETFDetailService
from axiom_engine.theme_sector_inference import (
    ThemeSectorInferenceError,
    ThemeSectorInferenceNotFound,
    ThemeSectorInferenceService,
)

class ValuationRequestError(ValueError):
    pass


StartResponse = Callable[[str, list[tuple[str, str]]], Any]


class ValuationWSGIApp:
    def __init__(
        self,
        full_market_service: FullMarketCoverageService | None = None,
        theme_sector_service: ThemeSectorInferenceService | None = None,
        etf_exposure_service: ETFExposureService | None = None,
        etf_change_service: ETFChangeService | None = None,
        etf_company_card_service: ETFCompanyCardService | None = None,
        etf_detail_service: ETFDetailService | None = None,
        coverage_service: CoveragePolicyService | None = None,
        company_overview_service: CompanyOverviewService | None = None,
        publication_root: Path | str = "data/generated/publication_gate",
    ) -> None:
        self.coverage_service = coverage_service or CoveragePolicyService()
        self.company_overview_service = company_overview_service or CompanyOverviewService()
        self.publication_root = Path(publication_root)
        self.full_market_service = full_market_service or FullMarketCoverageService(coverage_service=self.coverage_service)
        self.theme_sector_service = theme_sector_service or ThemeSectorInferenceService()
        self.etf_exposure_service = etf_exposure_service or ETFExposureService()
        self.etf_change_service = etf_change_service or ETFChangeService()
        self.etf_company_card_service = etf_company_card_service or ETFCompanyCardService()
        self.etf_detail_service = etf_detail_service or ETFDetailService(
            company_card_service=self.etf_company_card_service,
            change_service=self.etf_change_service,
        )

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        if method == "OPTIONS" and (
            path in {
                "/v1/valuations",
                "/v1/companies",
                "/v1/research-universe",
                "/v1/publication/manifest.json",
            }
            or (path.startswith("/v1/companies/") and path.endswith("/valuation-card"))
            or (path.startswith("/v1/companies/") and path.endswith("/research-policy"))
            or (path.startswith("/v1/companies/") and path.endswith("/overview"))
            or (path.startswith("/v1/companies/") and path.endswith("/etf-exposure"))
            or (path.startswith("/v1/companies/") and path.endswith("/etf-events"))
            or (path.startswith("/v1/etfs/") and path.endswith("/changes"))
            or (path.startswith("/v1/etfs/") and path.endswith("/company-cards"))
            or (path.startswith("/v1/etfs/") and path.count("/") == 3)
            or path.startswith("/v1/publication/companies/")
        ):
            return self._respond(start_response, HTTPStatus.NO_CONTENT, {})
        if method == "GET" and path == "/health":
            return self._respond(start_response, HTTPStatus.OK, {"status": "ok"})
        if method == "GET" and path == "/v1/publication/manifest.json":
            return self._publication_file(
                environ,
                start_response,
                self.publication_root / "manifest.json",
                cache_control="public, max-age=60, must-revalidate",
            )
        if method == "GET" and path.startswith("/v1/publication/companies/"):
            filename = path.removeprefix("/v1/publication/companies/")
            if not filename or "/" in filename or "\\" in filename or not filename.endswith(".json"):
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return self._publication_file(
                environ,
                start_response,
                self.publication_root / "companies" / filename,
                cache_control="public, max-age=31536000, immutable",
            )
        # Research-policy has its own evidence-universe lookup and may be used
        # with an isolated inference service before publication projection.
        company_suffixes = ("/valuation-card", "/etf-exposure", "/etf-events", "/overview")
        gated_symbol = None
        if method == "GET" and path.startswith("/v1/companies/") and path.endswith(company_suffixes):
            gated_symbol = path.removeprefix("/v1/companies/").rsplit("/", 1)[0].strip("/")
        if gated_symbol is not None:
            try:
                self.coverage_service.require_public(gated_symbol)
            except CoveragePublicationDenied as exc:
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {
                    "error": "company_not_published",
                    "publication_tier": exc.publication_tier,
                    "reason_code": exc.reason_code,
                    "message": str(exc),
                })
            except CoveragePolicyNotFound as exc:
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "company_not_found", "message": str(exc)})
            except CoveragePolicyError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "coverage_policy_unavailable", "message": str(exc)})
        
        if method == "GET" and path == "/v1/companies":
            try:
                return self._respond(start_response, HTTPStatus.OK, self.full_market_service.list())
            except FullMarketCoverageError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "full_market_coverage_unavailable", "message": str(exc)})
            except CoveragePolicyError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "coverage_policy_unavailable", "message": str(exc)})
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
        if method == "GET" and path.startswith("/v1/companies/") and path.endswith("/overview"):
            symbol = path.removeprefix("/v1/companies/").removesuffix("/overview").strip("/")
            try:
                return self._respond(start_response, HTTPStatus.OK, dict(self.company_overview_service.get(symbol)))
            except CompanyOverviewNotFound as exc:
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "company_not_found", "message": str(exc)})
            except CompanyOverviewError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "company_overview_unavailable", "message": str(exc)})
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
        if method == "GET" and path.startswith("/v1/etfs/") and path.count("/") == 3:
            symbol = path.removeprefix("/v1/etfs/").strip("/")
            try:
                return self._respond(start_response, HTTPStatus.OK, self.etf_detail_service.get(symbol))
            except ETFDetailNotFound as exc:
                return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "etf_not_found", "message": str(exc)})
            except ETFDetailAPIError as exc:
                return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "etf_detail_unavailable", "message": str(exc)})
        
        if method != "POST":
            return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        try:
            request = _read_json(environ)
            if path == "/v1/valuations":
                symbol = str(request.get("symbol") or "").strip().upper()
                if not symbol:
                    raise ValuationRequestError("symbol is required")

                unsupported = sorted(set(request) - {"symbol"})
                if unsupported:
                    raise ValuationRequestError(
                        "unified valuation endpoint accepts symbol only; "
                        f"unsupported field(s): {', '.join(unsupported)}"
                    )

                self.coverage_service.require_public(
                    symbol,
                    capability="valuation_card",
                )

                card = self.full_market_service.get(symbol)
                valuation = card.get("valuation") or {}
                payload = valuation.get("unified_contract")

                if not isinstance(payload, dict):
                    raise FullMarketCoverageError(
                        f"unified valuation contract unavailable: {symbol}"
                    )
            else:
                return self._respond(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    {"error": "not_found"},
                )
        except CoveragePublicationDenied as exc:
            return self._respond(start_response, HTTPStatus.NOT_FOUND, {
                "error": "company_not_published",
                "publication_tier": exc.publication_tier,
                "reason_code": exc.reason_code,
                "message": str(exc),
            })
        except CoveragePolicyNotFound as exc:
            return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "company_not_found", "message": str(exc)})
        except CoveragePolicyError as exc:
            return self._respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "coverage_policy_unavailable", "message": str(exc)})
        except ValuationRequestError as exc:
            return self._respond(
                start_response,
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_request", "message": str(exc)},
            )
        except Exception as exc:
            return self._respond(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal_error", "message": type(exc).__name__},
            )
        return self._respond(start_response, HTTPStatus.OK, payload)

    @staticmethod
    def _publication_file(
        environ: dict[str, Any],
        start_response: StartResponse,
        path: Path,
        *,
        cache_control: str,
    ) -> list[bytes]:
        try:
            body = path.read_bytes()
        except OSError:
            return ValuationWSGIApp._respond(
                start_response, HTTPStatus.NOT_FOUND, {"error": "publication_file_not_found"}
            )
        etag = f'"{hashlib.sha256(body).hexdigest()}"'
        headers = [
            ("ETag", etag),
            ("Cache-Control", cache_control),
            ("Access-Control-Allow-Origin", os.getenv("AXIOM_CORS_ORIGIN", "*")),
            ("Access-Control-Allow-Headers", "Content-Type, If-None-Match"),
            ("Access-Control-Allow-Methods", "GET, OPTIONS"),
        ]
        if_none_match = str(environ.get("HTTP_IF_NONE_MATCH") or "")
        validators = {
            value.strip().removeprefix("W/") for value in if_none_match.split(",") if value.strip()
        }
        if "*" in validators or etag in validators:
            start_response(f"{HTTPStatus.NOT_MODIFIED.value} {HTTPStatus.NOT_MODIFIED.phrase}", headers)
            return []
        start_response(
            f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
            [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))), *headers],
        )
        return [body]

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
                ("Access-Control-Allow-Headers", "Content-Type, If-None-Match"),
                ("Access-Control-Allow-Methods", "POST, GET, OPTIONS"),
            ],
        )
        return [body]


def _read_json(environ: dict[str, Any]) -> dict[str, Any]:
    if "application/json" not in str(environ.get("CONTENT_TYPE", "")):
        raise ValuationRequestError("Content-Type must be application/json")
    try:
        length = int(environ.get("CONTENT_LENGTH", "0") or 0)
    except (TypeError, ValueError) as exc:
        raise ValuationRequestError("invalid Content-Length") from exc
    if length <= 0 or length > 1_000_000:
        raise ValuationRequestError("request body size is invalid")
    try:
        payload = json.loads(environ["wsgi.input"].read(length).decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValuationRequestError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValuationRequestError("request body must be a JSON object")
    return payload


app = ValuationWSGIApp()
