#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parents[1]

OVERVIEW_ROOT = Path("data/generated/company_overview")
PROFILE_ROOT = Path("data/generated/company_profile_v2")
DEFAULT_OUTPUT = PROFILE_ROOT / "translation_universe_census_v2640.json"

PROFILE_CENSUS_CANDIDATES = (
    PROFILE_ROOT / "full_market_census.json",
    PROFILE_ROOT / "production_readiness.json",
)

HISTORICAL_TRANSLATION_CENSUS = (
    PROFILE_ROOT / "translation_universe_census_v2640.json"
)

# Product scope gate. Only companies already selected into these strategic
# themes (AI / technology / energy / quantum / robotics / space / autonomy...)
# are in scope for Company Profile reconciliation / translation handoff.
STRATEGIC_THEME_PRIORITY = {
    "theme:ai_infrastructure": "P0",
    "theme:advanced_semiconductors": "P0",
    "theme:autonomous_vehicles": "P1",
    "theme:space_economy": "P1",
    "theme:quantum_computing": "P1",
    "theme:advanced_communications": "P1",
    "theme:clean_energy": "P1",
    "theme:advanced_manufacturing": "P1",
    "theme:robotics": "P1",
    "theme:digital_assets": "P2",
    "theme:digital_asset_infrastructure": "P2",
}

# Candidate bridge remains diagnostic only. It never grants translation
# eligibility because primary-business fit is not a thematic classification.
PRIMARY_BUSINESS_CANDIDATE_THEME = {
    "semiconductors_and_electronic_components": "theme:advanced_semiconductors",
    "communications_equipment": "theme:advanced_communications",
    "computing_hardware": "theme:ai_infrastructure",
    "aerospace_and_defense": "theme:space_economy",
    "automobile_manufacturing": "theme:autonomous_vehicles",
    "electrical_and_electronic_equipment": "theme:advanced_manufacturing",
}

TRUSTED_THEMATIC_SOURCES = {
    "curated_core_override",
    "reviewed_automatic_inference",
    "locked_published_classification",
}

PROFILE_READY_STATUSES = {"production_ready", "ready", "published"}

TRANSLATION_ELIGIBLE_SEMANTIC_STATUSES = {
    "TRANSLATE_NOW",
    "REPAIR_SUMMARY",
    "REPAIR_OFFERINGS",
    "REPAIR_MARKETS",
    "MULTI_FIELD_REPAIR",
}

DIAGNOSTIC_SAMPLE_LIMIT = 10


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _safe_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _overview_rows(root: Path) -> list[dict[str, Any]]:
    index = _load(root / OVERVIEW_ROOT / "index.json")
    mapping = index.get("ticker_to_file") or {}
    filenames = sorted({str(v) for v in mapping.values() if v})
    rows: list[dict[str, Any]] = []

    for filename in filenames:
        path = root / OVERVIEW_ROOT / "per-company" / filename
        if not path.is_file():
            continue
        payload = _load(path)
        if isinstance(payload, dict):
            rows.append(payload)

    rows.sort(key=lambda r: str(r.get("ticker") or r.get("company_id") or ""))
    return rows


def _profile_inventory_from_census(
    payload: Mapping[str, Any],
    source: str,
) -> dict[str, dict[str, Any]]:
    rows = payload.get("records") or payload.get("companies") or []
    output: dict[str, dict[str, Any]] = {}

    for row in rows:
        if not isinstance(row, Mapping):
            continue

        symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        company_id = str(row.get("company_id") or "")
        if not symbol and not company_id:
            continue

        direct = row.get("production_ready")
        status = str(row.get("status") or row.get("readiness") or "").lower()
        readiness = row.get("production_readiness") or {}

        ready = bool(
            direct is True
            or status in PROFILE_READY_STATUSES
            or (
                isinstance(readiness, Mapping)
                and readiness.get("production_ready") is True
            )
            or row.get("profile_production_ready") is True
        )

        generated = bool(
            row.get("generated") is True
            or row.get("profile_available") is True
            or row.get("company_profile_available") is True
            or row.get("build_status") == "generated"
            or row.get("canonical_schema_version")
            or row.get("profile_production_ready") is not None
            or direct is not None
        )

        semantic_flags = list(
            row.get("semantic_quality_flags")
            or row.get("semantic_flags")
            or row.get("quality_reasons")
            or row.get("readiness_reasons")
            or []
        )

        item = {
            "symbol": symbol,
            "company_id": company_id or None,
            "profile_generated": generated or ready,
            "previous_production_ready": ready,
            "profile_inventory_source": source,
            "semantic_flags": semantic_flags,
        }

        for key in (symbol, company_id):
            if key:
                output[key] = item

    return output


