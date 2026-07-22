from __future__ import annotations

import json
import os
from http import HTTPStatus
from typing import Any, Callable, Iterable

from axiom_engine.previous_close import PreviousCloseError, YahooPreviousCloseAdapter
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
    ) -> None:
        close_provider = YahooPreviousCloseAdapter()
        self.production_service = production_service or BackendValuationAPIService(close_provider)
        self.legacy_service = legacy_service or LegacyValuationAPIService(close_provider)

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        if method == "OPTIONS" and path in {"/v1/valuations", "/v1/debug/valuations/legacy-parity"}:
            return self._respond(start_response, HTTPStatus.NO_CONTENT, {})
        if method == "GET" and path == "/health":
            return self._respond(start_response, HTTPStatus.OK, {"status": "ok"})
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
