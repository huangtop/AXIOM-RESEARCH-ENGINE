from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class ETFExposureAPIError(RuntimeError):
    pass


class ETFExposureNotFound(ETFExposureAPIError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ETFExposureAPIError(f"cannot read {path}: {exc}") from exc


class ETFExposureService:
    def __init__(
        self,
        *,
        root: Path | None = None,
        exposure_root: Path | None = None,
        companies_path: Path | None = None,
        securities_path: Path | None = None,
        identity_path: Path | None = None,
    ) -> None:
        self.root = root or Path.cwd()
        self.exposure_root = exposure_root or self.root / "data/generated/canonical_etf_exposure"
        self.companies_path = companies_path or self.root / "data/universe/companies.json"
        self.securities_path = securities_path or self.root / "data/universe/securities.json"
        self.identity_path = identity_path or self.root / "data/generated/security_identity/security_identity_normalization.json"
        self._payload: dict[str, Any] | None = None

    def _load_payload(self) -> dict[str, Any]:
        if self._payload is not None:
            return self._payload
        manifest = _load(self.exposure_root / "manifest.json")
        exposures = _load(self.exposure_root / "etf_exposures.json")
        indexes = _load(self.exposure_root / "indexes.json")
        companies = _load(self.companies_path)
        securities = _load(self.securities_path)
        identity = _load(self.identity_path)
        if manifest.get("schema_version") != "canonical-etf-exposure.v031e.1":
            raise ETFExposureAPIError("unsupported Canonical ETF Exposure schema")
        if not all(isinstance(value, list) for value in (exposures, companies, securities)) or not isinstance(indexes, Mapping) or identity.get("schema_version") != "security-identity-normalization.v031v.2":
            raise ETFExposureAPIError("ETF Exposure API inputs are invalid")
        eligible_security_ids = {
            str(row.get("security_id")) for row in identity.get("securities") or []
            if row.get("instrument_type") == "common_or_ordinary_equity" and row.get("security_id")
        }
        company_by_id = {str(row.get("company_id")): row for row in companies if row.get("company_id")}
        symbols: dict[str, list[Mapping[str, Any]]] = {}
        for security in securities:
            if str(security.get("security_id") or "") not in eligible_security_ids:
                continue
            if str(security.get("status") or "active").lower() != "active":
                continue
            symbol = str(security.get("ticker") or "").strip().upper()
            if symbol:
                symbols.setdefault(symbol, []).append(security)
        self._payload = {
            "manifest": manifest,
            "exposures": exposures,
            "positions": indexes.get("company_id_to_exposure_positions") or {},
            "company_by_id": company_by_id,
            "symbols": symbols,
        }
        return self._payload

    def get(self, ticker: str) -> dict[str, Any]:
        symbol = str(ticker or "").strip().upper()
        payload = self._load_payload()
        candidates = payload["symbols"].get(symbol, [])
        company_ids = sorted({str(row.get("company_id")) for row in candidates if row.get("company_id")})
        if not company_ids:
            raise ETFExposureNotFound(f"ticker not found in company Registry: {symbol}")
        if len(company_ids) > 1:
            raise ETFExposureAPIError(f"ticker maps to multiple company identities: {symbol}")
        company_id = company_ids[0]
        company = payload["company_by_id"].get(company_id, {})
        positions = payload["positions"].get(company_id, [])
        try:
            exposures = [payload["exposures"][int(position)] for position in positions]
        except (IndexError, TypeError, ValueError) as exc:
            raise ETFExposureAPIError(f"invalid ETF exposure index for {company_id}") from exc
        exposures = sorted(exposures, key=lambda row: (-float(row.get("portfolio_weight") or 0), str(row.get("etf_id") or "")))
        unavailable_as_of = sum(not row.get("as_of") for row in exposures)
        return {
            "schema_version": "company-etf-exposure-api.v031e.1",
            "version": "V031E.1D",
            "company": {
                "company_id": company_id,
                "ticker": symbol,
                "display_name": company.get("display_name") or company.get("legal_name"),
            },
            "status": "available" if exposures else "unavailable",
            "reason_code": None if exposures else "NO_TOP_HOLDINGS_EXPOSURE_OBSERVED",
            "summary": {
                "holding_etf_count": len(exposures),
                "maximum_portfolio_weight": max((float(row["portfolio_weight"]) for row in exposures), default=None),
                "maximum_portfolio_weight_percent": max((float(row["portfolio_weight_percent"]) for row in exposures), default=None),
                "as_of_available_count": len(exposures) - unavailable_as_of,
                "as_of_unavailable_count": unavailable_as_of,
            },
            "source": {
                "name": "ETF-ENGINE-V2",
                "source_status": payload["manifest"]["summary"]["source_status"],
                "provider_generated_at": payload["manifest"]["source_snapshot"]["provider_generated_at"],
                "snapshot_id": payload["manifest"]["source_snapshot"]["snapshot_id"],
                "interpretation": "Portfolio weight is the holding share of the ETF portfolio, not ETF ownership of the company.",
            },
            "exposures": [{
                "etf_id": row["etf_id"],
                "etf_ticker": row.get("etf_ticker"),
                "etf_name": row.get("etf_name"),
                "etf_name_en": row.get("etf_name_en"),
                "portfolio_weight": row["portfolio_weight"],
                "portfolio_weight_percent": row["portfolio_weight_percent"],
                "as_of": row.get("as_of"),
                "as_of_status": row.get("as_of_status"),
                "source_status": row.get("source_status"),
            } for row in exposures],
        }