def _profile_inventory_from_translation_census(
    payload: Mapping[str, Any],
    source: str,
) -> dict[str, dict[str, Any]]:
    """Recover historical profile membership without self-overwrite loss."""
    output: dict[str, dict[str, Any]] = {}

    rows = payload.get("historical_profile_inventory")
    if not isinstance(rows, list):
        rows = payload.get("records") or []

    for row in rows:
        if not isinstance(row, Mapping):
            continue

        symbol = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
        company_id = str(row.get("company_id") or "")
        if not symbol and not company_id:
            continue

        ready = (
            row.get("profile_production_ready") is True
            or row.get("previous_production_ready") is True
        )

        item = {
            "symbol": symbol,
            "company_id": company_id or None,
            "profile_generated": ready,
            "previous_production_ready": ready,
            "profile_inventory_source": source,
            "semantic_flags": [],
            "historical_membership_only": True,
        }

        for key in (symbol, company_id):
            if key:
                output[key] = item

    return output


def _load_profile_inventory(
    root: Path,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    combined: dict[str, dict[str, Any]] = {}
    sources: list[str] = []

    historical_path = root / HISTORICAL_TRANSLATION_CENSUS
    if historical_path.is_file():
        try:
            historical_payload = _load(historical_path)
        except (OSError, json.JSONDecodeError):
            historical_payload = {}

        historical = _profile_inventory_from_translation_census(
            historical_payload,
            str(HISTORICAL_TRANSLATION_CENSUS),
        )
        if historical:
            sources.append(str(HISTORICAL_TRANSLATION_CENSUS))
            combined.update(historical)

    for rel in PROFILE_CENSUS_CANDIDATES:
        path = root / rel
        if not path.is_file():
            continue

        try:
            payload = _load(path)
        except (OSError, json.JSONDecodeError):
            continue

        inventory = _profile_inventory_from_census(payload, str(rel))
        sources.append(str(rel))

        for key, item in inventory.items():
            previous = combined.get(key, {})
            merged = dict(previous)
            merged.update(
                {
                    k: v
                    for k, v in item.items()
                    if v not in (None, "", [], False)
                }
            )
            merged["profile_generated"] = bool(
                previous.get("profile_generated")
                or item.get("profile_generated")
            )
            merged["previous_production_ready"] = bool(
                previous.get("previous_production_ready")
                or item.get("previous_production_ready")
            )
            merged["semantic_flags"] = sorted(
                set(
                    (previous.get("semantic_flags") or [])
                    + (item.get("semantic_flags") or [])
                )
            )
            combined[key] = merged

    index_path = root / PROFILE_ROOT / "index.json"
    if index_path.is_file():
        try:
            index = _load(index_path)
        except (OSError, json.JSONDecodeError):
            index = {}

        sources.append(str(PROFILE_ROOT / "index.json"))

        for symbol, relpath in (index.get("symbol_to_file") or {}).items():
            symbol = str(symbol).upper()
            current = dict(combined.get(symbol, {}))
            current.update(
                {
                    "symbol": symbol,
                    "profile_generated": True,
                    "current_canonical_profile": True,
                    "current_profile_file": str(relpath),
                }
            )
            combined[symbol] = current

    return combined, sources


def _is_locked(row: Mapping[str, Any]) -> bool:
    return (
        str(
            ((row.get("primary_business_lock") or {}).get("status") or "")
        ).lower()
        == "locked"
    )


def _thematic_lock(row: Mapping[str, Any]) -> bool:
    lock = row.get("classification_lock") or {}
    return (
        str(lock.get("status") or "").lower() == "locked"
        and str(lock.get("update_mode") or "").lower() == "manual_override_only"
    )


def _classification_authority(
    row: Mapping[str, Any],
) -> tuple[bool, str]:
    if not _thematic_lock(row):
        return False, "classification_lock_not_publication_grade"

    path = row.get("path") or {}
    theme = path.get("theme") if isinstance(path, Mapping) else None
    sector = path.get("sector") if isinstance(path, Mapping) else None

    if str(row.get("status") or "").lower() != "classified":
        return False, "classification_status_not_classified"
    if not isinstance(theme, Mapping) or not theme:
        return False, "theme_missing"
    if not isinstance(sector, Mapping) or not sector:
        return False, "sector_missing"

    source = str(row.get("classification_source") or "").strip()
    if source:
        if source in TRUSTED_THEMATIC_SOURCES:
            return True, "explicit_reviewed_source"
        return False, f"unapproved_explicit_source:{source}"

    if row.get("evidence"):
        return True, "legacy_locked_evidence_backed"

    return False, "classification_evidence_missing"


def _strategic_match(row: Mapping[str, Any]) -> dict[str, Any]:
    path = row.get("path") or {}
    theme = path.get("theme") or {}
    sector = path.get("sector") or {}
    theme_id = str(theme.get("id") or "")
    source = str(row.get("classification_source") or "")

    thematic_status = str(
        (
            (row.get("thematic_classification") or {}).get("status")
            or row.get("status")
            or ""
        )
    ).lower()

    if theme_id in STRATEGIC_THEME_PRIORITY and thematic_status == "classified":
        authority, authority_reason = _classification_authority(row)
        return {
            "strategic": True,
            "theme_id": theme_id,
            "theme_name": theme.get("name"),
            "theme_zh_tw": theme.get("display_name_zh_tw"),
            "sector_id": sector.get("id"),
            "sector_name": sector.get("name"),
            "classification_source": source or None,
            "match_basis": "thematic_classification",
            "classification_authority": authority,
            "classification_gate_reason": authority_reason,
            "classification_review_required": not authority,
            "priority": STRATEGIC_THEME_PRIORITY[theme_id],
        }

    primary = row.get("primary_business") or {}
    category = primary.get("category") or {}
    category_id = str(category.get("id") or "")
    candidate_theme = PRIMARY_BUSINESS_CANDIDATE_THEME.get(category_id)

    if candidate_theme and _is_locked(row):
        return {
            "strategic": True,
            "theme_id": candidate_theme,
            "theme_name": None,
            "theme_zh_tw": None,
            "sector_id": None,
            "sector_name": None,
            "classification_source": primary.get("classification_source"),
            "match_basis": "locked_primary_business_candidate",
            "classification_authority": False,
            "classification_gate_reason": (
                "primary_business_bridge_requires_thematic_confirmation"
            ),
            "classification_review_required": True,
            "priority": STRATEGIC_THEME_PRIORITY[candidate_theme],
        }

    return {"strategic": False}


def _build_profile_for_audit(
    root: Path,
    symbol: str,
) -> Mapping[str, Any]:
    from axiom_engine.company_profile_v2.core import build_company_profile_v2

    return build_company_profile_v2(root, symbol=symbol)


def _load_profile_artifact(
    root: Path,
    symbol: str,
    company_id: str | None,
) -> tuple[Mapping[str, Any] | None, str | None, str | None]:
    """Resolve existing Company Profile before attempting a rebuild."""
    profile_root = root / PROFILE_ROOT
    per_company = profile_root / "per-company"
    candidates: list[tuple[Path, str]] = []

    index_path = profile_root / "index.json"
    if index_path.is_file():
        try:
            index = _load(index_path)
        except (OSError, json.JSONDecodeError):
            index = {}

        symbol_map = index.get("symbol_to_file") or {}
        company_map = index.get("company_id_to_file") or {}

        rel = symbol_map.get(symbol)
        if rel:
            candidates.append(
                (profile_root / unquote(str(rel)), "indexed_symbol_artifact")
            )
            candidates.append(
                (profile_root / str(rel), "indexed_symbol_artifact")
            )

        if company_id:
            rel = company_map.get(company_id)
            if rel:
                candidates.append(
                    (
                        profile_root / unquote(str(rel)),
                        "indexed_company_id_artifact",
                    )
                )
                candidates.append(
                    (profile_root / str(rel), "indexed_company_id_artifact")
                )

    if company_id:
        candidates.extend(
            [
                (
                    per_company / f"{company_id}.json",
                    "company_id_artifact",
                ),
                (
                    per_company / f"{quote(company_id, safe='')}.json",
                    "encoded_company_id_artifact",
                ),
            ]
        )

    seen: set[str] = set()

    for path, reason in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)

        if not path.is_file():
            continue

        try:
            payload = _load(path)
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(payload, Mapping):
            continue

        payload_symbol = str(payload.get("symbol") or "").upper()
        payload_company_id = str(payload.get("company_id") or "")

        if payload_symbol == symbol or (
            company_id and payload_company_id == company_id
        ):
            return payload, "EXISTING_ARTIFACT", reason

    if per_company.is_dir():
        for path in sorted(per_company.glob("*.json")):
            if str(path) in seen:
                continue

            try:
                payload = _load(path)
            except (OSError, json.JSONDecodeError):
                continue

            if not isinstance(payload, Mapping):
                continue

            payload_symbol = str(payload.get("symbol") or "").upper()
            payload_company_id = str(payload.get("company_id") or "")

            if payload_symbol == symbol or (
                company_id and payload_company_id == company_id
            ):
                return (
                    payload,
                    "EXISTING_ARTIFACT",
                    "legacy_per_company_scan",
                )

    return None, None, None


