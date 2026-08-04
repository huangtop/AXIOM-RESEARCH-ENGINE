from __future__ import annotations

import json
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

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

QUARTERLY_METRICS = {
    key: value
    for key, value in METRICS.items()
    if key in {"revenue", "net_income", "operating_cash_flow", "capital_expenditures", "diluted_shares_outstanding"}
}
QUARTERLY_METRICS["diluted_eps"] = {
    "statement": "income_statement",
    "period_type": "duration",
    "unit": "currency_per_share",
    "tags": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
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


def _quarter_unit_rows(fact: Mapping[str, Any], unit: str) -> list[Mapping[str, Any]]:
    units = fact.get("units") if isinstance(fact.get("units"), Mapping) else {}
    preferred = {
        "currency": ("USD", "usd"),
        "shares": ("shares", "SHARES"),
        "currency_per_share": ("USD/shares", "usd/shares", "USD / shares"),
    }[unit]
    for name in preferred:
        if name in units and isinstance(units[name], list):
            return units[name]
    return []


def _is_discrete_quarter(row: Mapping[str, Any]) -> bool:
    if str(row.get("fp") or "").upper() not in {"Q1", "Q2", "Q3", "Q4"}:
        return False
    if str(row.get("form") or "").upper() not in {"10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}:
        return False
    try:
        days = (date.fromisoformat(str(row["end"])) - date.fromisoformat(str(row["start"]))).days
    except (KeyError, TypeError, ValueError):
        return False
    return 60 <= days <= 120


def _is_annual_duration(row: Mapping[str, Any]) -> bool:
    if str(row.get("fp") or "").upper() != "FY":
        return False
    try:
        days = (date.fromisoformat(str(row["end"])) - date.fromisoformat(str(row["start"]))).days
    except (KeyError, TypeError, ValueError):
        return False
    return 300 <= days <= 430


def _duration_days(row: Mapping[str, Any]) -> int | None:
    try:
        return (date.fromisoformat(str(row["end"])) - date.fromisoformat(str(row["start"]))).days
    except (KeyError, TypeError, ValueError):
        return None


def _observation_rank(row: Mapping[str, Any], tag_priority: int) -> tuple[str, str, int]:
    return (str(row.get("filed") or ""), str(row.get("accn") or ""), -tag_priority)


def _quarterly_facts(company_id: str, cik: str, payload: Mapping[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    us_gaap = ((payload.get("facts") or {}).get("us-gaap") or {})
    selected: dict[tuple[str, int, str], tuple[str, Mapping[str, Any], Mapping[str, Any]]] = {}
    annual: dict[tuple[str, int], tuple[str, Mapping[str, Any], Mapping[str, Any]]] = {}
    cumulative: dict[tuple[str, str, str], tuple[str, Mapping[str, Any], Mapping[str, Any], int]] = {}
    for metric, spec in QUARTERLY_METRICS.items():
        for tag_priority, tag in enumerate(spec["tags"]):
            fact = us_gaap.get(tag)
            if not isinstance(fact, Mapping):
                continue
            for row in _quarter_unit_rows(fact, str(spec["unit"])):
                if row.get("val") is None:
                    continue
                fiscal_year = int(row.get("fy") or 0)
                fiscal_period = str(row.get("fp") or "").upper()
                if not fiscal_year or not row.get("start") or not row.get("end"):
                    continue
                days = _duration_days(row)
                if days is not None and 121 <= days <= 300 and fiscal_period in {"Q2", "Q3"}:
                    cumulative_key = (metric, str(row["start"]), str(row["end"]))
                    old_cumulative = cumulative.get(cumulative_key)
                    if old_cumulative is None or _observation_rank(row, tag_priority) > _observation_rank(old_cumulative[1], old_cumulative[3]):
                        cumulative[cumulative_key] = (tag, row, spec, tag_priority)
                if _is_annual_duration(row):
                    annual_key = (metric, fiscal_year)
                    old_annual = annual.get(annual_key)
                    sort_key = (str(row.get("filed") or ""), str(row.get("accn") or ""))
                    old_key = (str((old_annual or (None, {}))[1].get("filed") or ""), str((old_annual or (None, {}))[1].get("accn") or ""))
                    if old_annual is None or sort_key > old_key:
                        annual[annual_key] = (tag, row, spec)
                    continue
                if not _is_discrete_quarter(row):
                    continue
                key = (metric, fiscal_year, fiscal_period)
                old = selected.get(key)
                sort_key = (str(row.get("filed") or ""), str(row.get("accn") or ""))
                old_key = (str((old or (None, {}))[1].get("filed") or ""), str((old or (None, {}))[1].get("accn") or ""))
                if old is None or sort_key > old_key:
                        selected[key] = (tag, row, spec)
    # Cash-flow statements in 10-Q filings are normally year-to-date. Convert them
    # to discrete quarters so the UI never compares a six-month inflow with a
    # three-month capital expenditure (or presents YTD as "current quarter").
    by_metric_start = {}
    for (metric, start, _), item in cumulative.items():
        by_metric_start.setdefault((metric, start), []).append(item)
    for (metric, start), items in by_metric_start.items():
        items.sort(key=lambda item: str(item[1]["end"]))
        prior_row = None
        direct_q1 = [value for (name, _, period), value in selected.items() if name == metric and period == "Q1" and str(value[1].get("start")) == start]
        if direct_q1:
            prior_row = max(direct_q1, key=lambda value: str(value[1].get("filed") or ""))[1]
        for tag, row, spec, _ in items:
            if prior_row is None:
                prior_row = row
                continue
            fiscal_period = str(row.get("fp") or "").upper()
            fiscal_year = int(str(row["end"])[:4])
            key = (metric, fiscal_year, fiscal_period)
            try:
                value = Decimal(str(row["val"])) - Decimal(str(prior_row["val"]))
            except (KeyError, ValueError):
                prior_row = row
                continue
            if key not in selected:
                derived_row = dict(row)
                derived_row.update({
                    "val": value,
                    "start": prior_row.get("end"),
                    "_derivation_type": "ytd_less_prior_ytd",
                    "_source_accessions": [value for value in (row.get("accn"), prior_row.get("accn")) if value],
                })
                selected[key] = (tag, derived_row, spec)
            prior_row = row
    for (metric, fiscal_year), (tag, annual_row, spec) in annual.items():
        q4_key = (metric, fiscal_year, "Q4")
        quarter_keys = [(metric, fiscal_year, name) for name in ("Q1", "Q2", "Q3")]
        if q4_key in selected or any(key not in selected for key in quarter_keys):
            continue
        quarter_rows = [selected[key][1] for key in quarter_keys]
        try:
            q4_value = Decimal(str(annual_row["val"])) - sum(
                (Decimal(str(row["val"])) for row in quarter_rows), Decimal("0")
            )
        except (KeyError, ValueError):
            continue
        derived_row = dict(annual_row)
        derived_row.update({
            "val": q4_value,
            "fp": "Q4",
            "start": None,
            "_derivation_type": "annual_less_q1_q2_q3",
            "_source_accessions": [row.get("accn") for row in [annual_row, *quarter_rows] if row.get("accn")],
        })
        selected[q4_key] = (tag, derived_row, spec)
    period_ends = sorted({str(row.get("end")) for _, row, _ in selected.values() if row.get("end")})[-limit:]
    allowed_ends = set(period_ends)
    output: list[dict[str, Any]] = []
    for (metric, fiscal_year, fiscal_period), (tag, row, spec) in selected.items():
        if str(row.get("end")) not in allowed_ends:
            continue
        output.append({
            "financial_fact_id": f"quarterly_financial_fact:{cik}:{metric}:{row['end']}:{fiscal_period}",
            "company_id": company_id,
            "metric": metric,
            "value": str(row["val"]),
            "unit": spec["unit"],
            "currency": "USD" if spec["unit"] in {"currency", "currency_per_share"} else None,
            "period_type": "duration",
            "period_start": row.get("start"),
            "period_end": row["end"],
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period,
            "statement": spec["statement"],
            "form_type": row.get("form"),
            "filed_at": row.get("filed"),
            "accession_number": row.get("accn"),
            "source": {"provider": "sec_companyfacts", "cik": cik, "xbrl_tag": tag, "period_selection": row.get("_derivation_type") or "discrete_quarter_60_to_120_days", "source_accessions": row.get("_source_accessions") or [row.get("accn")]},
        })
    return sorted(output, key=lambda row: (str(row["period_end"]), str(row["metric"])))


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
    quarterly_facts: list[dict[str, Any]] = []
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
        quarterly_facts.extend(_quarterly_facts(company["company_id"], cik, payload))
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
        "summary": {"valuation_scope_company_count": 5876, "cik_scope_company_count": source_scope_count, "batch_offset": offset, "companies_requested": len(scope), "companies_with_companyfacts": sum(source_modes.values()), "companies_with_financial_facts": companies_with_facts, "financial_fact_count": len(facts), "quarterly_financial_fact_count": len(quarterly_facts), "quarterly_company_count": len({row["company_id"] for row in quarterly_facts}), "metric_company_coverage": {name: company_coverage[name] for name in coverage_names}, "source_mode_counts": dict(sorted(source_modes.items())), "missing_companyfacts_count": len(diagnostics), "cache_ttl_days": cache_ttl_days},
        "financial_facts": facts, "quarterly_financial_facts": quarterly_facts, "diagnostics": diagnostics,
    }


def write_sec_financial_population(report: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    quarterly_root = output_dir / "quarterly"
    quarterly_root.mkdir(parents=True, exist_ok=True)
    quarterly_by_company: dict[str, list[Mapping[str, Any]]] = {}
    for row in report["quarterly_financial_facts"]:
        quarterly_by_company.setdefault(str(row["company_id"]), []).append(row)
    quarterly_index: dict[str, str] = {}
    for company_id, rows in sorted(quarterly_by_company.items()):
        filename = quote(company_id, safe="._-") + ".json"
        quarterly_index[company_id] = f"quarterly/{filename}"
        temporary = (quarterly_root / filename).with_suffix(".json.tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(quarterly_root / filename)
    for name, payload in {"manifest.json": {key: report[key] for key in ("schema_version", "version", "generated_at", "summary")}, "financial_facts.json": report["financial_facts"], "quarterly_index.json": {"schema_version": "quarterly-financial-index.v031v.4", "company_count": len(quarterly_index), "company_id_to_file": quarterly_index}, "diagnostics.json": report["diagnostics"]}.items():
        temporary = output_dir / f"{name}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_dir / name)
