from __future__ import annotations

import gzip
import json
import re
import time
import urllib.request
import zlib
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from axiom_engine.financial_data import import_financial_data

SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}

# SEC registrant migrations where the current ticker registry CIK is not the historical
# operating-company CIK that owns the long financial Companyfacts history.
FINANCIAL_FACTS_CIK_ALIASES = {
    "0002115436": "0000034088",  # XOM: ExxonMobil Holdings -> Exxon Mobil Corp historical facts
}

METRICS: dict[str, dict[str, Any]] = {
    "revenue": {
        "statement": "income_statement",
        "period_type": "duration",
        "unit": "currency",
        "tags": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
        ],
    },
    "net_income": {
        "statement": "income_statement",
        "period_type": "duration",
        "unit": "currency",
        "tags": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    },
    "operating_cash_flow": {
        "statement": "cash_flow",
        "period_type": "duration",
        "unit": "currency",
        "tags": [
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ],
    },
    "capital_expenditures": {
        "statement": "cash_flow",
        "period_type": "duration",
        "unit": "currency",
        "tags": [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsForAdditionsToPropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
            "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets",
            "PaymentsToAcquirePropertyPlantAndEquipmentAndOtherProductiveAssets",
            "PropertyPlantAndEquipmentAdditions",
            "CapitalExpendituresIncurredButNotYetPaid",
            "PaymentsToAcquireOtherPropertyPlantAndEquipment",
            "PaymentsToAcquireBuildings",
            "PaymentsToAcquireLand",
            "PaymentsToAcquireMachineryAndEquipment",
            "PaymentsToAcquireFurnitureAndFixtures",
            "PaymentsToAcquireComputerEquipment",
        ],
    },
    "cash_and_cash_equivalents": {
        "statement": "balance_sheet",
        "period_type": "instant",
        "unit": "currency",
        "tags": [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
            "Cash",
        ],
    },
    "total_debt": {
        "statement": "balance_sheet",
        "period_type": "instant",
        "unit": "currency",
        "tags": [
            "DebtLongtermAndShorttermCombinedAmount",
            "LongTermDebtAndFinanceLeaseObligations",
            "LongTermDebtAndCapitalLeaseObligations",
            "LongTermDebt",
            "DebtAndFinanceLeaseObligations",
            "DebtCurrentAndNoncurrent",
            "FinanceLeaseLiability",
            "CapitalLeaseObligations",
            "ConvertibleDebt",
            "ConvertibleNotesPayable",
            "NotesPayable",
        ],
    },
    "diluted_shares_outstanding": {
        "statement": "income_statement",
        "period_type": "duration",
        "unit": "shares",
        "tags": [
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        ],
    },
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SecFinancialBuildReport(StrictModel):
    companies_requested: int
    companies_downloaded: int
    companies_with_facts: int
    facts_built: int
    metric_company_coverage: dict[str, int]
    failed_companies: dict[str, str]
    companies_without_facts: list[str]
    missing_metrics_by_company: dict[str, list[str]]
    tag_usage_by_metric: dict[str, dict[str, int]]
    source_file: str | None = None
    financial_directory: str | None = None
    diagnostics_file: str | None = None
    dry_run: bool
    acceptance_passed: bool


def _validate_ua(value: str) -> None:
    if not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("SEC user agent must include a valid contact email")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("SEC user agent must contain ASCII characters only") from exc


def _decode(body: bytes, encoding: str | None) -> bytes:
    normalized = (encoding or "").lower()
    if normalized == "gzip" or body.startswith(b"\x1f\x8b"):
        return gzip.decompress(body)
    if normalized == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    return body


def _get_json(url: str, user_agent: str, timeout: int = 45) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        decoded = _decode(response.read(), response.headers.get("Content-Encoding"))
        return json.loads(decoded.decode("utf-8"))


def _load_registry(root: str | Path) -> list[dict[str, Any]]:
    rows = json.loads((Path(root) / "companies.json").read_text(encoding="utf-8"))
    output: list[dict[str, Any]] = []
    for row in rows:
        cik = str(row.get("metadata", {}).get("cik", "")).zfill(10)
        if cik.strip("0"):
            output.append({"company_id": row["company_id"], "cik": cik})
    return sorted(output, key=lambda item: item["company_id"])


