from __future__ import annotations

import hashlib
import json
import re
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SEC_SUBMISSIONS_BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


class SECCompanyEvidenceError(RuntimeError):
    pass


def _validate_user_agent(value: str) -> None:
    if not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("SEC user agent must include a valid contact email")
    value.encode("ascii")


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SECCompanyEvidenceError(f"cannot read {path}: {exc}") from exc


def _registry(root: Path, companies_path: str) -> list[dict[str, str | None]]:
    rows = _load_json(root / companies_path)
    if not isinstance(rows, list):
        raise SECCompanyEvidenceError("company registry must be an array")
    output = []
    for row in rows:
        raw_cik = str((row.get("metadata") or {}).get("cik") or "")
        cik = raw_cik.zfill(10) if raw_cik.strip("0") else None
        output.append({"company_id": str(row["company_id"]), "cik": cik})
    return sorted(output, key=lambda row: row["company_id"])


def _bulk_payloads(path: Path | None, requested_ciks: set[str]) -> dict[str, Mapping[str, Any]]:
    if path is None:
        return {}
    if not path.is_file():
        raise SECCompanyEvidenceError(f"SEC submissions bulk archive not found: {path}")
    output: dict[str, Mapping[str, Any]] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                match = re.fullmatch(r"(?:submissions/)?CIK(\d{10})\.json", name)
                if not match:
                    continue
                if match.group(1) not in requested_ciks:
                    continue
                payload = json.loads(archive.read(name))
                if isinstance(payload, Mapping):
                    output[match.group(1)] = payload
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise SECCompanyEvidenceError(f"invalid SEC submissions bulk archive: {exc}") from exc
    return output