def _resolve_profile_for_audit(
    root: Path,
    *,
    symbol: str,
    company_id: str | None,
) -> tuple[Mapping[str, Any] | None, str, str]:
    profile, source, reason = _load_profile_artifact(
        root,
        symbol,
        company_id,
    )

    if profile is not None:
        return profile, str(source), str(reason)

    try:
        rebuilt = _build_profile_for_audit(root, symbol)
    except FileNotFoundError:
        return None, "UNRESOLVED", "canonical_evidence_not_found"
    except (KeyError, ValueError) as exc:
        return (
            None,
            "UNRESOLVED",
            f"profile_rebuild_invalid_input:{type(exc).__name__}",
        )
    except Exception as exc:
        detail = " ".join(str(exc).split())
        if len(detail) > 300:
            detail = detail[:297] + "..."
        reason = f"profile_rebuild_failed:{type(exc).__name__}"
        if detail:
            reason = f"{reason}:{detail}"
        return None, "UNRESOLVED", reason

    if not isinstance(rebuilt, Mapping):
        return (
            None,
            "UNRESOLVED",
            "profile_rebuild_returned_non_mapping",
        )

    return (
        rebuilt,
        "REBUILT_FROM_EVIDENCE",
        "rebuilt_from_canonical_evidence",
    )