def _candidate_units(fact: dict[str, Any], unit_kind: str) -> list[dict[str, Any]]:
    units = fact.get("units", {})
    preferred = ("USD", "usd") if unit_kind == "currency" else ("shares", "SHARES")
    for key in preferred:
        if key in units:
            return units[key]
    return []


def _is_annual_duration(row: dict[str, Any]) -> bool:
    start, end = row.get("start"), row.get("end")
    if not start or not end:
        return False
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return False
    return 300 <= days <= 430


def _annual_rows(fact: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _candidate_units(fact, spec["unit"]):
        if row.get("form") not in ANNUAL_FORMS or not row.get("end") or row.get("val") is None:
            continue
        if spec["period_type"] == "duration":
            if not row.get("start"):
                continue
            # Some valid Companyfacts omit fy/fp. Keep annual-length rows instead of dropping the company.
            if row.get("fp") != "FY" and row.get("fy") is None and not _is_annual_duration(row):
                continue
        rows.append(row)
    return rows


def _row_sort_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("filed", "")),
        str(row.get("end", "")),
        str(row.get("accn", "")),
        str(row.get("frame", "")),
    )


def _latest_annual(payload: dict[str, Any], spec: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    us_gaap = payload.get("facts", {}).get("us-gaap", {})
    for tag in spec["tags"]:
        fact = us_gaap.get(tag)
        if not fact:
            continue
        rows = _annual_rows(fact, spec)
        if rows:
            rows.sort(key=_row_sort_key, reverse=True)
            return tag, rows[0]
    return None


def _latest_instant_for_tag(payload: dict[str, Any], tag: str) -> dict[str, Any] | None:
    fact = payload.get("facts", {}).get("us-gaap", {}).get(tag)
    if not fact:
        return None
    spec = {"unit": "currency", "period_type": "instant"}
    rows = _annual_rows(fact, spec)
    if not rows:
        return None
    rows.sort(key=_row_sort_key, reverse=True)
    return rows[0]


def _sum_same_period(payload: dict[str, Any], combinations: list[tuple[str, ...]]) -> tuple[str, dict[str, Any]] | None:
    for tags in combinations:
        parts = [(tag, _latest_instant_for_tag(payload, tag)) for tag in tags]
        if any(row is None for _, row in parts):
            continue
        ends = {row["end"] for _, row in parts if row is not None}
        if len(ends) != 1:
            continue
        rows = [row for _, row in parts if row is not None]
        result = dict(max(rows, key=_row_sort_key))
        result["val"] = sum((Decimal(str(row["val"])) for row in rows), Decimal("0"))
        result["_derived_tags"] = list(tags)
        return "+".join(tags), result
    return None


def _latest_common_period_pair(
    payload: dict[str, Any],
    current_tags: tuple[str, ...],
    noncurrent_tags: tuple[str, ...],
) -> tuple[str, dict[str, Any]] | None:
    current_rows = [(tag, _latest_instant_for_tag(payload, tag)) for tag in current_tags]
    noncurrent_rows = [(tag, _latest_instant_for_tag(payload, tag)) for tag in noncurrent_tags]
    candidates: list[tuple[tuple[str, str, str, str], str, dict[str, Any]]] = []
    for current_tag, current in current_rows:
        if current is None:
            continue
        for noncurrent_tag, noncurrent in noncurrent_rows:
            if noncurrent is None or current.get("end") != noncurrent.get("end"):
                continue
            result = dict(max((current, noncurrent), key=_row_sort_key))
            result["val"] = Decimal(str(current["val"])) + Decimal(str(noncurrent["val"]))
            result["_derived_tags"] = [current_tag, noncurrent_tag]
            tag = f"{current_tag}+{noncurrent_tag}"
            candidates.append((_row_sort_key(result), tag, result))
    if not candidates:
        return None
    _, tag, row = max(candidates, key=lambda item: item[0])
    return tag, row


def _noncurrent_debt_proxy(payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    # Explicitly marked proxy: preferable to inventing a zero current portion, while preserving
    # traceability for companies that disclose only a non-current consolidated debt concept.
    tags = (
        "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
        "LongTermDebtAndCapitalLeaseObligationsNoncurrent",
        "LongTermDebtNoncurrent",
        "DebtNoncurrent",
        "NotesPayableNoncurrent",
        "ConvertibleNotesPayableNoncurrent",
        "ConvertibleDebtNoncurrent",
        "FinanceLeaseLiabilityNoncurrent",
        "CapitalLeaseObligationsNoncurrent",
    )
    for tag in tags:
        row = _latest_instant_for_tag(payload, tag)
        if row is not None:
            result = dict(row)
            result["_derived_tags"] = [tag]
            result["_coverage_proxy"] = "noncurrent_debt_only"
            return f"{tag}[proxy]", result
    return None


def _debt(payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    # Direct consolidated totals are safest and therefore always preferred.
    direct = _latest_annual(payload, METRICS["total_debt"])
    if direct:
        return direct

    # Ordered from most comprehensive to more permissive combinations.
    combinations = [
        ("LongTermDebtAndFinanceLeaseObligationsCurrent", "LongTermDebtAndFinanceLeaseObligationsNoncurrent"),
        ("LongTermDebtAndCapitalLeaseObligationsCurrent", "LongTermDebtAndCapitalLeaseObligationsNoncurrent"),
        ("LongTermDebtCurrent", "LongTermDebtNoncurrent"),
        ("DebtCurrent", "DebtNoncurrent"),
        ("NotesPayableCurrent", "NotesPayableNoncurrent"),
        ("ConvertibleNotesPayableCurrent", "ConvertibleNotesPayableNoncurrent"),
        ("ConvertibleDebtCurrent", "ConvertibleDebtNoncurrent"),
        ("FinanceLeaseLiabilityCurrent", "FinanceLeaseLiabilityNoncurrent"),
        ("CapitalLeaseObligationsCurrent", "CapitalLeaseObligationsNoncurrent"),
        ("ShortTermBorrowings", "LongTermDebtCurrent", "LongTermDebtNoncurrent"),
        ("ShortTermDebtCurrent", "LongTermDebtNoncurrent"),
        ("CommercialPaper", "LongTermDebtCurrent", "LongTermDebtNoncurrent"),
    ]
    exact = _sum_same_period(payload, combinations)
    if exact:
        return exact

    adaptive = _latest_common_period_pair(
        payload,
        (
            "LongTermDebtAndFinanceLeaseObligationsCurrent",
            "LongTermDebtAndCapitalLeaseObligationsCurrent",
            "LongTermDebtCurrent",
            "DebtCurrent",
            "ShortTermBorrowings",
            "ShortTermDebtCurrent",
            "CommercialPaper",
            "NotesPayableCurrent",
            "ConvertibleNotesPayableCurrent",
            "ConvertibleDebtCurrent",
            "FinanceLeaseLiabilityCurrent",
            "CapitalLeaseObligationsCurrent",
        ),
        (
            "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
            "LongTermDebtAndCapitalLeaseObligationsNoncurrent",
            "LongTermDebtNoncurrent",
            "DebtNoncurrent",
            "NotesPayableNoncurrent",
            "ConvertibleNotesPayableNoncurrent",
            "ConvertibleDebtNoncurrent",
            "FinanceLeaseLiabilityNoncurrent",
            "CapitalLeaseObligationsNoncurrent",
        ),
    )
    return adaptive or _noncurrent_debt_proxy(payload)


def _fiscal_year(row: dict[str, Any]) -> int:
    fiscal_year = row.get("fy")
    if fiscal_year is not None:
        return int(fiscal_year)
    return int(str(row["end"])[:4])


def _acceptance(companies: int, with_facts: int, coverage: dict[str, int], failed: dict[str, str]) -> bool:
    return (
        companies == 100
        and with_facts == 100
        and coverage["revenue"] >= 90
        and coverage["net_income"] >= 95
        and coverage["operating_cash_flow"] >= 90
        and coverage["capital_expenditures"] >= 95
        and coverage["total_debt"] >= 95
        and coverage["diluted_shares_outstanding"] >= 90
        and not failed
    )


def build_real_100_financials(
    *,
    user_agent: str,
    registry_dir: str = "data/company_registry",
    source_output: str = "data/onboarding/generated/real_100_sec_financial_source.json",
    financial_dir: str = "data/financial_data",
    cache_dir: str = "data/onboarding/sec_companyfacts",
    diagnostics_output: str = "data/onboarding/generated/v023_financial_diagnostics.json",
    sleep_seconds: float = 0.12,
    write: bool = False,
) -> SecFinancialBuildReport:
    _validate_ua(user_agent)
    companies = _load_registry(registry_dir)
    now = datetime.now(timezone.utc).isoformat()
    cache = Path(cache_dir)
    facts: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    failed: dict[str, str] = {}
    coverage = {metric: 0 for metric in METRICS}
    company_metrics: dict[str, list[str]] = {}
    tag_usage: dict[str, Counter[str]] = {metric: Counter() for metric in METRICS}
    downloaded = 0

    for company in companies:
        company_id = company["company_id"]
        company_metrics[company_id] = []
        try:
            requested_cik = company["cik"]
            facts_cik = FINANCIAL_FACTS_CIK_ALIASES.get(requested_cik, requested_cik)
            cache_path = cache / f"CIK{facts_cik}.json"
            if cache_path.exists():
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            else:
                payload = _get_json(SEC_COMPANYFACTS_URL.format(cik=facts_cik), user_agent)
                downloaded += 1
                if write:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                if sleep_seconds:
                    time.sleep(sleep_seconds)

            for metric, spec in METRICS.items():
                found = _debt(payload) if metric == "total_debt" else _latest_annual(payload, spec)
                if not found:
                    continue
                tag, row = found
                provenance_id = (
                    f"provenance:SEC-COMPANYFACTS-{facts_cik}-"
                    f"{row.get('accn', 'NA')}-{metric}"
                )
                derived_tags = row.get("_derived_tags")
                provenance.append(
                    {
                        "provenance_id": provenance_id,
                        "provider_id": "provider:SEC",
                        "source_type": "regulator_filing",
                        "source_name": "SEC Companyfacts",
                        "source_record_id": f"{facts_cik}:{tag}:{row.get('accn', 'NA')}",
                        "retrieved_at": now,
                        "source_url": SEC_COMPANYFACTS_URL.format(cik=facts_cik),
                        "filing_date": row.get("filed"),
                        "metadata": {"xbrl_tag": tag, "derived_from_components": derived_tags, "registry_cik": requested_cik, "financial_facts_cik": facts_cik, "cik_alias_applied": facts_cik != requested_cik, "coverage_proxy": row.get("_coverage_proxy")},
                    }
                )
                unit = spec["unit"]
                facts.append(
                    {
                        "financial_fact_id": f"financial_fact:{facts_cik}:{metric}:{row['end']}:FY",
                        "company_id": company_id,
                        "metric": metric,
                        "value": str(row["val"]),
                        "unit": unit,
                        "currency": "USD" if unit == "currency" else None,
                        "period_type": spec["period_type"],
                        "period_start": row.get("start"),
                        "period_end": row["end"],
                        "fiscal_year": _fiscal_year(row),
                        "fiscal_period": "FY",
                        "statement": spec["statement"],
                        "form_type": row.get("form"),
                        "accession_number": row.get("accn"),
                        "audited": True,
                        "provenance_ids": [provenance_id],
                        "metadata": {
                            "xbrl_tag": tag,
                            "frame": row.get("frame"),
                            "derived_from_components": derived_tags,
                            "registry_cik": requested_cik,
                            "financial_facts_cik": facts_cik,
                            "cik_alias_applied": facts_cik != requested_cik,
                            "coverage_proxy": row.get("_coverage_proxy"),
                        },
                    }
                )
                coverage[metric] += 1
                company_metrics[company_id].append(metric)
                tag_usage[metric][tag] += 1
        except Exception as exc:  # report individual company failures without discarding the cohort
            failed[company_id] = f"{type(exc).__name__}: {exc}"

    all_metrics = set(METRICS)
    missing_by_company = {
        company_id: sorted(all_metrics - set(metrics))
        for company_id, metrics in company_metrics.items()
        if set(metrics) != all_metrics
    }
    companies_without_facts = sorted(
        company_id for company_id, metrics in company_metrics.items() if not metrics
    )
    tag_usage_plain = {
        metric: dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))
        for metric, counter in tag_usage.items()
    }
    source = {
        "schema_version": "1.0.0",
        "provider_id": "provider:SEC",
        "provider_name": "U.S. Securities and Exchange Commission",
        "as_of_date": date.today().isoformat(),
        "provenance": provenance,
        "facts": facts,
    }
    diagnostics = {
        "schema_version": "1.0.0",
        "companies_requested": len(companies),
        "companies_without_facts": companies_without_facts,
        "missing_metrics_by_company": missing_by_company,
        "tag_usage_by_metric": tag_usage_plain,
        "failed_companies": failed,
    }
    acceptance_passed = _acceptance(len(companies), len(companies) - len(companies_without_facts), coverage, failed)

    if write:
        source_path = Path(source_output)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        diagnostics_path = Path(diagnostics_output)
        diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostics_path.write_text(
            json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        import_financial_data(
            source_path,
            output_dir=financial_dir,
            company_registry_dir=registry_dir,
            dry_run=False,
        )

    companies_with_facts = len(companies) - len(companies_without_facts)
    return SecFinancialBuildReport(
        companies_requested=len(companies),
        companies_downloaded=downloaded,
        companies_with_facts=companies_with_facts,
        facts_built=len(facts),
        metric_company_coverage=coverage,
        failed_companies=failed,
        companies_without_facts=companies_without_facts,
        missing_metrics_by_company=missing_by_company,
        tag_usage_by_metric=tag_usage_plain,
        source_file=source_output if write else None,
        financial_directory=financial_dir if write else None,
        diagnostics_file=diagnostics_output if write else None,
        dry_run=not write,
        acceptance_passed=acceptance_passed,
    )


def validate_real_100_financials(
    *,
    registry_dir: str = "data/company_registry",
    financial_dir: str = "data/financial_data",
) -> dict[str, Any]:
    companies = {
        row["company_id"]
        for row in json.loads((Path(registry_dir) / "companies.json").read_text(encoding="utf-8"))
    }
    facts = json.loads((Path(financial_dir) / "financial_facts.json").read_text(encoding="utf-8"))
    by_company: dict[str, int] = {}
    coverage = {metric: set() for metric in METRICS}
    company_metrics = {company_id: set() for company_id in companies}
    tag_usage: dict[str, Counter[str]] = {metric: Counter() for metric in METRICS}

    for fact in facts:
        company_id = fact["company_id"]
        metric = fact["metric"]
        if company_id not in companies:
            continue
        by_company[company_id] = by_company.get(company_id, 0) + 1
        if metric in coverage:
            coverage[metric].add(company_id)
            company_metrics[company_id].add(metric)
            tag = fact.get("metadata", {}).get("xbrl_tag")
            if tag:
                tag_usage[metric][tag] += 1

    companies_without_facts = sorted(companies - set(by_company))
    missing_by_company = {
        company_id: sorted(set(METRICS) - metrics)
        for company_id, metrics in company_metrics.items()
        if metrics != set(METRICS)
    }
    coverage_counts = {metric: len(company_ids) for metric, company_ids in coverage.items()}
    output = {
        "companies_requested": len(companies),
        "companies_with_facts": len(by_company),
        "facts_loaded": sum(by_company.values()),
        "metric_company_coverage": coverage_counts,
        "companies_without_facts": companies_without_facts,
        "missing_metrics_by_company": missing_by_company,
        "tag_usage_by_metric": {
            metric: dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))
            for metric, counter in tag_usage.items()
        },
    }
    output["acceptance_passed"] = _acceptance(len(companies), len(by_company), coverage_counts, {})
    return output
