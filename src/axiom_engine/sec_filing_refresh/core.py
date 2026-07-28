from __future__ import annotations

import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping


FINANCIAL_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _recent(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    recent = ((payload.get("filings") or {}).get("recent") or {})
    columns = {key: value for key, value in recent.items() if isinstance(value, list)} if isinstance(recent, Mapping) else {}
    count = min((len(values) for values in columns.values()), default=0)
    return [{key: values[index] for key, values in columns.items()} for index in range(count)]


def _is_financial_trigger(row: Mapping[str, Any]) -> bool:
    form = str(row.get("form") or "").upper()
    return form in FINANCIAL_FORMS or (form == "6-K" and str(row.get("isXBRL") or "0") == "1")


def _companyfacts_accessions(payload: Mapping[str, Any]) -> set[str]:
    output: set[str] = set()
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        return output
    for namespace in facts.values():
        concepts = namespace if isinstance(namespace, Mapping) else {}
        for concept in concepts.values():
            units = concept.get("units") if isinstance(concept, Mapping) else {}
            if not isinstance(units, Mapping):
                continue
            for observations in units.values():
                if not isinstance(observations, list):
                    continue
                output.update(str(row.get("accn")) for row in observations if isinstance(row, Mapping) and row.get("accn"))
    return output


def build_sec_filing_refresh_plan(
    root: Path,
    *,
    companies_path: str = "data/universe/companies.json",
    submissions_cache_dir: str = "data/generated/provider_cache/sec/submissions",
    financial_facts_path: str = "data/generated/canonical_financial_population/financial_facts.json",
    companyfacts_cache_dir: str = "data/generated/provider_cache/sec/companyfacts",
    companyfacts_bulk_zip: str = "data/onboarding/sec/companyfacts.zip",
    safety_refresh_days: int = 90,
    as_of: date | None = None,
) -> dict[str, Any]:
    if safety_refresh_days < 1:
        raise ValueError("safety_refresh_days must be positive")
    current = as_of or datetime.now(timezone.utc).date()
    companies = _load(root / companies_path)
    facts = _load(root / financial_facts_path)
    known_accessions: dict[str, set[str]] = {}
    for fact in facts:
        company_id = str(fact.get("company_id") or "")
        accession = str(fact.get("accession_number") or "")
        if company_id and accession:
            known_accessions.setdefault(company_id, set()).add(accession)
    worklist: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    cache_root = root / submissions_cache_dir
    companyfacts_root = root / companyfacts_cache_dir
    bulk_path = root / companyfacts_bulk_zip
    bulk = zipfile.ZipFile(bulk_path) if bulk_path.is_file() else None
    bulk_names = set(bulk.namelist()) if bulk else set()
    for company in companies:
        company_id = str(company.get("company_id") or "")
        cik = str((company.get("metadata") or {}).get("cik") or "").zfill(10)
        cache_path = cache_root / f"CIK{cik}.json"
        if not cik.strip("0") or not cache_path.is_file():
            diagnostics.append({"company_id": company_id, "reason_code": "SUBMISSIONS_CACHE_UNAVAILABLE"})
            continue
        payload = _load(cache_path)
        filings = sorted(
            (row for row in _recent(payload) if _is_financial_trigger(row)),
            key=lambda row: (str(row.get("filingDate") or ""), str(row.get("accessionNumber") or "")),
            reverse=True,
        )
        latest = filings[0] if filings else None
        latest_accession = str((latest or {}).get("accessionNumber") or "")
        companyfacts_path = companyfacts_root / f"CIK{cik}.json"
        if companyfacts_path.is_file():
            raw_payload = _load(companyfacts_path)
        elif bulk is not None and f"CIK{cik}.json" in bulk_names:
            raw_payload = json.loads(bulk.read(f"CIK{cik}.json"))
        else:
            raw_payload = {}
        raw_accessions = _companyfacts_accessions(raw_payload)
        consumed_accessions = known_accessions.get(company_id, set()) | raw_accessions
        reasons: list[str] = []
        if latest_accession and latest_accession not in consumed_accessions:
            reasons.append("NEW_FINANCIAL_FILING_ACCESSION")
        cache_age_days = (current - datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc).date()).days
        if cache_age_days >= safety_refresh_days:
            reasons.append("SAFETY_TTL_EXPIRED")
        if reasons:
            worklist.append({
                "company_id": company_id,
                "cik": cik,
                "reason_codes": reasons,
                "latest_financial_filing": {"form": (latest or {}).get("form"), "filing_date": (latest or {}).get("filingDate"), "report_date": (latest or {}).get("reportDate"), "accession_number": latest_accession or None},
                "known_financial_accession_count": len(consumed_accessions),
                "submissions_cache_age_days": cache_age_days,
            })
    if bulk is not None:
        bulk.close()
    return {
        "schema_version": "sec-filing-refresh-plan.v031c.1.1",
        "version": "V031C.1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": current.isoformat(),
        "policy": {"submissions_metadata_poll": "daily", "financial_refresh_trigger": "new_financial_filing_accession", "safety_refresh_days": safety_refresh_days, "yahoo_earnings_calendar_role": "advisory_only"},
        "summary": {"registry_company_count": len(companies), "refresh_company_count": len(worklist), "missing_submissions_cache_count": len(diagnostics), "new_filing_count": sum("NEW_FINANCIAL_FILING_ACCESSION" in row["reason_codes"] for row in worklist), "safety_ttl_count": sum("SAFETY_TTL_EXPIRED" in row["reason_codes"] for row in worklist)},
        "worklist": worklist,
        "diagnostics": diagnostics,
    }


def write_sec_filing_refresh_plan(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
