from __future__ import annotations

import json
import os
from http import HTTPStatus
from typing import Any, Callable, Iterable

from .core import ValuationCardError, get_valuation_card

StartResponse = Callable[[str, list[tuple[str, str]]], Any]


class ValuationCardWSGIApp:
    def __init__(self, research_dir: str | None = None) -> None:
        self.research_dir = research_dir or os.getenv("AXIOM_RESEARCH_DATA", "data/research_data")

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        if method == "OPTIONS" and path == "/v1/research/valuation-card":
            return self._respond(start_response, HTTPStatus.NO_CONTENT, {})
        if method == "GET" and path == "/health":
            return self._respond(start_response, HTTPStatus.OK, {"status": "ok", "source": "canonical_research_bundle"})
        if method != "POST" or path != "/v1/research/valuation-card":
            return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        try:
            request = self._read_json(environ)
            payload = get_valuation_card(ticker=request.get("ticker") or request.get("symbol"), company_id=request.get("company_id"), research_dir=self.research_dir)
        except ValuationCardError as exc:
            return self._respond(start_response, HTTPStatus.BAD_REQUEST, {"error": "valuation_card_unavailable", "message": str(exc)})
        except Exception as exc:
            return self._respond(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error", "message": type(exc).__name__})
        return self._respond(start_response, HTTPStatus.OK, payload)

    @staticmethod
    def _read_json(environ: dict[str, Any]) -> dict[str, Any]:
        if "application/json" not in str(environ.get("CONTENT_TYPE", "")):
            raise ValuationCardError("Content-Type must be application/json")
        length = int(environ.get("CONTENT_LENGTH", "0") or 0)
        if length <= 0 or length > 100000:
            raise ValuationCardError("request body size is invalid")
        payload = json.loads(environ["wsgi.input"].read(length).decode())
        if not isinstance(payload, dict):
            raise ValuationCardError("request body must be a JSON object")
        return payload

    @staticmethod
    def _respond(start_response: StartResponse, status: HTTPStatus, payload: dict[str, Any]) -> list[bytes]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        start_response(f"{status.value} {status.phrase}", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("Access-Control-Allow-Origin", os.getenv("AXIOM_CORS_ORIGIN", "*")),
            ("Access-Control-Allow-Headers", "Content-Type"),
            ("Access-Control-Allow-Methods", "POST, GET, OPTIONS"),
        ])
        return [body]


app = ValuationCardWSGIApp()
