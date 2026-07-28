from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


SUPPORTED_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}


class SECBusinessEvidenceError(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.suppressed += 1
        elif not self.suppressed and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.suppressed:
            self.suppressed -= 1
        elif not self.suppressed and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            self.parts.append(data)


def _plain_text(document: bytes) -> str:
    decoded = document.decode("utf-8", errors="replace")
    parser = _TextExtractor()
    try:
        parser.feed(decoded)
        value = "".join(parser.parts)
    except Exception:
        value = re.sub(r"<[^>]+>", " ", decoded)
    value = html.unescape(value).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _patterns(form: str) -> tuple[list[re.Pattern[str]], list[re.Pattern[str]]]:
    flags = re.IGNORECASE | re.MULTILINE
    if form.startswith("10-K"):
        starts = [
            re.compile(
                r"^\s*ITEMS?\s+1(?:[.\s:—|_-]+(?:AND|&)\s*2)?[.\s:—|_-]+BUSINESS(?:\s+AND\s+PROPERTIES)?\b.*$",
                flags,
            )
        ]
        ends = [re.compile(r"^\s*ITEM\s+1A[.\s:—|_-]+RISK\s+FACTORS\b.*$", flags)]
    else:
        starts = [re.compile(r"^\s*ITEM\s+4[.\s:—-]+INFORMATION\s+ON\s+THE\s+COMPANY\b.*$", flags)]
        ends = [
            re.compile(r"^\s*ITEM\s+4A[.\s:—|_-]+UNRESOLVED\s+STAFF\s+COMMENTS\b.*$", flags),
            re.compile(r"^\s*ITEM\s+5[.\s:—|_-]+OPERATING\s+AND\s+FINANCIAL\s+REVIEW\b.*$", flags),
        ]
    return starts, ends


def extract_business_section(document: bytes, *, form: str, minimum_characters: int = 500) -> dict[str, Any]:
    if form not in SUPPORTED_FORMS:
        return {"status": "unavailable", "reason_code": "UNSUPPORTED_FORM"}
    text = _plain_text(document)
    starts, ends = _patterns(form)
    candidates: list[tuple[int, int, str]] = []
    for start_pattern in starts:
        for start in start_pattern.finditer(text):
            possible_ends = [match for pattern in ends for match in pattern.finditer(text, start.end())]
            if not possible_ends:
                continue
            end = min(possible_ends, key=lambda match: match.start())
            section = text[start.start() : end.start()].strip()
            candidates.append((len(section), start.start(), section))
    if not candidates:
        return {"status": "unavailable", "reason_code": "BUSINESS_SECTION_BOUNDARY_NOT_FOUND"}
    length, offset, section = max(candidates)
    if length < minimum_characters:
        return {
            "status": "unavailable",
            "reason_code": "BUSINESS_SECTION_TOO_SHORT",
            "extracted_characters": length,
        }
    return {
        "status": "available",
        "section_type": "item_1_business" if form.startswith("10-K") else "item_4_company_information",
        "text": section,
        "text_sha256": hashlib.sha256(section.encode()).hexdigest(),
        "start_character": offset,
        "extracted_characters": length,
    }


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SECBusinessEvidenceError(f"cannot read {path}: {exc}") from exc


def _validate_user_agent(value: str) -> None:
    if not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("SEC user agent must include a valid contact email")
    value.encode("ascii")


def _download(url: str, user_agent: str) -> bytes:
    _validate_user_agent(user_agent)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _submission_text_url(row: Mapping[str, Any]) -> str | None:
    document_url = str(row.get("document_url") or "")
    accession = str(row.get("accession_number") or "")
    if not document_url or not accession:
        return None
    return f"{document_url.rsplit('/', 1)[0]}/{accession}.txt"


def _foreign_annual_report(submission: bytes, row: Mapping[str, Any]) -> tuple[str | None, bytes | None]:
    text = submission.decode("utf-8", errors="replace")
    candidates: list[tuple[int, str, bytes | None]] = []
    for block in re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", text, flags=re.IGNORECASE | re.DOTALL):
        type_match = re.search(r"<TYPE>\s*([^\r\n<]+)", block, flags=re.IGNORECASE)
        file_match = re.search(r"<FILENAME>\s*([^\r\n<]+)", block, flags=re.IGNORECASE)
        description_match = re.search(r"<DESCRIPTION>\s*([^\r\n<]+)", block, flags=re.IGNORECASE)
        if not type_match or not file_match:
            continue
        document_type = type_match.group(1).strip().upper()
        filename = file_match.group(1).strip()
        description = description_match.group(1).strip().lower() if description_match else ""
        if not document_type.startswith("EX-99") or not filename.lower().endswith((".htm", ".html")):
            continue
        embedded_match = re.search(r"<TEXT>(.*?)</TEXT>", block, flags=re.IGNORECASE | re.DOTALL)
        embedded = embedded_match.group(1).encode() if embedded_match else None
        extracted = extract_business_section(embedded, form=str(row.get("form") or "")) if embedded else {}
        score = int(extracted.get("extracted_characters") or 0)
        if "annual report" in description:
            score += 1_000_000
        candidates.append((score, filename, embedded))
    if not candidates:
        return None, None
    _, filename, embedded = max(candidates, key=lambda item: (item[0], len(item[2] or b""), item[1]))
    return f"{str(row['document_url']).rsplit('/', 1)[0]}/{filename}", embedded


def build_sec_business_evidence(
    root: Path,
    *,
    filing_manifest_path: str = "data/generated/canonical_company_evidence/filing_documents.json",
    cache_dir: str = "data/generated/provider_cache/sec/filing_documents",
    allow_live: bool = False,
    user_agent: str = "",
    limit: int | None = None,
    offset: int = 0,
    company_ids: Iterable[str] | None = None,
    write_cache: bool = False,
    request_delay_seconds: float = 0.11,
    now: datetime | None = None,
    fetcher: Callable[[str, str], bytes] = _download,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if offset < 0:
        raise ValueError("offset cannot be negative")
    rows = _load(root / filing_manifest_path)
    if not isinstance(rows, list):
        raise SECBusinessEvidenceError("filing document manifest must be an array")
    source_filing_count = len(rows)
    selected = set(company_ids or [])
    if selected:
        rows = [row for row in rows if row.get("company_id") in selected]
    rows = sorted(rows, key=lambda row: str(row.get("company_id") or ""))
    rows = rows[offset:]
    if limit is not None:
        rows = rows[:limit]
    cache_root = root / cache_dir
    evidence: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    downloaded = 0
    for row in rows:
        accession = str(row.get("accession_number") or "")
        cache_path = cache_root / f"{accession.replace('-', '')}.html"
        document: bytes | None = None
        acquisition_mode = ""
        effective_document_url = str(row.get("document_url") or "")
        try:
            if cache_path.is_file():
                document = cache_path.read_bytes()
                acquisition_mode = "cache"
            elif allow_live and row.get("document_url"):
                document = fetcher(str(row["document_url"]), user_agent)
                acquisition_mode = "sec_live"
                downloaded += 1
                if write_cache:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_bytes(document)
                if request_delay_seconds:
                    time.sleep(request_delay_seconds)
            if document is None:
                result = {"status": "unavailable", "reason_code": "FILING_DOCUMENT_NOT_CACHED"}
            else:
                result = extract_business_section(document, form=str(row.get("form") or ""))
            if result["status"] != "available" and str(row.get("form") or "").startswith("40-F"):
                package_cache = cache_root / f"{accession.replace('-', '')}.submission.txt"
                exhibit_cache = cache_root / f"{accession.replace('-', '')}.annual-report.html"
                package = package_cache.read_bytes() if package_cache.is_file() else None
                package_url = _submission_text_url(row)
                if package is None and allow_live and package_url:
                    package = fetcher(package_url, user_agent)
                    downloaded += 1
                    if write_cache:
                        package_cache.parent.mkdir(parents=True, exist_ok=True)
                        package_cache.write_bytes(package)
                    if request_delay_seconds:
                        time.sleep(request_delay_seconds)
                exhibit_url, embedded_exhibit = _foreign_annual_report(package, row) if package else (None, None)
                exhibit_from_cache = embedded_exhibit is None and exhibit_cache.is_file()
                exhibit = embedded_exhibit or (exhibit_cache.read_bytes() if exhibit_from_cache else None)
                if exhibit is None and allow_live and exhibit_url:
                    exhibit = fetcher(exhibit_url, user_agent)
                    downloaded += 1
                    if write_cache:
                        exhibit_cache.parent.mkdir(parents=True, exist_ok=True)
                        exhibit_cache.write_bytes(exhibit)
                    if request_delay_seconds:
                        time.sleep(request_delay_seconds)
                if exhibit is not None:
                    exhibit_result = extract_business_section(exhibit, form=str(row.get("form") or ""))
                    if exhibit_result["status"] == "available":
                        document = exhibit
                        result = exhibit_result
                        acquisition_mode = "submission_exhibit" if embedded_exhibit else "cache_exhibit" if exhibit_from_cache else "sec_live_exhibit"
                        effective_document_url = exhibit_url or effective_document_url
        except (OSError, urllib.error.URLError, ValueError) as exc:
            result = {"status": "unavailable", "reason_code": "FILING_DOCUMENT_FETCH_FAILED", "error_type": type(exc).__name__}
        status_counts[str(result["status"])] += 1
        if result["status"] != "available":
            diagnostics.append({"company_id": row.get("company_id"), "filing_document_id": row.get("filing_document_id"), **result})
            continue
        document_hash = hashlib.sha256(document or b"").hexdigest()
        provenance_id = f"provenance:SEC-FILING-{accession}-{document_hash[:16]}"
        evidence.append({
            "business_evidence_id": f"business-evidence:SEC-{accession}",
            "company_id": row["company_id"],
            "evidence_type": "regulator_filing_business_section",
            "form": row["form"],
            "accession_number": accession,
            "filing_date": row.get("filing_date"),
            "document_url": effective_document_url,
            "document_sha256": document_hash,
            "retrieved_at": current.isoformat(),
            "acquisition_mode": acquisition_mode,
            "provenance_id": provenance_id,
            **{key: result[key] for key in ("section_type", "text", "text_sha256", "start_character", "extracted_characters")},
        })
    return {
        "schema_version": "sec-business-evidence.v031.2b",
        "version": "V031.2B",
        "generated_at": current.isoformat(),
        "summary": {
            "source_filing_manifest_count": source_filing_count,
            "batch_offset": offset,
            "filings_requested": len(rows),
            "documents_downloaded": downloaded,
            "business_evidence_available": len(evidence),
            "business_evidence_unavailable": len(diagnostics),
            "availability_ratio": round(len(evidence) / len(rows), 6) if rows else 0.0,
            "status_counts": dict(sorted(status_counts.items())),
        },
        "business_evidence": evidence,
        "diagnostics": diagnostics,
    }


def write_sec_business_evidence(report: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, payload in {
        "manifest.json": {key: report[key] for key in ("schema_version", "version", "generated_at", "summary")},
        "business_evidence.json": report["business_evidence"],
        "diagnostics.json": report["diagnostics"],
    }.items():
        temporary = output_dir / f"{filename}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_dir / filename)
