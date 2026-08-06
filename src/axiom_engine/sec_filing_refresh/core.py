from __future__ import annotations

import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.business_evidence_store import load_business_evidence


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
    submissions_bulk_zip: str | None = None,
    financial_facts_path: str = "data/generated/canonical_financial_population/financial_facts.json",
    quarterly_index_path: str = "data/generated/canonical_financial_population/quarterly_index.json",
    companyfacts_cache_dir: str = "data/generated/provider_cache/sec/companyfacts",
    companyfacts_bulk_zip: str = "data/onboarding/sec/companyfacts.zip",
    safety_refresh_days: int = 90,
    accession_ledger_path: str = "data/generated/sec_filing_refresh/accession_ledger.json",
    business_evidence_path: str = "data/generated/canonical_business_evidence/business_evidence.json",
    as_of: date | None = None,
) -> dict[str, Any]:
    if safety_refresh_days < 1:
        raise ValueError("safety_refresh_days must be positive")
    current = as_of or datetime.now(timezone.utc).date()
    companies = _load(root / companies_path)
    facts = _load(root / financial_facts_path)
    ledger_file = root / accession_ledger_path
    ledger = _load(ledger_file) if ledger_file.is_file() else {"processed_accessions": []}
    ledger_by_accession = {
        str(row.get("accession_number") or ""): row
        for row in ledger.get("processed_accessions") or []
        if row.get("accession_number")
    }
    processed_accessions = {
        accession
        for accession, row in ledger_by_accession.items()
        if row.get("financial_processed_at") or row.get("processed_at")
    }
    business_evidence_file = root / business_evidence_path
    business_evidence = load_business_evidence(business_evidence_file)
    evidence_accessions = {str(row.get("accession_number") or "") for row in business_evidence}
    annual_forms = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
    known_accessions: dict[str, set[str]] = {}
    for fact in facts:
        company_id = str(fact.get("company_id") or "")
        accession = str(fact.get("accession_number") or "")
        if company_id and accession:
            known_accessions.setdefault(company_id, set()).add(accession)
    quarterly_index_file = root / quarterly_index_path
    if quarterly_index_file.is_file():
        quarterly_index = _load(quarterly_index_file).get("company_id_to_file") or {}
        for company_id, filename in quarterly_index.items():
            quarterly_file = quarterly_index_file.parent / str(filename)
            if not quarterly_file.is_file():
                continue
            for fact in _load(quarterly_file):
                accession = str(fact.get("accession_number") or "")
                if accession:
                    known_accessions.setdefault(str(company_id), set()).add(accession)
    worklist: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    cache_root = root / submissions_cache_dir
    submissions_bulk_path = root / submissions_bulk_zip if submissions_bulk_zip else None
    submissions_bulk = (
        zipfile.ZipFile(submissions_bulk_path)
        if submissions_bulk_path and submissions_bulk_path.is_file()
        else None
    )
    submissions_bulk_names = set(submissions_bulk.namelist()) if submissions_bulk else set()
    companyfacts_root = root / companyfacts_cache_dir
    bulk_path = root / companyfacts_bulk_zip
    bulk = zipfile.ZipFile(bulk_path) if bulk_path.is_file() else None
    bulk_names = set(bulk.namelist()) if bulk else set()
    for company in companies:
        company_id = str(company.get("company_id") or "")
        cik = str((company.get("metadata") or {}).get("cik") or "").zfill(10)
        cache_path = cache_root / f"CIK{cik}.json"
        bulk_name = f"CIK{cik}.json"
        if not cik.strip("0") or (not cache_path.is_file() and bulk_name not in submissions_bulk_names):
            diagnostics.append({"company_id": company_id, "reason_code": "SUBMISSIONS_CACHE_UNAVAILABLE"})
            continue
        payload = (
            _load(cache_path)
            if cache_path.is_file()
            else json.loads(submissions_bulk.read(bulk_name))
        )
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
        consumed_accessions = known_accessions.get(company_id, set()) | raw_accessions | processed_accessions
        reasons: list[str] = []
        pending_filings = []
        for row in filings[:1]:
            accession = str(row.get("accessionNumber") or "")
            if not accession:
                continue
            form = str(row.get("form") or "").upper()
            ledger_row = ledger_by_accession.get(accession)
            # Existing canonical facts establish the one-time baseline. Evidence
            # retries are permitted only for accessions first observed by this
            # ledger, never for the entire pre-ledger annual filing history.
            requires_financial = accession not in consumed_accessions
            requires_evidence = bool(
                form in annual_forms
                and ledger_row is not None
                and not ledger_row.get("business_evidence_processed_at")
                and accession not in evidence_accessions
            )
            if requires_financial and form in annual_forms:
                requires_evidence = accession not in evidence_accessions
            if requires_financial or requires_evidence:
                pending_filings.append({
                    "form": form,
                    "filing_date": row.get("filingDate"),
                    "report_date": row.get("reportDate"),
                    "accession_number": accession,
                    "requires_financial_refresh": requires_financial,
                    "requires_business_evidence_refresh": requires_evidence,
                })
        if any(row["requires_financial_refresh"] for row in pending_filings):
            reasons.append("NEW_FINANCIAL_FILING_ACCESSION")
        if any(row["requires_business_evidence_refresh"] for row in pending_filings):
            reasons.append("ANNUAL_BUSINESS_EVIDENCE_PENDING")
        cache_age_days = (
            (current - datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc).date()).days
            if cache_path.is_file()
            else 0
        )
        if cache_age_days >= safety_refresh_days:
            reasons.append("SAFETY_TTL_EXPIRED")
        if reasons:
            worklist.append({
                "company_id": company_id,
                "cik": cik,
                "reason_codes": reasons,
                "latest_financial_filing": {"form": (latest or {}).get("form"), "filing_date": (latest or {}).get("filingDate"), "report_date": (latest or {}).get("reportDate"), "accession_number": latest_accession or None},
                "pending_filings": pending_filings,
                "requires_financial_refresh": any(
                    row["requires_financial_refresh"] for row in pending_filings
                ) or "SAFETY_TTL_EXPIRED" in reasons,
                "requires_business_evidence_refresh": any(
                    row["requires_business_evidence_refresh"]
                    for row in pending_filings
                ),
                "known_financial_accession_count": len(consumed_accessions),
                "submissions_cache_age_days": cache_age_days,
            })
    if bulk is not None:
        bulk.close()
    if submissions_bulk is not None:
        submissions_bulk.close()
    return {
        "schema_version": "sec-filing-refresh-plan.v031c.1.1",
        "version": "V031C.1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": current.isoformat(),
        "policy": {"submissions_metadata_poll": "daily", "financial_refresh_trigger": "latest_unprocessed_financial_filing_accession", "accession_ledger_path": accession_ledger_path, "annual_business_evidence_refresh": True, "historical_accession_replay": False, "safety_refresh_days": safety_refresh_days, "yahoo_earnings_calendar_role": "advisory_only"},
        "summary": {"registry_company_count": len(companies), "refresh_company_count": len(worklist), "financial_refresh_company_count": sum(bool(row.get("requires_financial_refresh")) for row in worklist), "missing_submissions_cache_count": len(diagnostics), "new_filing_count": sum(sum(bool(filing.get("requires_financial_refresh")) for filing in row.get("pending_filings") or []) for row in worklist), "annual_evidence_refresh_company_count": sum(bool(row.get("requires_business_evidence_refresh")) for row in worklist), "safety_ttl_count": sum("SAFETY_TTL_EXPIRED" in row["reason_codes"] for row in worklist)},
        "worklist": worklist,
        "diagnostics": diagnostics,
    }


def write_sec_filing_refresh_plan(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
