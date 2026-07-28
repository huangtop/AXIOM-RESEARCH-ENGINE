from __future__ import annotations

import json
import zipfile
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.sec_financial_loader.core import METRICS, _debt, _fiscal_year, _latest_annual


EXTRA_METRICS = {
    "stockholders_equity": {
        "statement": "balance_sheet",
        "period_type": "instant",
        "unit": "currency",
        "tags": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    },
    "shares_outstanding_instant": {
        "statement": "balance_sheet",
        "period_type": "instant",
        "unit": "shares",
        "tags": ["CommonStocksIncludingAdditionalPaidInCapitalMember", "CommonStockSharesOutstanding"],
    },
    "ebitda": {
        "statement": "income_statement",
        "period_type": "duration",
        "unit": "currency",
        "tags": ["EarningsBeforeInterestTaxesDepreciationAndAmortization"],
    },
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _scope(root: Path) -> list[dict[str, str]]:
    companies = _load(root / "data/universe/companies.json")
    identity = _load(root / "data/generated/security_identity/security_identity_normalization.json")
    included = {row["company_id"] for row in identity["companies"] if row["valuation_scope_status"] == "included"}
    output = []
    for row in companies:
        if row["company_id"] not in included:
            continue
        cik = str((row.get("metadata") or {}).get("cik") or "").zfill(10)
        if cik.strip("0"):
            output.append({"company_id": row["company_id"], "cik": cik})
    return sorted(output, key=lambda row: row["company_id"])


def _fact(company_id: str, cik: str, metric: str, spec: Mapping[str, Any], found: tuple[str, Mapping[str, Any]]) -> dict[str, Any]:
    tag, row = found
    return {
        "financial_fact_id": f"financial_fact:{cik}:{metric}:{row['end']}:FY",
        "company_id": company_id,
        "metric": metric,
        "value": str(row["val"]),
        "unit": spec["unit"],
        "currency": "USD" if spec["unit"] == "currency" else None,
        "period_type": spec["period_type"],
        "period_start": row.get("start"),
        "period_end": row["end"],
        "fiscal_year": _fiscal_year(dict(row)),
        "fiscal_period": "FY",
        "statement": spec["statement"],
        "form_type": row.get("form"),
        "accession_number": row.get("accn"),
        "source": {"provider": "sec_companyfacts", "cik": cik, "xbrl_tag": tag},
    }


def build_sec_financial_population(
    root: Path,
    *,
    bulk_zip: Path | None = None,
    cache_dir: str = "data/generated/provider_cache/sec/companyfacts",
    limit: int | None = None,
    offset: int = 0,
    write_cache: bool = False,
    cache_ttl_days: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    scope = _scope(root)
    source_scope_count = len(scope)
    scope = scope[offset:]
    if limit is not None:
        scope = scope[:limit]
    cache_root = root / cache_dir
    bulk_archive = zipfile.ZipFile(bulk_zip) if bulk_zip else None
    bulk_names = set(bulk_archive.namelist()) if bulk_archive else set()
    facts: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    company_coverage: Counter[str] = Counter()
    source_modes: Counter[str] = Counter()
    all_specs = {**METRICS, **EXTRA_METRICS}
    for company in scope:
        cik = company["cik"]
        cache_path = cache_root / f"CIK{cik}.json"
        cache_is_fresh = cache_path.is_file() and current.timestamp() - cache_path.stat().st_mtime <= cache_ttl_days * 86_400
        if cache_is_fresh:
            payload, mode = _load(cache_path), "cache"
        elif f"CIK{cik}.json" in bulk_names and bulk_archive is not None:
            payload = json.loads(bulk_archive.read(f"CIK{cik}.json"))
            mode = "sec_bulk"
            if write_cache:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        elif cache_path.is_file():
            payload, mode = _load(cache_path), "stale_cache_fallback"
        else:
            diagnostics.append({**company, "reason_code": "SEC_COMPANYFACTS_NOT_AVAILABLE"})
            continue
        source_modes[mode] += 1
        company_facts: dict[str, dict[str, Any]] = {}
        for metric, spec in all_specs.items():
            found = _debt(payload) if metric == "total_debt" else _latest_annual(payload, spec)
            if found:
                company_facts[metric] = _fact(company["company_id"], cik, metric, spec, found)
                company_coverage[metric] += 1
        equity = company_facts.get("stockholders_equity")
        shares = company_facts.get("shares_outstanding_instant")
        if equity and shares and Decimal(shares["value"]) > 0 and equity["period_end"] == shares["period_end"]:
            value = Decimal(equity["value"]) / Decimal(shares["value"])
            company_facts["book_value_per_share"] = {
                "financial_fact_id": f"financial_fact:{cik}:book_value_per_share:{equity['period_end']}:FY",
                "company_id": company["company_id"], "metric": "book_value_per_share", "value": str(value),
                "unit": "currency_per_share", "currency": "USD", "period_type": "instant",
                "period_end": equity["period_end"], "fiscal_year": equity["fiscal_year"], "fiscal_period": "FY",
                "statement": "derived", "form_type": equity["form_type"], "accession_number": equity["accession_number"],
                "source": {"provider": "sec_companyfacts", "formula_version": "book_value_per_share.v031v.3", "source_fact_ids": [equity["financial_fact_id"], shares["financial_fact_id"]]},
            }
            company_coverage["book_value_per_share"] += 1
        facts.extend(company_facts.values())
    if bulk_archive is not None:
        bulk_archive.close()
    companies_with_facts = len({row["company_id"] for row in facts})
    coverage_names = [*all_specs, "book_value_per_share"]
    return {
        "schema_version": "sec-financial-population.v031v.3", "version": "V031V.3", "generated_at": current.isoformat(),
        "summary": {"valuation_scope_company_count": 5876, "cik_scope_company_count": source_scope_count, "batch_offset": offset, "companies_requested": len(scope), "companies_with_companyfacts": sum(source_modes.values()), "companies_with_financial_facts": companies_with_facts, "financial_fact_count": len(facts), "metric_company_coverage": {name: company_coverage[name] for name in coverage_names}, "source_mode_counts": dict(sorted(source_modes.items())), "missing_companyfacts_count": len(diagnostics), "cache_ttl_days": cache_ttl_days},
        "financial_facts": facts, "diagnostics": diagnostics,
    }


def write_sec_financial_population(report: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in {"manifest.json": {key: report[key] for key in ("schema_version", "version", "generated_at", "summary")}, "financial_facts.json": report["financial_facts"], "diagnostics.json": report["diagnostics"]}.items():
        temporary = output_dir / f"{name}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_dir / name)
