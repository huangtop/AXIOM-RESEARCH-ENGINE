from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ThemeSectorInferenceError(RuntimeError):
    pass


class ThemeSectorInferenceNotFound(ThemeSectorInferenceError):
    pass


def _load(path: Path, default: Any = None) -> Any:
    if not path.is_file() and default is not None:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThemeSectorInferenceError(f"cannot read {path}: {exc}") from exc


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("-", " ").replace("/", " ").split())


def _matches(text: str, terms: list[str]) -> list[str]:
    return sorted({term for term in terms if _normalise(term) in text})


def _score(evidence: list[Mapping[str, Any]]) -> float:
    if not evidence:
        return 0.0
    remaining = 1.0
    for item in evidence:
        remaining *= 1.0 - float(item["weight"])
    return round(min(0.99, 1.0 - remaining), 4)


def _evidence(
    *,
    kind: str,
    source_record_ids: list[str],
    matched_terms: list[str],
    weight: float,
) -> dict[str, Any]:
    return {
        "evidence_type": kind,
        "source_record_ids": source_record_ids,
        "matched_terms": matched_terms,
        "weight": weight,
    }


def build_theme_sector_inference(
    root: Path,
    *,
    policy_path: str = "config/theme_sector_inference.v031.1.json",
    companies_path: str = "data/universe/companies.json",
    securities_path: str = "data/universe/securities.json",
    descriptions_path: str = "data/company_registry/business_descriptions.json",
    classifications_path: str = "data/company_registry/official_classifications.json",
    provenance_path: str = "data/company_registry/provenance.json",
    evidence_path: str = "data/canonical/evidence.json",
    exposures_path: str = "data/industry/industry_exposures.json",
    edges_path: str = "data/industry/industry_edges.json",
) -> dict[str, Any]:
    policy = _load(root / policy_path)
    companies = _load(root / companies_path)
    securities = _load(root / securities_path)
    descriptions = _load(root / descriptions_path, [])
    classifications = _load(root / classifications_path, [])
    provenance = _load(root / provenance_path, [])
    canonical_evidence = _load(root / evidence_path, [])
    exposures = _load(root / exposures_path, [])
    edges = _load(root / edges_path, [])
    if policy.get("schema_version") != "theme-sector-inference-policy.v031.1":
        raise ThemeSectorInferenceError("unsupported inference policy")
    if not all(
        isinstance(rows, list)
        for rows in (
            companies,
            securities,
            descriptions,
            classifications,
            provenance,
            canonical_evidence,
            exposures,
            edges,
        )
    ):
        raise ThemeSectorInferenceError("inference inputs must be arrays")

    valid_provenance_ids = {
        str(row["provenance_id"]) for row in provenance if row.get("provenance_id")
    }
    approved_evidence_ids = {
        str(row["evidence_id"])
        for row in canonical_evidence
        if row.get("evidence_id") and row.get("review_status") == "approved"
    }

    primary_ticker: dict[str, str] = {}
    for security in securities:
        company_id = str(security.get("company_id") or "")
        if security.get("primary_listing") is True or company_id not in primary_ticker:
            primary_ticker[company_id] = str(security.get("ticker") or "")
    descriptions_by_company = {
        str(row.get("company_id")): row for row in descriptions if row.get("company_id")
    }
    classifications_by_company = {
        str(row.get("company_id")): row
        for row in classifications
        if row.get("company_id")
    }
    relationships: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    rejected_evidence: list[dict[str, Any]] = []
    for kind, rows in (("industry_exposure", exposures), ("industry_edge", edges)):
        for row in rows:
            evidence_ids = [str(value) for value in row.get("evidence_ids") or [] if value]
            company_ids = []
            if kind == "industry_exposure" and row.get("company_id"):
                company_ids.append(str(row["company_id"]))
            if kind == "industry_edge":
                company_ids.extend(
                    str(row[field]) for field in ("source_entity_id", "target_entity_id")
                    if str(row.get(field) or "").startswith("company:")
                )
            if not evidence_ids or not all(
                evidence_id in approved_evidence_ids for evidence_id in evidence_ids
            ):
                rejected_evidence.append(
                    {
                        "record_id": row.get("exposure_id") or row.get("edge_id"),
                        "code": (
                            "RELATIONSHIP_EVIDENCE_MISSING"
                            if not evidence_ids
                            else "RELATIONSHIP_EVIDENCE_UNVERIFIED"
                        ),
                    }
                )
                continue
            for company_id in company_ids:
                relationships[company_id].append({**row, "_kind": kind, "_evidence_ids": evidence_ids})

    theme_counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    for company in sorted(companies, key=lambda row: str(row.get("company_id") or "")):
        company_id = str(company.get("company_id") or "")
        description = descriptions_by_company.get(company_id)
        classification = classifications_by_company.get(company_id)
        description_ids = [
            str(value)
            for value in (description or {}).get("provenance_ids") or []
            if value and str(value) in valid_provenance_ids
        ]
        classification_ids = [
            str(value)
            for value in (classification or {}).get("provenance_ids") or []
            if value and str(value) in valid_provenance_ids
        ]
        if description and not description_ids:
            rejected_evidence.append(
                {
                    "record_id": description.get("description_id") or company_id,
                    "code": "DESCRIPTION_PROVENANCE_MISSING_OR_UNVERIFIED",
                }
            )
        if classification and not classification_ids:
            rejected_evidence.append(
                {
                    "record_id": classification.get("classification_id") or company_id,
                    "code": "CLASSIFICATION_PROVENANCE_MISSING_OR_UNVERIFIED",
                }
            )
        description_text = _normalise((description or {}).get("business_description"))
        classification_text = _normalise(" ".join(str((classification or {}).get(key) or "") for key in ("official_sector", "official_industry")))
        inferred_themes: list[dict[str, Any]] = []
        inferred_sectors: list[dict[str, Any]] = []
        relationship_evidence = relationships.get(company_id, [])

        for theme in policy["themes"]:
            theme_evidence: list[dict[str, Any]] = []
            for sector in theme["sectors"]:
                sector_evidence: list[dict[str, Any]] = []
                description_hits = _matches(description_text, sector["terms"]) if description_ids else []
                if description_hits:
                    item = _evidence(
                        kind="canonical_business_description",
                        source_record_ids=description_ids,
                        matched_terms=description_hits,
                        weight=min(0.7, 0.56 + 0.03 * (len(description_hits) - 1)),
                    )
                    sector_evidence.append(item)
                    theme_evidence.append(item)
                classification_hits = _matches(classification_text, sector["terms"]) if classification_ids else []
                if classification_hits:
                    item = _evidence(
                        kind="official_classification",
                        source_record_ids=classification_ids,
                        matched_terms=classification_hits,
                        weight=min(0.8, 0.64 + 0.03 * (len(classification_hits) - 1)),
                    )
                    sector_evidence.append(item)
                    theme_evidence.append(item)
                for relation in relationship_evidence:
                    relation_text = _normalise(" ".join(str(relation.get(key) or "") for key in ("entity_id", "source_entity_id", "target_entity_id", "description_zh_tw", "rationale_zh_tw")))
                    relation_hits = _matches(relation_text, sector["terms"])
                    if relation_hits:
                        confidence = float(relation.get("confidence") or 0.5)
                        item = _evidence(
                            kind=relation["_kind"],
                            source_record_ids=relation["_evidence_ids"],
                            matched_terms=relation_hits,
                            weight=min(0.9, 0.55 + 0.35 * confidence),
                        )
                        sector_evidence.append(item)
                        theme_evidence.append(item)
                sector_score = _score(sector_evidence)
                if sector_score > 0:
                    inferred_sectors.append({"sector_id": sector["sector_id"], "theme_id": theme["theme_id"], "score": sector_score, "evidence": sector_evidence})
            theme_score = _score(theme_evidence)
            if theme_score > 0:
                inferred_themes.append({"theme_id": theme["theme_id"], "score": theme_score, "evidence": theme_evidence})

        inferred_themes.sort(key=lambda row: (-row["score"], row["theme_id"]))
        inferred_sectors.sort(key=lambda row: (-row["score"], row["sector_id"]))
        max_score = inferred_themes[0]["score"] if inferred_themes else 0.0
        thresholds = policy["analysis_thresholds"]
        has_verified_relationship = bool(relationship_evidence)
        analysis_policy = {
            "news": {"enabled": max_score >= float(thresholds["news"]), "reason_code": "THEME_SCORE_THRESHOLD_MET" if max_score >= float(thresholds["news"]) else "INSUFFICIENT_THEME_EVIDENCE"},
            "etf": {"enabled": max_score >= float(thresholds["etf"]), "reason_code": "THEME_SCORE_THRESHOLD_MET" if max_score >= float(thresholds["etf"]) else "INSUFFICIENT_THEME_EVIDENCE"},
            "industry_chain": {"enabled": has_verified_relationship or max_score >= float(thresholds["industry_chain"]), "reason_code": "VERIFIED_RELATIONSHIP_PRESENT" if has_verified_relationship else "THEME_SCORE_THRESHOLD_MET" if max_score >= float(thresholds["industry_chain"]) else "INSUFFICIENT_CHAIN_EVIDENCE"},
        }
        eligible = max_score >= float(policy["research_universe"]["minimum_score"])
        for theme in inferred_themes:
            if eligible:
                theme_counts[theme["theme_id"]] += 1
        records.append({
            "company_id": company_id,
            "ticker": primary_ticker.get(company_id) or None,
            "display_name": company.get("display_name") or company.get("legal_name"),
            "status": "eligible" if eligible else "unclassified",
            "research_score": max_score,
            "themes": inferred_themes,
            "sectors": inferred_sectors,
            "analysis_policy": analysis_policy,
        })

    ranked = sorted((row for row in records if row["status"] == "eligible"), key=lambda row: (-row["research_score"], row["company_id"]))
    limit = int(policy["research_universe"]["maximum_selected_companies"])
    selected_ids = {row["company_id"] for row in ranked[:limit]}
    for row in records:
        row["research_universe_status"] = "selected" if row["company_id"] in selected_ids else "eligible_not_selected" if row["status"] == "eligible" else "not_eligible"

    return {
        "schema_version": "theme-sector-inference.v031.1",
        "version": "V031.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "company_count": len(records),
            "evidence_eligible_company_count": len(ranked),
            "selected_research_company_count": len(selected_ids),
            "news_enabled_company_count": sum(row["analysis_policy"]["news"]["enabled"] for row in records),
            "etf_enabled_company_count": sum(row["analysis_policy"]["etf"]["enabled"] for row in records),
            "industry_chain_enabled_company_count": sum(row["analysis_policy"]["industry_chain"]["enabled"] for row in records),
            "theme_company_counts": dict(theme_counts),
            "rejected_evidence_count": len(rejected_evidence),
        },
        "policy": policy,
        "records": records,
        "diagnostics": {"rejected_evidence": rejected_evidence},
        "indexes": {"company_id_to_position": {row["company_id"]: index for index, row in enumerate(records)}, "ticker_to_position": {row["ticker"]: index for index, row in enumerate(records) if row["ticker"]}},
    }


def write_theme_sector_inference(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


class ThemeSectorInferenceService:
    def __init__(self, *, root: Path | None = None, snapshot_path: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.snapshot_path = snapshot_path or self.root / "data/generated/theme_sector_inference/theme_sector_inference.json"
        self._payload: Mapping[str, Any] | None = None

    def _get_payload(self) -> Mapping[str, Any]:
        if self._payload is None:
            self._payload = _load(self.snapshot_path) if self.snapshot_path.is_file() else build_theme_sector_inference(self.root)
        return self._payload

    def selected(self) -> dict[str, Any]:
        payload = self._get_payload()
        return {"schema_version": payload["schema_version"], "version": payload["version"], "summary": payload["summary"], "companies": [row for row in payload["records"] if row["research_universe_status"] == "selected"]}

    def get(self, ticker: str) -> Mapping[str, Any]:
        payload = self._get_payload()
        position = payload["indexes"]["ticker_to_position"].get(str(ticker or "").strip().upper())
        if position is None:
            raise ThemeSectorInferenceNotFound(f"ticker not found in population: {ticker}")
        return payload["records"][position]