def _offering_values(profile: Mapping[str, Any]) -> list[str]:
    values: list[str] = []

    for value in profile.get("product_stack") or []:
        text = str(value).strip()
        if text:
            values.append(text)

    market_products = profile.get("market_products") or {}
    if isinstance(market_products, Mapping):
        for product_rows in market_products.values():
            for value in product_rows or []:
                text = str(value).strip()
                if text:
                    values.append(text)

    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            output.append(value)

    return output


def _semantic_profile_audit(
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    field_flags: dict[str, list[str]] = {
        "summary": [],
        "offerings": [],
        "markets": [],
    }
    flags: list[str] = []

    summary = str(
        ((profile.get("company_summary") or {}).get("one_line_business") or "")
    ).strip()

    offerings = _offering_values(profile)

    markets = [
        str(value).strip()
        for value in (profile.get("markets") or [])
        if str(value).strip()
    ]

    customers = {
        str(value).strip().casefold()
        for value in (profile.get("customer_types") or [])
        if str(value).strip()
    }

    if not summary:
        field_flags["summary"].append("missing_summary")
    elif len(summary) < 45:
        field_flags["summary"].append("summary_too_short")

    if summary and re.search(
        r"\b(?:our strategy|strategic priorities|capital allocation|"
        r"centralized procurement|shareholder value|risk factors)\b",
        summary,
        flags=re.IGNORECASE,
    ):
        field_flags["summary"].append(
            "summary_strategy_or_corporate_boilerplate"
        )

    if not offerings:
        field_flags["offerings"].append("missing_offerings")

    generic_offering_exact = {
        "products",
        "services",
        "solutions",
        "technology",
        "technologies",
        "capabilities",
        "business",
        "operations",
        "platform",
        "platforms",
    }

    for value in offerings:
        lower = value.casefold()
        if lower in generic_offering_exact:
            field_flags["offerings"].append("generic_offering")
            break

        if re.search(
            r"\b(?:customer demand|market demand|competitive advantage|"
            r"capital allocation|supply chain strategy|growth strategy)\b",
            lower,
        ):
            field_flags["offerings"].append(
                "non_offering_corporate_statement"
            )
            break

    if not markets:
        field_flags["markets"].append("missing_markets")

    geography_exact = {
        "united states",
        "u.s.",
        "us",
        "china",
        "japan",
        "india",
        "canada",
        "mexico",
        "europe",
        "asia",
        "australia",
        "south america",
        "north america",
        "latin america",
        "south korea",
        "new zealand",
        "middle east",
        "africa",
    }

    demand_prefixes = (
        "demand for ",
        "growth in ",
        "investment in ",
        "increase in ",
    )

    product_market_terms = {
        "gpu",
        "gpus",
        "cpu",
        "cpus",
        "dram",
        "nand",
        "hbm",
        "dimm",
        "dimms",
        "semiconductor",
        "semiconductors",
        "processor",
        "processors",
        "chipset",
        "chipsets",
        "accelerator",
        "accelerators",
    }

    for value in markets:
        lower = value.casefold()

        if lower in customers:
            field_flags["markets"].append("customer_type_as_market")
        if lower in geography_exact:
            field_flags["markets"].append("geography_as_market")
        if lower.startswith(demand_prefixes):
            field_flags["markets"].append("demand_driver_as_market")
        if lower in product_market_terms:
            field_flags["markets"].append("product_or_capability_as_market")
        if re.search(
            r"\b(?:we|our|strategy|strategic|shareholder|revenue growth)\b",
            lower,
        ):
            field_flags["markets"].append("strategy_statement_as_market")

    for field in field_flags:
        field_flags[field] = sorted(set(field_flags[field]))
        flags.extend(
            f"{field}:{reason}"
            for reason in field_flags[field]
        )

    bad_fields = [
        field
        for field, reasons in field_flags.items()
        if reasons
    ]

    if not bad_fields:
        bucket = "TRANSLATE_NOW"
    elif len(bad_fields) > 1:
        bucket = "MULTI_FIELD_REPAIR"
    elif bad_fields[0] == "summary":
        bucket = "REPAIR_SUMMARY"
    elif bad_fields[0] == "offerings":
        bucket = "REPAIR_OFFERINGS"
    else:
        bucket = "REPAIR_MARKETS"

    return {
        "semantic_audit_status": bucket,
        "semantic_quality_flags": sorted(set(flags)),
        "semantic_field_flags": field_flags,
        "summary_available": bool(summary),
        "offerings_available": bool(offerings),
        "markets_available": bool(markets),
        "summary_preview": summary[:240] if summary else None,
        "offerings_preview": offerings[:12],
        "markets_preview": markets[:12],
    }


def _audit_reuse_profile(
    root: Path,
    symbol: str,
    company_id: str | None,
) -> dict[str, Any]:
    profile, source, reason = _resolve_profile_for_audit(
        root,
        symbol=symbol,
        company_id=company_id,
    )

    if profile is None:
        return {
            "semantic_audit_status": "PROFILE_ARTIFACT_MISSING",
            "semantic_profile_source": source,
            "semantic_profile_resolution_reason": reason,
            "semantic_quality_flags": [f"profile_resolution:{reason}"],
            "semantic_field_flags": {
                "summary": [],
                "offerings": [],
                "markets": [],
            },
            "summary_available": False,
            "offerings_available": False,
            "markets_available": False,
            "summary_preview": None,
            "offerings_preview": [],
            "markets_preview": [],
        }

    result = _semantic_profile_audit(profile)
    result["semantic_profile_source"] = source
    result["semantic_profile_resolution_reason"] = reason
    return result


def _profile_state(
    symbol: str,
    company_id: str,
    inventory: Mapping[str, Mapping[str, Any]],
    *,
    classification_review_required: bool,
) -> dict[str, Any]:
    info = inventory.get(symbol) or inventory.get(company_id) or {}
    generated = bool(info.get("profile_generated"))
    ready = bool(info.get("previous_production_ready"))
    flags = list(info.get("semantic_flags") or [])

    if classification_review_required:
        action = "CLASSIFICATION_REVIEW"
    elif ready and not flags:
        action = "REUSE_TRANSLATE"
    elif generated:
        action = "PROFILE_REPAIR"
    else:
        action = "NEW_PROFILE_BUILD"

    return {
        "profile_generated": generated,
        "previous_production_ready": ready,
        "profile_inventory_source": info.get("profile_inventory_source"),
        "current_canonical_profile": bool(
            info.get("current_canonical_profile")
        ),
        "semantic_flags": flags,
        "recommended_action": action,
    }


def _translation_eligibility(
    row: Mapping[str, Any],
) -> tuple[bool, str, str]:
    """Final V2.6.4.3 translation handoff contract.

    Scope is determined by the upstream strategic company census.
    Semantic repair remains visible as quality metadata, but does not block
    translation when a Company Profile was successfully resolved.
    """
    if row.get("strategic") is not True:
        return False, "BLOCKED", "not_strategic"

    # The 558-row strategic census is already the upstream scope gate.
    # match_basis / classification_authority remain audit metadata only.
    # Do not apply a second classification gate here: newly bridged strategic
    # companies must be allowed to continue once their profile resolves.
    semantic_status = str(row.get("semantic_audit_status") or "")

    if semantic_status == "PROFILE_ARTIFACT_MISSING":
        return (
            False,
            "EVIDENCE_MISSING",
            str(
                row.get("semantic_profile_resolution_reason")
                or "company_profile_missing"
            ),
        )

    if semantic_status not in TRANSLATION_ELIGIBLE_SEMANTIC_STATUSES:
        return (
            False,
            "BLOCKED",
            f"unsupported_semantic_status:{semantic_status}",
        )

    if semantic_status == "TRANSLATE_NOW":
        return True, "STRICT", "semantic_pass"

    return (
        True,
        "PARTIAL",
        f"semantic_repair_retained:{semantic_status}",
    )


def _diagnostic_row(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "symbol": record.get("symbol"),
        "company_id": record.get("company_id"),
        "display_name": record.get("display_name"),
        "theme_id": record.get("theme_id"),
        "priority": record.get("priority"),
        "semantic_audit_status": record.get("semantic_audit_status"),
        "semantic_profile_source": record.get("semantic_profile_source"),
        "semantic_profile_resolution_reason": record.get(
            "semantic_profile_resolution_reason"
        ),
        "semantic_quality_flags": record.get("semantic_quality_flags") or [],
        "semantic_field_flags": record.get("semantic_field_flags") or {},
        "summary_available": bool(record.get("summary_available")),
        "offerings_available": bool(record.get("offerings_available")),
        "markets_available": bool(record.get("markets_available")),
        "summary_preview": record.get("summary_preview"),
        "offerings_preview": record.get("offerings_preview") or [],
        "markets_preview": record.get("markets_preview") or [],
    }


def _semantic_failure_diagnostics(
    records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    repair_buckets = (
        "REPAIR_SUMMARY",
        "REPAIR_OFFERINGS",
        "REPAIR_MARKETS",
        "MULTI_FIELD_REPAIR",
    )

    samples: dict[str, list[dict[str, Any]]] = {}
    counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    build_failures: list[dict[str, Any]] = []

    for record in records:
        status = str(record.get("semantic_audit_status") or "")
        if not status or status == "TRANSLATE_NOW":
            continue

        counts[status] += 1

        for flag in record.get("semantic_quality_flags") or []:
            flag_counts[str(flag)] += 1

        row = _diagnostic_row(record)

        if status == "PROFILE_ARTIFACT_MISSING":
            build_failures.append(row)
        elif status in repair_buckets:
            bucket = samples.setdefault(status, [])
            if len(bucket) < DIAGNOSTIC_SAMPLE_LIMIT:
                bucket.append(row)

    build_failures.sort(
        key=lambda row: (
            str(row.get("theme_id") or ""),
            str(row.get("symbol") or ""),
        )
    )

    for rows in samples.values():
        rows.sort(
            key=lambda row: (
                str(row.get("theme_id") or ""),
                str(row.get("symbol") or ""),
            )
        )

    return {
        "counts": dict(sorted(counts.items())),
        "semantic_flag_counts": dict(sorted(flag_counts.items())),
        "repair_samples": dict(sorted(samples.items())),
        "build_failures": build_failures,
    }


def build_report(root: Path) -> dict[str, Any]:
    rows = _overview_rows(root)
    inventory, inventory_sources = _load_profile_inventory(root)

    records: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    theme_counts: dict[str, Counter[str]] = defaultdict(Counter)
    action_counts: Counter[str] = Counter()
    semantic_audit_counts: Counter[str] = Counter()
    semantic_profile_source_counts: Counter[str] = Counter()
    semantic_resolution_reason_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    classification_gate_reason_counts: Counter[str] = Counter()
    translation_quality_counts: Counter[str] = Counter()
    translation_reason_counts: Counter[str] = Counter()

    for row in rows:
        symbol = str(row.get("ticker") or "").upper()
        company_id = str(row.get("company_id") or "")
        primary_status = str(
            ((row.get("primary_business") or {}).get("status") or "")
        ).lower()
        primary_locked = _is_locked(row)

        if not primary_locked:
            pending.append(
                {
                    "symbol": symbol,
                    "company_id": company_id,
                    "display_name": row.get("display_name"),
                    "primary_business_status": primary_status or None,
                }
            )
            continue

        match = _strategic_match(row)
        if not match.get("strategic"):
            continue

        profile = _profile_state(
            symbol,
            company_id,
            inventory,
            classification_review_required=bool(
                match["classification_review_required"]
            ),
        )

        record = {
            "symbol": symbol,
            "company_id": company_id,
            "display_name": row.get("display_name"),
            "primary_business_locked": True,
            **match,
            **profile,
        }

        # Company Profile audit is downstream of strategic selection.
        semantic = _audit_reuse_profile(root, symbol, company_id)
        record.update(semantic)

        (
            translation_eligible,
            translation_quality,
            translation_reason,
        ) = _translation_eligibility(record)

        record["translation_eligible"] = translation_eligible
        record["translation_quality"] = translation_quality
        record["translation_eligibility_reason"] = translation_reason

        records.append(record)

        theme_id = str(record["theme_id"])
        theme_counts[theme_id]["companies"] += 1
        theme_counts[theme_id][record["recommended_action"]] += 1

        semantic_status = str(record.get("semantic_audit_status") or "")
        if semantic_status and semantic_status != "NOT_AUDITED":
            theme_counts[theme_id][f"profile:{semantic_status}"] += 1

        if translation_eligible:
            theme_counts[theme_id]["translation:ELIGIBLE"] += 1
        else:
            theme_counts[theme_id][
                f"translation:{translation_quality}"
            ] += 1

        action_counts[record["recommended_action"]] += 1

        if semantic_status and semantic_status != "NOT_AUDITED":
            semantic_audit_counts[semantic_status] += 1
            semantic_profile_source_counts[
                str(record.get("semantic_profile_source") or "UNKNOWN")
            ] += 1
            semantic_resolution_reason_counts[
                str(
                    record.get("semantic_profile_resolution_reason")
                    or "unknown"
                )
            ] += 1

        priority_counts[record["priority"]] += 1
        classification_gate_reason_counts[
            str(record.get("classification_gate_reason") or "not_applicable")
        ] += 1
        translation_quality_counts[translation_quality] += 1
        translation_reason_counts[translation_reason] += 1

    records.sort(
        key=lambda r: (
            r["priority"],
            r["theme_id"],
            r["symbol"],
        )
    )
    pending.sort(key=lambda r: r["symbol"])

    translation_candidates = [
        {
            "symbol": row["symbol"],
            "company_id": row.get("company_id"),
            "display_name": row.get("display_name"),
            "theme_id": row.get("theme_id"),
            "theme_name": row.get("theme_name"),
            "theme_zh_tw": row.get("theme_zh_tw"),
            "sector_id": row.get("sector_id"),
            "sector_name": row.get("sector_name"),
            "priority": row.get("priority"),
            "translation_quality": row.get("translation_quality"),
            "semantic_audit_status": row.get("semantic_audit_status"),
            "semantic_quality_flags": list(
                row.get("semantic_quality_flags") or []
            ),
            "semantic_profile_source": row.get("semantic_profile_source"),
        }
        for row in records
        if row.get("translation_eligible") is True
    ]

    translation_strict_count = sum(
        1
        for row in records
        if row.get("translation_eligible") is True
        and row.get("translation_quality") == "STRICT"
    )

    translation_partial_count = sum(
        1
        for row in records
        if row.get("translation_eligible") is True
        and row.get("translation_quality") == "PARTIAL"
    )

    translation_evidence_missing_count = sum(
        1
        for row in records
        if row.get("translation_quality") == "EVIDENCE_MISSING"
    )

    summary = {
        "company_universe_count": len(rows),
        "primary_business_locked_count": len(rows) - len(pending),
        "primary_business_pending_count": len(pending),
        "strategic_company_count": len(records),
        "reuse_translate_count": action_counts["REUSE_TRANSLATE"],
        "translate_now_count": semantic_audit_counts["TRANSLATE_NOW"],
        "profile_repair_count": sum(
            semantic_audit_counts[key]
            for key in (
                "REPAIR_SUMMARY",
                "REPAIR_OFFERINGS",
                "REPAIR_MARKETS",
                "MULTI_FIELD_REPAIR",
            )
        ),
        "profile_artifact_missing_count": (
            semantic_audit_counts["PROFILE_ARTIFACT_MISSING"]
        ),
        "semantic_profile_source_counts": dict(
            sorted(semantic_profile_source_counts.items())
        ),
        "semantic_resolution_reason_counts": dict(
            sorted(semantic_resolution_reason_counts.items())
        ),
        "strategic_profile_audited_count": sum(
            semantic_audit_counts.values()
        ),
        "strategic_profile_ready_count": (
            semantic_audit_counts["TRANSLATE_NOW"]
        ),
        "strategic_profile_repair_count": sum(
            semantic_audit_counts[key]
            for key in (
                "REPAIR_SUMMARY",
                "REPAIR_OFFERINGS",
                "REPAIR_MARKETS",
                "MULTI_FIELD_REPAIR",
            )
        ),
        "strategic_profile_build_failed_count": (
            semantic_audit_counts["PROFILE_ARTIFACT_MISSING"]
        ),
        "new_profile_build_count": action_counts["NEW_PROFILE_BUILD"],
        "classification_review_count": (
            action_counts["CLASSIFICATION_REVIEW"]
        ),
        "semantic_audit_counts": dict(
            sorted(semantic_audit_counts.items())
        ),
        "historical_profile_ready_recovered_count": sum(
            1 for row in records if row.get("previous_production_ready")
        ),
        "priority_counts": dict(sorted(priority_counts.items())),
        "classification_gate_reason_counts": dict(
            sorted(classification_gate_reason_counts.items())
        ),
        "translation_eligible_count": len(translation_candidates),
        "translation_strict_count": translation_strict_count,
        "translation_partial_count": translation_partial_count,
        "translation_evidence_missing_count": (
            translation_evidence_missing_count
        ),
        "translation_blocked_count": translation_quality_counts["BLOCKED"],
        "translation_quality_counts": dict(
            sorted(translation_quality_counts.items())
        ),
        "translation_eligibility_reason_counts": dict(
            sorted(translation_reason_counts.items())
        ),
    }

    return {
        "schema_version": (
            "axiom-strategic-company-profile-reconciliation.v2.6.4.3"
        ),
        "generation_mode": "dry_run_inventory_reconciliation",
        "principles": [
            "classification_is_upstream_gate",
            "strategic_census_is_translation_scope_gate",
            "preserve_existing_profiles",
            "reuse_before_repair_before_new_build",
            "match_basis_is_audit_metadata_not_translation_blocker",
            "semantic_repair_does_not_block_translation_handoff",
            "profile_artifact_missing_blocks_translation",
            "no_production_publish",
        ],
        "translation_policy": {
            "scope_gate": "strategic_company_census",
            "strict_semantic_status": "TRANSLATE_NOW",
            "partial_semantic_statuses": [
                "REPAIR_SUMMARY",
                "REPAIR_OFFERINGS",
                "REPAIR_MARKETS",
                "MULTI_FIELD_REPAIR",
            ],
            "profile_blocker": "PROFILE_ARTIFACT_MISSING",
            "note": (
                "Semantic repair flags remain quality metadata. "
                "They do not remove a successfully resolved profile from "
                "the translation handoff cohort."
            ),
        },
        "profile_inventory_sources": inventory_sources,
        "historical_profile_inventory": sorted(
            [
                {
                    "symbol": str(item.get("symbol") or key).upper(),
                    "company_id": item.get("company_id"),
                    "previous_production_ready": True,
                }
                for key, item in inventory.items()
                if item.get("previous_production_ready")
                and str(item.get("symbol") or key).upper()
                == str(key).upper()
            ],
            key=lambda row: (
                row["symbol"],
                str(row.get("company_id") or ""),
            ),
        ),
        "summary": summary,
        "theme_counts": {
            theme_id: dict(sorted(counter.items()))
            for theme_id, counter in sorted(theme_counts.items())
        },
        "translation_candidates": translation_candidates,
        "semantic_failure_diagnostics": (
            _semantic_failure_diagnostics(records)
        ),
        "records": records,
        "pending_primary_business": pending,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "V2.6.4.3 strategic Company Profile reconciliation census "
            "and translation handoff contract."
        )
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write census JSON; default is dry-run.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
    )
    args = parser.parse_args()

    report = build_report(ROOT)
    summary = report["summary"]

    print(
        "=== V2.6.4.3 Strategic Company Profile Reconciliation "
        "+ Translation Handoff ==="
    )

    for key in (
        "company_universe_count",
        "primary_business_locked_count",
        "primary_business_pending_count",
        "strategic_company_count",
        "reuse_translate_count",
        "translate_now_count",
        "profile_repair_count",
        "profile_artifact_missing_count",
        "strategic_profile_audited_count",
        "strategic_profile_ready_count",
        "strategic_profile_repair_count",
        "strategic_profile_build_failed_count",
        "new_profile_build_count",
        "classification_review_count",
        "historical_profile_ready_recovered_count",
        "translation_eligible_count",
        "translation_strict_count",
        "translation_partial_count",
        "translation_evidence_missing_count",
        "translation_blocked_count",
    ):
        print(f"{key:36s} {summary[key]}")

    print(
        "priority_counts:",
        json.dumps(summary["priority_counts"], sort_keys=True),
    )
    print(
        "classification_gate_reason_counts:",
        json.dumps(
            summary["classification_gate_reason_counts"],
            sort_keys=True,
        ),
    )
    print(
        "semantic_audit_counts:",
        json.dumps(summary["semantic_audit_counts"], sort_keys=True),
    )
    print(
        "semantic_profile_source_counts:",
        json.dumps(
            summary["semantic_profile_source_counts"],
            sort_keys=True,
        ),
    )
    print(
        "translation_quality_counts:",
        json.dumps(
            summary["translation_quality_counts"],
            sort_keys=True,
        ),
    )

    print()
    print("Theme counts:")
    for theme_id, counts in report["theme_counts"].items():
        print(
            f"  {theme_id:36s} "
            f"{json.dumps(counts, sort_keys=True)}"
        )

    print()
    print("Profile inventory sources:")
    for source in report["profile_inventory_sources"]:
        print(" ", source)

    diagnostics = report["semantic_failure_diagnostics"]

    print()
    print("Semantic failure diagnostics:")
    print(
        "  counts:",
        json.dumps(diagnostics["counts"], sort_keys=True),
    )
    print(
        "  semantic_flag_counts:",
        json.dumps(
            diagnostics["semantic_flag_counts"],
            sort_keys=True,
        ),
    )
    print(
        "  build_failures:",
        len(diagnostics["build_failures"]),
    )

    for bucket, rows in diagnostics["repair_samples"].items():
        print(f"  {bucket} samples:")
        for row in rows:
            print(
                "    "
                f"{str(row.get('symbol') or ''):8s} "
                f"flags={','.join(row.get('semantic_quality_flags') or [])} "
                f"offerings={row.get('offerings_preview') or []} "
                f"markets={row.get('markets_preview') or []}"
            )

    print()
    print("Translation handoff:")
    print("  eligible:", summary["translation_eligible_count"])
    print("  strict:  ", summary["translation_strict_count"])
    print("  partial: ", summary["translation_partial_count"])
    print(
        "  evidence_missing:",
        summary["translation_evidence_missing_count"],
    )

    if args.write:
        output = Path(args.output)
        if not output.is_absolute():
            output = ROOT / output
        _write(output, report)
        print()
        print("written:", output.relative_to(ROOT))
    else:
        print()
        print(
            "dry-run: no production artifact modified; "
            "use --write to write census only"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
