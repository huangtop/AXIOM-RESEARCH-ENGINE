from __future__ import annotations

from typing import Any, Mapping


class CompanyProfileEnrichmentError(RuntimeError):
    pass


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


def _display_market_products_offerings(
    display: Mapping[str, Any],
) -> list[str]:
    values = []

    market_products = (
        display.get("market_products")
        or {}
    )

    for products in market_products.values():
        values.extend(
            str(value)
            for value in (products or [])
            if str(value)
        )

    return _dedupe(values)


def _display_product_stack(
    display: Mapping[str, Any],
) -> list[str]:
    return _dedupe(
        [
            str(value)
            for value in (
                display.get("product_stack")
                or []
            )
            if str(value)
        ]
    )


def _display_direct_markets(
    display: Mapping[str, Any],
) -> list[str]:
    return _dedupe(
        [
            str(value)
            for value in (
                display.get("markets")
                or []
            )
            if str(value)
        ]
    )


def _display_market_product_keys(
    display: Mapping[str, Any],
) -> list[str]:
    market_products = (
        display.get("market_products")
        or {}
    )

    if not isinstance(
        market_products,
        Mapping,
    ):
        return []

    return _dedupe(
        [
            str(key)
            for key in market_products
            if str(key).strip()
        ]
    )


def _display_customer_types(
    display: Mapping[str, Any],
) -> list[str]:
    return _dedupe(
        [
            str(value)
            for value in (
                display.get("customer_types")
                or []
            )
            if str(value)
        ]
    )


def _display_capabilities(
    display: Mapping[str, Any],
) -> list[str]:
    manufacturing = (
        display.get("manufacturing")
        or {}
    )

    values = []

    values.extend(
        str(value)
        for value in (
            display.get("core_technologies")
            or []
        )
        if str(value)
    )

    values.extend(
        str(value)
        for value in (
            manufacturing.get("model")
            or []
        )
        if str(value)
    )

    return _dedupe(values)


def enrich_company_profile_display(
    root,
    *,
    profile: Mapping[str, Any],
    display_payload: Mapping[str, Any],
) -> dict[str, Any]:
    _ = root
    _ = profile

    result = dict(display_payload)

    display = dict(
        result.get("display")
        or {}
    )

    direct_offerings = (
        _display_market_products_offerings(
            display
        )
    )

    product_stack = (
        _display_product_stack(
            display
        )
    )

    direct_markets = (
        _display_direct_markets(
            display
        )
    )

    market_product_keys = (
        _display_market_product_keys(
            display
        )
    )

    customer_types = (
        _display_customer_types(
            display
        )
    )

    direct_capabilities = (
        _display_capabilities(
            display
        )
    )

    enrichment = {
        "schema_version":
            "axiom-company-profile-enrichment.v2.6.2",
        "mode":
            "canonical_only_generic_frontend_fallback",
        "legacy_source_used":
            False,
        "fallback_dimensions":
            [],
        "source_schema_version":
            None,
        "evidence_ids":
            [],
        "frontend_sources": {
            "offerings": None,
            "markets": None,
            "operating_capabilities": None,
        },
    }

    if direct_offerings:
        display["offerings"] = (
            direct_offerings
        )
        display["offerings_source"] = (
            "v2_market_products"
        )

    elif product_stack:
        display["offerings"] = (
            product_stack
        )
        display["offerings_source"] = (
            "v2_product_stack"
        )
        enrichment[
            "fallback_dimensions"
        ].append("offerings")

    else:
        display["offerings"] = []
        display["offerings_source"] = None

    enrichment[
        "frontend_sources"
    ]["offerings"] = display.get(
        "offerings_source"
    )

    if direct_markets:
        display["markets"] = (
            direct_markets
        )
        display["markets_source"] = (
            "v2_direct"
        )

    elif market_product_keys:
        display["markets"] = (
            market_product_keys
        )
        display["markets_source"] = (
            "v2_market_products"
        )
        enrichment[
            "fallback_dimensions"
        ].append("markets")

    elif customer_types:
        display["markets"] = (
            customer_types
        )
        display["markets_source"] = (
            "v2_customer_types_proxy"
        )
        enrichment[
            "fallback_dimensions"
        ].append("markets")

    else:
        display["markets"] = []
        display["markets_source"] = None

    enrichment[
        "frontend_sources"
    ]["markets"] = display.get(
        "markets_source"
    )

    if direct_capabilities:
        display[
            "operating_capabilities"
        ] = direct_capabilities

        display[
            "operating_capabilities_source"
        ] = "v2_direct"

    else:
        display.setdefault(
            "operating_capabilities",
            [],
        )
        display.setdefault(
            "operating_capabilities_source",
            None,
        )

    enrichment[
        "frontend_sources"
    ][
        "operating_capabilities"
    ] = display.get(
        "operating_capabilities_source"
    )

    result["display"] = display
    result[
        "production_enrichment"
    ] = enrichment

    return result
