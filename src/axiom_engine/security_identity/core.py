from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


INSTRUMENT_RULES = (
    ("exchange_traded_fund", (r"\bETF\b", r"\bexchange[- ]traded fund\b")),
    ("exchange_traded_note", (r"\bETN\b", r"\bexchange[- ]traded notes?\b")),
    ("commodity_trust", (r"\b(?:gold|silver|bitcoin|oil|commodity) trust\b", r"\bcommodity pool\b")),
    ("investment_fund", (r"\bclosed[- ]end fund\b", r"\binvestment fund shares\b")),
    ("warrant", (r"\bwarrants?\b", r"\.W(?:S)?$")),
    ("subscription_right", (r"\brights?\b", r"\.R$")),
    ("unit", (r"\bunits?\b", r"\.U$")),
    (
        "preferred_stock",
        (
            r"\bpreferred (?:stock|shares?)\b",
            r"\bdepositary shares?.*preferred\b",
            r"\bcumulative redeemable preferred\b",
            r"\$[A-Z]$",
        ),
    ),
)

NAME_ONLY_INSTRUMENT_TYPES = {
    "exchange_traded_fund",
    "exchange_traded_note",
    "commodity_trust",
    "investment_fund",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _classify(row: Mapping[str, Any]) -> tuple[str, str]:
    declared_type = str(row.get("security_type") or "").strip().lower()
    declared_non_company = {
        "etf": "exchange_traded_fund",
        "exchange_traded_fund": "exchange_traded_fund",
        "etn": "exchange_traded_note",
        "exchange_traded_note": "exchange_traded_note",
        "fund": "investment_fund",
        "closed_end_fund": "investment_fund",
        "commodity": "commodity_trust",
        "future": "futures_contract",
        "futures": "futures_contract",
    }
    if declared_type in declared_non_company:
        return declared_non_company[declared_type], "DECLARED_SECURITY_TYPE"
    name = str((row.get("metadata") or {}).get("security_name") or "")
    ticker = str(row.get("ticker") or "")
    text = f"{name} {ticker}"
    for instrument_type, patterns in INSTRUMENT_RULES:
        searchable = name if instrument_type in NAME_ONLY_INSTRUMENT_TYPES else text
        if any(re.search(pattern, searchable, flags=re.IGNORECASE) for pattern in patterns):
            return instrument_type, "OFFICIAL_SECURITY_NAME_OR_SYMBOL_PATTERN"
    return "common_or_ordinary_equity", "NO_NON_COMMON_INSTRUMENT_SIGNAL"


def build_security_identity_normalization(
    root: Path,
    *,
    companies_path: str = "data/universe/companies.json",
    securities_path: str = "data/universe/securities.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    companies = _load(root / companies_path)
    securities = _load(root / securities_path)
    if not isinstance(companies, list) or not isinstance(securities, list):
        raise ValueError("universe companies and securities must be arrays")
    by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    normalized_securities: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    for security in securities:
        instrument_type, reason_code = _classify(security)
        valuation_eligible = instrument_type == "common_or_ordinary_equity"
        record = {
            "security_id": security.get("security_id"),
            "company_id": security.get("company_id"),
            "ticker": security.get("ticker"),
            "exchange": security.get("exchange"),
            "instrument_type": instrument_type,
            "valuation_eligible": valuation_eligible,
            "reason_code": reason_code,
            "source_record_ids": list((security.get("metadata") or {}).get("source_ids") or []),
        }
        normalized_securities.append(record)
        by_company[str(security.get("company_id") or "")].append(record)
        type_counts[instrument_type] += 1
    normalized_companies: list[dict[str, Any]] = []
    excluded_counts: Counter[str] = Counter()
    for company in companies:
        company_id = str(company.get("company_id") or "")
        linked = by_company.get(company_id, [])
        eligible = [row for row in linked if row["valuation_eligible"]]
        if eligible:
            status, reason = "included", "COMMON_OR_ORDINARY_EQUITY_PRESENT"
        elif linked:
            types = sorted({str(row["instrument_type"]) for row in linked})
            status, reason = "excluded", "NON_COMPANY_INSTRUMENT_ONLY"
            excluded_counts.update(types)
        else:
            status, reason = "excluded", "NO_ACTIVE_SECURITY"
            excluded_counts["no_active_security"] += 1
        normalized_companies.append({
            "company_id": company_id,
            "valuation_scope_status": status,
            "reason_code": reason,
            "eligible_security_ids": [row["security_id"] for row in eligible],
            "excluded_security_ids": [row["security_id"] for row in linked if not row["valuation_eligible"]],
        })
    included = sum(row["valuation_scope_status"] == "included" for row in normalized_companies)
    return {
        "schema_version": "security-identity-normalization.v031v.2",
        "version": "V031V.2",
        "generated_at": current.isoformat(),
        "summary": {
            "registry_company_count": len(companies),
            "registry_security_count": len(securities),
            "valuation_company_count": included,
            "excluded_company_count": len(companies) - included,
            "instrument_type_counts": dict(sorted(type_counts.items())),
            "excluded_company_reason_counts": dict(sorted(excluded_counts.items())),
        },
        "companies": normalized_companies,
        "securities": normalized_securities,
        "indexes": {
            "company_id_to_position": {row["company_id"]: index for index, row in enumerate(normalized_companies)},
            "security_id_to_position": {str(row["security_id"]): index for index, row in enumerate(normalized_securities)},
        },
    }


def write_security_identity_normalization(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