def _fetch(cik: str, user_agent: str) -> Mapping[str, Any]:
    _validate_user_agent(user_agent)
    request = urllib.request.Request(
        SEC_SUBMISSIONS_URL.format(cik=cik),
        headers={"User-Agent": user_agent, "Accept-Encoding": "identity"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise SECCompanyEvidenceError(f"SEC submissions payload for {cik} is not an object")
    return payload


def _recent_filings(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    recent = ((payload.get("filings") or {}).get("recent") or {})
    if not isinstance(recent, Mapping):
        return []
    columns = {key: value for key, value in recent.items() if isinstance(value, list)}
    count = min((len(values) for values in columns.values()), default=0)
    return [{key: values[index] for key, values in columns.items()} for index in range(count)]


def _filing_url(cik: str, accession: str, document: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}"


def build_sec_company_evidence(
    root: Path,
    *,
    companies_path: str = "data/universe/companies.json",
    cache_dir: str = "data/generated/provider_cache/sec/submissions",
    bulk_zip: Path | None = None,
    allow_live: bool = False,
    user_agent: str = "",
    now: datetime | None = None,
    write_cache: bool = False,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    companies = _registry(root, companies_path)
    cache_root = root / cache_dir
    bulk = _bulk_payloads(
        bulk_zip, {str(row["cik"]) for row in companies if row["cik"]}
    )
    classifications: list[dict[str, Any]] = []
    filing_documents: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    source_counts: Counter[str] = Counter()

    for company in companies:
        cik = company["cik"]
        if not cik:
            missing.append(
                {
                    "company_id": str(company["company_id"]),
                    "cik": "",
                    "reason_code": "REGISTRY_CIK_MISSING",
                }
            )
            continue
        cik = str(cik)
        cache_path = cache_root / f"CIK{cik}.json"
        payload: Mapping[str, Any] | None = None
        source_mode = ""
        if cache_path.is_file():
            loaded = _load_json(cache_path)
            payload = loaded if isinstance(loaded, Mapping) else None
            source_mode = "cache"
        elif cik in bulk:
            payload = bulk[cik]
            source_mode = "sec_bulk"
        elif allow_live:
            payload = _fetch(cik, user_agent)
            source_mode = "sec_live"
        if payload is None:
            missing.append({**company, "reason_code": "SEC_SUBMISSIONS_NOT_AVAILABLE"})
            continue
        if write_cache and not cache_path.is_file():
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        source_counts[source_mode] += 1
        digest = hashlib.sha256(_json_bytes(payload)).hexdigest()
        provenance_id = f"provenance:SEC-SUBMISSIONS-{cik}-{digest[:16]}"
        provenance.append({
            "provenance_id": provenance_id,
            "source_type": "regulator",
            "source_name": "SEC EDGAR Submissions",
            "source_record_id": f"CIK{cik}",
            "retrieved_at": current.isoformat(),
            "source_url": SEC_SUBMISSIONS_URL.format(cik=cik),
            "content_sha256": digest,
            "acquisition_mode": source_mode,
        })
        sic = str(payload.get("sic") or "").strip()
        sic_description = str(payload.get("sicDescription") or "").strip()
        if sic:
            classifications.append({
                "classification_id": f"classification:SEC-SIC-{cik}-{sic}",
                "company_id": company["company_id"],
                "classification_scheme": "SEC_SIC",
                "classification_code": sic,
                "classification_label": sic_description or None,
                "authority": "U.S. Securities and Exchange Commission",
                "observed_at": current.isoformat(),
                "provenance_ids": [provenance_id],
            })
        annual = [row for row in _recent_filings(payload) if row.get("form") in ANNUAL_FORMS]
        annual.sort(
            key=lambda row: (
                str(row.get("reportDate") or ""),
                not str(row.get("form") or "").endswith("/A"),
                str(row.get("filingDate") or ""),
                str(row.get("accessionNumber") or ""),
            ),
            reverse=True,
        )
        if annual:
            row = annual[0]
            accession = str(row.get("accessionNumber") or "")
            document = str(row.get("primaryDocument") or "")
            filing_documents.append({
                "filing_document_id": f"filing-document:SEC-{cik}-{accession}",
                "company_id": company["company_id"],
                "cik": cik,
                "form": row.get("form"),
                "accession_number": accession,
                "filing_date": row.get("filingDate"),
                "report_date": row.get("reportDate"),
                "primary_document": document,
                "document_url": _filing_url(cik, accession, document) if accession and document else None,
                "extraction_status": "not_started",
                "provenance_ids": [provenance_id],
            })

    company_count = len(companies)
    submissions_count = sum(source_counts.values())
    return {
        "schema_version": "sec-company-evidence.v031.2a",
        "version": "V031.2A",
        "generated_at": current.isoformat(),
        "summary": {
            "registry_company_count": company_count,
            "submissions_available_count": submissions_count,
            "sic_classification_count": len(classifications),
            "annual_filing_manifest_count": len(filing_documents),
            "missing_submissions_count": len(missing),
            "submissions_coverage_ratio": round(submissions_count / company_count, 6) if company_count else 0.0,
            "sic_coverage_ratio": round(len(classifications) / company_count, 6) if company_count else 0.0,
            "annual_filing_coverage_ratio": round(len(filing_documents) / company_count, 6) if company_count else 0.0,
            "source_mode_counts": dict(sorted(source_counts.items())),
        },
        "official_classifications": classifications,
        "filing_documents": filing_documents,
        "provenance": provenance,
        "coverage_audit": {"missing_companies": missing},
    }


def write_sec_company_evidence(report: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "manifest.json": {key: report[key] for key in ("schema_version", "version", "generated_at", "summary")},
        "official_classifications.json": report["official_classifications"],
        "filing_documents.json": report["filing_documents"],
        "provenance.json": report["provenance"],
        "coverage_audit.json": report["coverage_audit"],
    }
    for filename, payload in outputs.items():
        temporary = (output_dir / filename).with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_dir / filename)


def download_submissions_bulk(*, target: Path, user_agent: str) -> None:
    _validate_user_agent(user_agent)
    request = urllib.request.Request(SEC_SUBMISSIONS_BULK_URL, headers={"User-Agent": user_agent})
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with urllib.request.urlopen(request, timeout=180) as response:
        temporary.write_bytes(response.read())
    if not zipfile.is_zipfile(temporary):
        temporary.unlink(missing_ok=True)
        raise SECCompanyEvidenceError("downloaded SEC submissions bulk file is not a ZIP archive")
    temporary.replace(target)
