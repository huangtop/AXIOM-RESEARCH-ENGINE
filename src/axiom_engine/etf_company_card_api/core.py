from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class ETFCompanyCardAPIError(RuntimeError):
    pass


class ETFCompanyCardNotFound(ETFCompanyCardAPIError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ETFCompanyCardAPIError(f"cannot read {path}: {exc}") from exc


class ETFCompanyCardService:
    def __init__(self, *, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.projection_root = self.root / "data/generated/etf_company_cards"
        self._payload: dict[str, Any] | None = None

    def _data(self) -> dict[str, Any]:
        if self._payload is not None:
            return self._payload
        manifest = _load(self.projection_root / "manifest.json")
        cards = _load(self.projection_root / "cards.json")
        indexes = _load(self.projection_root / "indexes.json")
        if manifest.get("schema_version") != "etf-company-cards.v031e.4":
            raise ETFCompanyCardAPIError("unsupported ETF Company Card schema")
        if not isinstance(cards, list) or not isinstance(indexes, Mapping):
            raise ETFCompanyCardAPIError("invalid ETF Company Card projection")
        self._payload = {"manifest": manifest, "cards": cards, "indexes": indexes}
        return self._payload

    def get(self, ticker: str) -> dict[str, Any]:
        data = self._data()
        symbol = str(ticker or "").strip().upper()
        etf_id = symbol if symbol.startswith("US-") else f"US-{symbol}"
        if etf_id not in data["indexes"].get("known_etf_ids", []):
            raise ETFCompanyCardNotFound(f"US ETF not found in Canonical exposure: {symbol}")
        positions = data["indexes"].get("etf_id_to_card_positions", {}).get(etf_id, [])
        try:
            cards = [data["cards"][int(position)] for position in positions]
        except (IndexError, TypeError, ValueError) as exc:
            raise ETFCompanyCardAPIError(f"invalid ETF company-card index for {etf_id}") from exc
        return {
            "schema_version": "etf-company-cards-api.v031e.4",
            "version": "V031E.4",
            "etf": {"etf_id": etf_id, "ticker": etf_id.removeprefix("US-")},
            "status": "available" if cards else "unavailable",
            "reason_code": None if cards else "NO_RESOLVED_US_COMPANY_HOLDINGS",
            "summary": {
                "company_card_count": len(cards),
                "valuation_available_count": sum(card["valuation"]["fair_value"] is not None for card in cards),
                "valuation_unavailable_count": sum(card["valuation"]["fair_value"] is None for card in cards),
            },
            "source": {
                "etf_holdings": "ETF-ENGINE-V2 top_holdings_only via Canonical ETF Exposure",
                "valuation": "AXIOM Full-Market Valuation",
                "provider_generated_at": data["manifest"].get("source_snapshots", {}).get("canonical_etf_exposure", {}).get("provider_generated_at"),
                "interpretation": "Portfolio weight is ETF portfolio exposure; valuation availability never determines ETF membership.",
            },
            "company_cards": cards,
        }
