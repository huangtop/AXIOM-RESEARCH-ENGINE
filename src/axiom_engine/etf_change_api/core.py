from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class ETFChangeAPIError(RuntimeError):
    pass


class ETFChangeNotFound(ETFChangeAPIError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ETFChangeAPIError(f"cannot read {path}: {exc}") from exc


class ETFChangeService:
    def __init__(self, *, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.event_root = self.root / "data/generated/canonical_etf_change_events"
        self._payload: dict[str, Any] | None = None

    def _data(self) -> dict[str, Any]:
        if self._payload is not None:
            return self._payload
        manifest = _load(self.event_root / "manifest.json")
        events = _load(self.event_root / "events.json")
        indexes = _load(self.event_root / "indexes.json")
        companies = _load(self.root / "data/universe/companies.json")
        securities = _load(self.root / "data/universe/securities.json")
        if manifest.get("schema_version") != "canonical-etf-change-events.v031e.3" or not isinstance(events, list) or not isinstance(indexes, Mapping):
            raise ETFChangeAPIError("invalid Canonical ETF Change Event projection")
        company_by_id = {str(row.get("company_id")): row for row in companies if row.get("company_id")}
        ticker_to_companies: dict[str, set[str]] = {}
        for row in securities:
            if str(row.get("status") or "active").lower() != "active":
                continue
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker and row.get("company_id"):
                ticker_to_companies.setdefault(ticker, set()).add(str(row["company_id"]))
        self._payload = {"manifest": manifest, "events": events, "indexes": indexes, "companies": company_by_id, "tickers": ticker_to_companies}
        return self._payload

    @staticmethod
    def _positions(events: list[Any], positions: Any) -> list[Mapping[str, Any]]:
        try:
            return [events[int(position)] for position in positions]
        except (IndexError, TypeError, ValueError) as exc:
            raise ETFChangeAPIError("invalid ETF change event index") from exc

    def company(self, ticker: str) -> dict[str, Any]:
        data = self._data()
        symbol = str(ticker or "").strip().upper()
        company_ids = sorted(data["tickers"].get(symbol, set()))
        if not company_ids:
            raise ETFChangeNotFound(f"ticker not found in company Registry: {symbol}")
        if len(company_ids) != 1:
            raise ETFChangeAPIError(f"ticker maps to multiple company identities: {symbol}")
        company_id = company_ids[0]
        events = self._positions(data["events"], data["indexes"].get("company_id_to_event_positions", {}).get(company_id, []))
        return self._response(events, company={"company_id": company_id, "ticker": symbol, "display_name": data["companies"].get(company_id, {}).get("display_name")})

    def etf(self, ticker: str) -> dict[str, Any]:
        data = self._data()
        symbol = str(ticker or "").strip().upper()
        etf_id = symbol if symbol.startswith("US-") else f"US-{symbol}"
        positions = data["indexes"].get("etf_id_to_event_positions", {}).get(etf_id)
        if positions is None:
            raise ETFChangeNotFound(f"US ETF not found in change projection: {symbol}")
        events = self._positions(data["events"], positions)
        return self._response(events, etf={"etf_id": etf_id, "ticker": etf_id.removeprefix("US-")})

    def _response(self, events: list[Mapping[str, Any]], **identity: Any) -> dict[str, Any]:
        manifest = self._data()["manifest"]
        changed = [row for row in events if row.get("change_type") != "UNCHANGED"]
        return {
            "schema_version": "etf-change-events-api.v031e.3",
            "version": "V031E.3",
            **identity,
            "status": "available" if events else "unavailable",
            "reason_code": None if events else "NO_TOP_HOLDINGS_CHANGE_OBSERVED",
            "summary": {"event_count": len(events), "material_change_count": len(changed)},
            "source": {
                "name": "ETF-ENGINE-V2",
                "coverage": "top_holdings_only",
                "provider_generated_at": manifest.get("source_snapshot", {}).get("provider_generated_at"),
                "interpretation": "Events describe changes in observed top holdings, not official index membership changes.",
            },
            "events": events,
        }
