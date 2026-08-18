from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


LEGACY_ANALYSIS_ROOT = Path("data/generated/company_analysis")


class CompanyProfileEnrichmentError(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyProfileEnrichmentError(
            f"cannot read {path}: {exc}"
        ) from exc


def _dedupe(values: list[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _legacy_analysis_for_symbol(
    root: Path,
    *,
    symbol: str,
) -> dict[str, Any] | None:
    base = root / LEGACY_ANALYSIS_ROOT
    index_path = base / "index.json"

    if not index_path.exists():
        return None

    index = _load_json(index_path)

    rel = (
        index.get("symbol_to_file")
        or {}
    ).get(symbol.upper())

    if not rel:
        return None

    path = base / rel

    if not path.exists():
        path = (
            base
            / "per-company"
            / rel
        )

    if not path.exists():
        return None

    payload = _load_json(path)

    return (
        payload
        if isinstance(payload, dict)
        else None
    )


def _legacy_offerings(
    legacy: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    values = []
    evidence_ids = []
    for row in legacy.get("offerings") or []:
        name = str(row.get("name") or "").strip()
        if name:
            values.append(name)
        evidence_ids.extend(
            str(value)
            for value in (row.get("evidence_ids") or [])
            if str(value)
        )
    return _dedupe(values), _dedupe(evidence_ids)


def _legacy_markets(
    legacy: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    values = []
    evidence_ids = []
    value_chain = legacy.get("value_chain") or {}
    for row in value_chain.get("downstream") or []:
        text = str(row.get("text") or "").strip()
        if text:
            values.append(text)
        evidence_ids.extend(
            str(value)
            for value in (row.get("evidence_ids") or [])
            if str(value)
        )
    return _dedupe(values), _dedupe(evidence_ids)


def _legacy_capabilities(
    legacy: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    values = []
    evidence_ids = []
    business_model = legacy.get("business_model") or {}
    for row in business_model.get("operating_capabilities") or []:
        text = str(row.get("text") or "").strip()
        if text:
            values.append(text)
        evidence_ids.extend(
            str(value)
            for value in (row.get("evidence_ids") or [])
            if str(value)
        )
    return _dedupe(values), _dedupe(evidence_ids)


def _direct_display_offerings(
    display: Mapping[str, Any],
) -> list[str]:
    values = []
    market_products = display.get("market_products") or {}
    for products in market_products.values():
        values.extend(
            str(value)
            for value in (products or [])
            if str(value)
        )
    return _dedupe(values)


def enrich_company_profile_display(
    root: Path,
    *,
    profile: Mapping[str, Any],
    display_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a production display payload without mutating canonical V2."""
    result = dict(display_payload)
    display = dict(result.get("display") or {})
    symbol = str(profile.get("symbol") or "").upper()
    legacy = _legacy_analysis_for_symbol(root, symbol=symbol)

    direct_offerings = _direct_display_offerings(display)
    direct_markets = _dedupe([
        str(value)
        for value in (display.get("markets") or [])
        if str(value)
    ])

    enrichment = {
        "schema_version": "axiom-company-profile-enrichment.v2.5.1",
        "mode": "direct_first_legacy_evidence_fallback",
        "legacy_source_used": False,
        "fallback_dimensions": [],
        "source_schema_version": None,
        "evidence_ids": [],
    }

    legacy_offerings = []
    legacy_markets = []
    legacy_capabilities = []
    legacy_evidence_ids = []

    if legacy:
        legacy_offerings, offering_evidence = _legacy_offerings(legacy)
        legacy_markets, market_evidence = _legacy_markets(legacy)
        legacy_capabilities, capability_evidence = _legacy_capabilities(legacy)
        legacy_evidence_ids = _dedupe(
            offering_evidence + market_evidence + capability_evidence
        )
        enrichment["source_schema_version"] = legacy.get("schema_version")

    if direct_offerings:
        display["offerings"] = direct_offerings
        display["offerings_source"] = "v2_direct"
    elif legacy_offerings:
        display["offerings"] = legacy_offerings
        display["offerings_source"] = "company_analysis_v1_fallback"
        enrichment["legacy_source_used"] = True
        enrichment["fallback_dimensions"].append("offerings")
    else:
        display["offerings"] = []
        display["offerings_source"] = None

    if direct_markets:
        display["markets"] = direct_markets
        display["markets_source"] = "v2_direct"
    elif legacy_markets:
        display["markets"] = legacy_markets
        display["markets_source"] = "company_analysis_v1_fallback"
        enrichment["legacy_source_used"] = True
        enrichment["fallback_dimensions"].append("markets")
    else:
        display["markets"] = []
        display["markets_source"] = None

    if legacy_capabilities:
        display["operating_capabilities"] = legacy_capabilities
        display["operating_capabilities_source"] = "company_analysis_v1_fallback"
        enrichment["legacy_source_used"] = True
        enrichment["fallback_dimensions"].append("operating_capabilities")
    else:
        display.setdefault("operating_capabilities", [])
        display.setdefault("operating_capabilities_source", None)

    enrichment["fallback_dimensions"] = _dedupe(
        enrichment["fallback_dimensions"]
    )
    enrichment["evidence_ids"] = (
        legacy_evidence_ids if enrichment["legacy_source_used"] else []
    )

    result["display"] = display
    result["production_enrichment"] = enrichment
    return result