from __future__ import annotations

from typing import Any

from axiom_engine.etf_change_api import ETFChangeAPIError, ETFChangeNotFound, ETFChangeService
from axiom_engine.etf_company_card_api import (
    ETFCompanyCardAPIError,
    ETFCompanyCardNotFound,
    ETFCompanyCardService,
)


class ETFDetailAPIError(RuntimeError):
    pass


class ETFDetailNotFound(ETFDetailAPIError):
    pass


class ETFDetailService:
    def __init__(
        self,
        *,
        company_card_service: ETFCompanyCardService | None = None,
        change_service: ETFChangeService | None = None,
    ) -> None:
        self.company_card_service = company_card_service or ETFCompanyCardService()
        self.change_service = change_service or ETFChangeService()

    def get(self, ticker: str) -> dict[str, Any]:
        symbol = str(ticker or "").strip().upper()
        try:
            card_payload = self.company_card_service.get(symbol)
        except ETFCompanyCardNotFound as exc:
            raise ETFDetailNotFound(str(exc)) from exc
        except ETFCompanyCardAPIError as exc:
            raise ETFDetailAPIError(f"ETF company cards unavailable: {exc}") from exc

        cards = card_payload["company_cards"]
        first = cards[0] if cards else {}
        exposure_weights = [
            float(card.get("exposure", {}).get("portfolio_weight") or 0) for card in cards
        ]
        profile = {
            **card_payload["etf"],
            "name": first.get("etf_name"),
            "listing_market": "US",
            "holdings_coverage": "top_holdings_only",
        }
        holdings = {
            "status": card_payload["status"],
            "reason_code": card_payload["reason_code"],
            "summary": {
                **card_payload["summary"],
                "observed_portfolio_weight": round(sum(exposure_weights), 8),
                "observed_portfolio_weight_percent": round(sum(exposure_weights) * 100, 6),
                "top_3_observed_weight": round(sum(exposure_weights[:3]), 8),
                "top_10_observed_weight": round(sum(exposure_weights[:10]), 8),
            },
            "company_cards": cards,
        }

        try:
            change_payload = self.change_service.etf(symbol)
            material = [
                event
                for event in change_payload["events"]
                if event.get("change_type") != "UNCHANGED"
            ]
            changes = {
                "status": "available" if material else "unavailable",
                "reason_code": None if material else "NO_MATERIAL_TOP_HOLDINGS_CHANGE_OBSERVED",
                "summary": {
                    "observed_event_count": len(change_payload["events"]),
                    "material_change_count": len(material),
                },
                "events": material,
                "source": change_payload["source"],
            }
        except ETFChangeNotFound:
            changes = self._unavailable_changes("NO_TOP_HOLDINGS_TRANSITION_OBSERVED")
        except ETFChangeAPIError:
            changes = self._unavailable_changes("ETF_CHANGE_PROJECTION_UNAVAILABLE")

        return {
            "schema_version": "etf-detail-api.v031e.5",
            "version": "V031E.5",
            "etf": profile,
            "status": "available",
            "components": {
                "holdings": holdings["status"],
                "company_cards": card_payload["status"],
                "changes": changes["status"],
            },
            "holdings": holdings,
            "changes": changes,
            "source": {
                "holdings": card_payload["source"],
                "write_back_to_etf_engine": False,
            },
        }

    @staticmethod
    def _unavailable_changes(reason: str) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "reason_code": reason,
            "summary": {"observed_event_count": 0, "material_change_count": 0},
            "events": [],
            "source": {
                "name": "ETF-ENGINE-V2",
                "coverage": "top_holdings_only",
                "interpretation": "No verified top-holdings transition is currently available.",
            },
        }
