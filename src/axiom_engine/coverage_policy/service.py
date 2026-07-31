from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .core import CoveragePolicyError


def _symbol_key(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", ".").replace("/", ".")


class CoveragePolicyNotFound(CoveragePolicyError):
    pass


class CoveragePublicationDenied(CoveragePolicyError):
    def __init__(self, ticker: str, record: Mapping[str, Any]) -> None:
        self.ticker = ticker
        self.record = record
        self.publication_tier = str(record.get("publication_tier") or "contextual")
        if self.publication_tier == "candidate":
            self.reason_code = "CANDIDATE_NOT_YET_PUBLISHED"
        elif self.publication_tier == "excluded":
            self.reason_code = "NON_OPERATING_COMPANY_INSTRUMENT"
        else:
            self.reason_code = "CONTEXTUAL_COMPANY_NOT_COVERED"
        super().__init__(f"ticker is not published by Coverage Policy: {ticker} ({self.publication_tier})")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoveragePolicyError(f"cannot read Coverage Policy source {path}: {exc}") from exc


class CoveragePolicyService:
    def __init__(self, *, root: Path | None = None, projection_path: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.projection_path = projection_path or self.root / "data/generated/coverage_policy/coverage_policy.json"
        self._payload: dict[str, Any] | None = None
        self._ticker_to_company: dict[str, str] | None = None

    def _data(self) -> dict[str, Any]:
        if self._payload is None:
            payload = _load(self.projection_path)
            if payload.get("schema_version") != "coverage-policy-projection.v031f.1":
                raise CoveragePolicyError("unsupported Coverage Policy projection")
            if not isinstance(payload.get("records"), list) or not isinstance(payload.get("indexes"), Mapping):
                raise CoveragePolicyError("invalid Coverage Policy projection")
            self._payload = payload
        return self._payload

    def _registry_tickers(self) -> dict[str, str]:
        if self._ticker_to_company is None:
            rows = _load(self.root / "data/universe/securities.json")
            if not isinstance(rows, list):
                raise CoveragePolicyError("security registry must be an array")
            self._ticker_to_company = {
                _symbol_key(row.get("ticker")): str(row.get("company_id"))
                for row in rows
                if row.get("ticker") and row.get("company_id") and row.get("status") in (None, "active")
            }
        return self._ticker_to_company

    def get(self, ticker: str) -> Mapping[str, Any]:
        symbol = str(ticker or "").strip().upper()
        if not symbol:
            raise CoveragePolicyNotFound("ticker is required")
        data = self._data()
        explicit_company_id = data["indexes"].get("ticker_to_company_id", {}).get(symbol)
        if explicit_company_id:
            position = data["indexes"].get("company_id_to_position", {}).get(explicit_company_id)
            if isinstance(position, int) and 0 <= position < len(data["records"]):
                return data["records"][position]
            raise CoveragePolicyError(f"invalid Coverage Policy index for {symbol}")
        company_id = self._registry_tickers().get(_symbol_key(symbol))
        if company_id is None:
            raise CoveragePolicyNotFound(f"ticker is absent from the company Registry: {symbol}")
        position = data["indexes"].get("company_id_to_position", {}).get(company_id)
        if isinstance(position, int) and 0 <= position < len(data["records"]):
            return data["records"][position]
        return {
            "company_id": company_id,
            "ticker": symbol,
            "research_scope": "contextual",
            "publication_tier": data["contract"]["unlisted_company_default_tier"],
            "publication": {"company_page": False, "valuation_card": False, "visibility": "embedded_only"},
            "valuation": {"scope_status": "not_covered", "reason_code": "CONTEXTUAL_COMPANY_NO_VALUATION_COMMITMENT"},
            "reason_codes": ["IDENTITY_RESOLVED_CONTEXT_ONLY"],
            "review_status": "automatic_default",
        }

    def require_public(self, ticker: str, *, capability: str = "company_page") -> Mapping[str, Any]:
        record = self.get(ticker)
        if not bool((record.get("publication") or {}).get(capability)):
            raise CoveragePublicationDenied(str(ticker).strip().upper(), record)
        return record

    def public_company_ids(self) -> set[str]:
        return {
            str(row["company_id"])
            for row in self._data()["records"]
            if bool((row.get("publication") or {}).get("company_page"))
        }

    def public_tickers(self) -> set[str]:
        return {
            str(row["ticker"]).upper()
            for row in self._data()["records"]
            if row.get("ticker") and bool((row.get("publication") or {}).get("company_page"))
        }
