from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from axiom_engine.config import GENERATED_DIR


DEFAULT_SNAPSHOT_PATH = GENERATED_DIR / "fair_value" / "fair_value_snapshot.json"


class FairValueSnapshotAPIError(ValueError):
    """Raised when the read-only fair-value snapshot cannot serve a request."""


class FairValueSnapshotNotFound(FairValueSnapshotAPIError):
    """Raised when a ticker is absent from the current snapshot."""


class FairValueSnapshotService:
    """Read-only query facade over the generated V030.14 fair-value snapshot."""

    def __init__(self, snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH) -> None:
        self.snapshot_path = Path(snapshot_path)

    def list_companies(self) -> dict[str, Any]:
        snapshot = self._load()
        return {
            "api_version": "1.0",
            "endpoint_mode": "fair_value_snapshot",
            "schema_version": snapshot["schema_version"],
            "snapshot_version": snapshot.get("version"),
            "generated_at": snapshot.get("generated_at"),
            "as_of_date": snapshot.get("as_of_date"),
            "summary": snapshot.get("summary", {}),
            "companies": [self._company_summary(row) for row in snapshot["companies"]],
        }

    def get_company(self, symbol: str) -> dict[str, Any]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            raise FairValueSnapshotAPIError("symbol is required")

        snapshot = self._load()
        position = (snapshot.get("indexes") or {}).get("symbol_to_position", {}).get(normalized)
        row: dict[str, Any] | None = None
        if isinstance(position, int) and 0 <= position < len(snapshot["companies"]):
            candidate = snapshot["companies"][position]
            if str(candidate.get("symbol", "")).upper() == normalized:
                row = candidate
        if row is None:
            row = next(
                (
                    candidate
                    for candidate in snapshot["companies"]
                    if str(candidate.get("symbol", "")).upper() == normalized
                ),
                None,
            )
        if row is None:
            raise FairValueSnapshotNotFound(
                f"symbol is not available in fair-value snapshot: {normalized}"
            )

        return {
            "api_version": "1.0",
            "endpoint_mode": "fair_value_snapshot",
            "schema_version": snapshot["schema_version"],
            "snapshot_version": snapshot.get("version"),
            "generated_at": snapshot.get("generated_at"),
            "source_as_of_date": snapshot.get("as_of_date"),
            **row,
        }

    def _load(self) -> dict[str, Any]:
        if not self.snapshot_path.exists():
            raise FairValueSnapshotAPIError(
                f"fair-value snapshot not found: {self.snapshot_path}"
            )
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FairValueSnapshotAPIError("fair-value snapshot is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise FairValueSnapshotAPIError("fair-value snapshot must be a JSON object")
        if payload.get("schema_version") != "fair-value-snapshot.v030.14.0":
            raise FairValueSnapshotAPIError("unsupported fair-value snapshot schema")
        if not isinstance(payload.get("companies"), list):
            raise FairValueSnapshotAPIError("fair-value snapshot companies must be an array")
        return payload

    @staticmethod
    def _company_summary(row: dict[str, Any]) -> dict[str, Any]:
        card = row.get("valuation_card") or {}
        return {
            "company_id": row.get("company_id"),
            "symbol": row.get("symbol"),
            "company_name": row.get("company_name"),
            "currency": row.get("currency"),
            "as_of_date": row.get("as_of_date"),
            "snapshot_state": row.get("snapshot_state"),
            "current_price": card.get("current_price"),
            "fair_value": card.get("fair_value"),
            "upside": card.get("upside"),
            "rating": card.get("rating"),
            "confidence": card.get("confidence"),
        }
