from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


def _clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _paragraphs(text: str) -> list[str]:
    """
    Preserve filing wording instead of converting the company into
    ontology / research-signal tokens.

    Page markers and Table of Contents noise are removed, but the
    underlying SEC disclosure remains verbatim.
    """
    result: list[str] = []

    for raw in re.split(r"\n+", text):
        paragraph = _clean_text(raw)

        if not paragraph:
            continue

        if paragraph.lower() == "table of contents":
            continue

        if re.fullmatch(r"\d+", paragraph):
            continue

        result.append(paragraph)

    return result


def _latest_business_evidence(
    company_id: str,
    evidence_rows: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    candidates = [
        row
        for row in evidence_rows
        if str(row.get("company_id") or "") == company_id
        and str(row.get("evidence_type") or "")
        == "regulator_filing_business_section"
        and _clean_text(row.get("text"))
    ]

    if not candidates:
        return None

    candidates.sort(
        key=lambda row: (
            str(row.get("filing_date") or ""),
            str(row.get("accession_number") or ""),
        ),
        reverse=True,
    )

    return candidates[0]


def build_company_profile_v2(
    company_id: str,
    evidence_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Evidence-first company profile.

    Important:
    - This layer does NOT consume company_signals.
    - This layer does NOT consume ontology labels.
    - This layer does NOT infer a theme / sector / cluster.
    - Filing text is preserved so downstream company understanding
      cannot lose information simply because a concept is absent from
      the current ontology.

    Structured semantic extraction will be layered on top of this
    evidence substrate in the next stage.
    """
    source = _latest_business_evidence(company_id, evidence_rows)

    if source is None:
        return {
            "schema_version": "axiom-company-profile.v2",
            "status": "unavailable",
            "source": None,
            "business_text": None,
            "paragraphs": [],
        }

    text = _clean_text(source.get("text"))
    paragraphs = _paragraphs(text)

    return {
        "schema_version": "axiom-company-profile.v2",
        "status": "available",
        "source": {
            "business_evidence_id": source.get("business_evidence_id"),
            "source_type": "sec_filing",
            "form": source.get("form"),
            "accession_number": source.get("accession_number"),
            "filing_date": source.get("filing_date"),
            "section_type": source.get("section_type"),
            "document_url": source.get("document_url"),
            "document_sha256": source.get("document_sha256"),
            "provenance_id": source.get("provenance_id"),
            "native_word_count": source.get("native_word_count"),
        },
        "business_text": text,
        "paragraphs": [
            {
                "paragraph_id": f"p{position:03d}",
                "text": paragraph,
            }
            for position, paragraph in enumerate(paragraphs, start=1)
        ],
    }