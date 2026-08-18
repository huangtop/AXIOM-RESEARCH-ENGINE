from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


LEGACY_ANALYSIS_ROOT = Path(
    "data/generated/company_analysis"
)


class CompanyProfileEnrichmentError(
    RuntimeError
):
    pass


def _load_json(
    path: Path,
) -> Any:
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise CompanyProfileEnrichmentError(
            f"cannot read {path}: {exc}"
        ) from exc


def _dedupe(
    values: list[str],
) -> list[str]:
    output = []
    seen = set()

    for value in values:
        value = str(
            value or ""
        ).strip()

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
    base = (
        root
        / LEGACY_ANALYSIS_ROOT
    )

    index_path = (
        base
        / "index.json"
    )

    if not index_path.exists():
        return None

    index = _load_json(
        index_path
    )

    rel = (
        index.get(
            "symbol_to_file"
        )
        or {}
    ).get(
        symbol.upper()
    )

    if not rel:
        return None

    path = (
        base
        / rel
    )

    if not path.exists():
        path = (
            base
            / "per-company"
            / rel
        )

    if not path.exists():
        return None

    payload = _load_json(
        path
    )

    return (
        payload
        if isinstance(
            payload,
            dict,
        )
        else None
    )


def _legacy_offerings(
    legacy: Mapping[str, Any],
) -> tuple[
    list[str],
    list[str],
]:
    values = []
    evidence_ids = []

    for row in (
        legacy.get(
            "offerings"
        )
        or []
    ):
        name = str(
            row.get(
                "name"
            )
            or ""
        ).strip()

        if name:
            values.append(
                name
            )

        evidence_ids.extend(
            str(value)
            for value
            in (
                row.get(
                    "evidence_ids"
                )
                or []
            )
            if str(value)
        )

    return (
        _dedupe(values),
        _dedupe(
            evidence_ids
        ),
    )


def _legacy_markets(
    legacy: Mapping[str, Any],
) -> tuple[
    list[str],
    list[str],
]:
    values = []
    evidence_ids = []

    value_chain = (
        legacy.get(
            "value_chain"
        )
        or {}
    )

    for row in (
        value_chain.get(
            "downstream"
        )
        or []
    ):
        text = str(
            row.get(
                "text"
            )
            or ""
        ).strip()

        if text:
            values.append(
                text
            )

        evidence_ids.extend(
            str(value)
            for value
            in (
                row.get(
                    "evidence_ids"
                )
                or []
            )
            if str(value)
        )

    return (
        _dedupe(values),
        _dedupe(
            evidence_ids
        ),
    )


def _legacy_capabilities(
    legacy: Mapping[str, Any],
) -> tuple[
    list[str],
    list[str],
]:
    values = []
    evidence_ids = []

    business_model = (
        legacy.get(
            "business_model"
        )
        or {}
    )

    for row in (
        business_model.get(
            "operating_capabilities"
        )
        or []
    ):
        text = str(
            row.get(
                "text"
            )
            or ""
        ).strip()

        if text:
            values.append(
                text
            )

        evidence_ids.extend(
            str(value)
            for value
            in (
                row.get(
                    "evidence_ids"
                )
                or []
            )
            if str(value)
        )

    return (
        _dedupe(values),
        _dedupe(
            evidence_ids
        ),
    )


def _display_market_products_offerings(
    display: Mapping[str, Any],
) -> list[str]:
    """
    Highest-quality direct offering source.

    Example:
        Data Center:
            - GPU
            - networking product

    We flatten the product values, not
    the market names.
    """

    values = []

    market_products = (
        display.get(
            "market_products"
        )
        or {}
    )

    for products in (
        market_products.values()
    ):
        values.extend(
            str(value)
            for value
            in (
                products
                or []
            )
            if str(value)
        )

    return _dedupe(
        values
    )


def _display_product_stack(
    display: Mapping[str, Any],
) -> list[str]:
    """
    Generic V2.6.1 fallback.

    product_stack is already produced
    by canonical Company Profile V2 and
    translated by the display adapter.

    It is therefore suitable for the
    frontend "產品與服務" section when
    market_products is absent.
    """

    return _dedupe(
        [
            str(value)
            for value
            in (
                display.get(
                    "product_stack"
                )
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
            for value
            in (
                display.get(
                    "markets"
                )
                or []
            )
            if str(value)
        ]
    )


def _display_market_product_keys(
    display: Mapping[str, Any],
) -> list[str]:
    """
    market_products keys are legitimate
    end-market labels produced by the
    canonical display adapter.

    They can populate frontend markets
    when the standalone markets array
    is absent.
    """

    market_products = (
        display.get(
            "market_products"
        )
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
            for key
            in market_products
            if str(key).strip()
        ]
    )


def _display_customer_types(
    display: Mapping[str, Any],
) -> list[str]:
    """
    Last-resort frontend market proxy.

    This does NOT mutate canonical
    markets and is explicitly marked
    with markets_source =
    v2_customer_types_proxy.

    The frontend can therefore display
    useful target-customer context while
    provenance remains transparent.
    """

    return _dedupe(
        [
            str(value)
            for value
            in (
                display.get(
                    "customer_types"
                )
                or []
            )
            if str(value)
        ]
    )


def _display_capabilities(
    display: Mapping[str, Any],
) -> list[str]:
    manufacturing = (
        display.get(
            "manufacturing"
        )
        or {}
    )

    values = []

    values.extend(
        str(value)
        for value
        in (
            display.get(
                "core_technologies"
            )
            or []
        )
        if str(value)
    )

    values.extend(
        str(value)
        for value
        in (
            manufacturing.get(
                "model"
            )
            or []
        )
        if str(value)
    )

    return _dedupe(
        values
    )


def enrich_company_profile_display(
    root: Path,
    *,
    profile: Mapping[str, Any],
    display_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Build production frontend fields
    without mutating canonical V2.

    V2.6.1 precedence:

    Offerings
    ----------
    1. V2 market_products
    2. V2 product_stack
    3. reviewed legacy company_analysis

    Markets
    -------
    1. V2 direct markets
    2. V2 market_products keys
    3. V2 customer_types proxy
    4. reviewed legacy company_analysis

    Operating capabilities
    ----------------------
    1. V2 technologies/manufacturing
    2. reviewed legacy company_analysis

    All fallback sources are explicitly
    recorded in production_enrichment.
    """

    result = dict(
        display_payload
    )

    display = dict(
        result.get(
            "display"
        )
        or {}
    )

    symbol = str(
        profile.get(
            "symbol"
        )
        or ""
    ).upper()

    legacy = (
        _legacy_analysis_for_symbol(
            root,
            symbol=symbol,
        )
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
            "axiom-company-profile-enrichment.v2.6.1",

        "mode":
            "canonical_first_generic_frontend_fallback",

        "legacy_source_used":
            False,

        "fallback_dimensions":
            [],

        "source_schema_version":
            None,

        "evidence_ids":
            [],

        "frontend_sources":
            {
                "offerings":
                    None,
                "markets":
                    None,
                "operating_capabilities":
                    None,
            },
    }

    legacy_offerings = []
    legacy_markets = []
    legacy_capabilities = []
    legacy_evidence_ids = []

    if legacy:
        (
            legacy_offerings,
            offering_evidence,
        ) = _legacy_offerings(
            legacy
        )

        (
            legacy_markets,
            market_evidence,
        ) = _legacy_markets(
            legacy
        )

        (
            legacy_capabilities,
            capability_evidence,
        ) = _legacy_capabilities(
            legacy
        )

        legacy_evidence_ids = (
            _dedupe(
                offering_evidence
                + market_evidence
                + capability_evidence
            )
        )

        enrichment[
            "source_schema_version"
        ] = legacy.get(
            "schema_version"
        )

    # ---------------------------------
    # FRONTEND OFFERINGS
    # ---------------------------------

    if direct_offerings:
        display[
            "offerings"
        ] = direct_offerings

        display[
            "offerings_source"
        ] = "v2_market_products"

    elif product_stack:
        display[
            "offerings"
        ] = product_stack

        display[
            "offerings_source"
        ] = "v2_product_stack"

        enrichment[
            "fallback_dimensions"
        ].append(
            "offerings"
        )

    elif legacy_offerings:
        display[
            "offerings"
        ] = legacy_offerings

        display[
            "offerings_source"
        ] = (
            "company_analysis_v1_fallback"
        )

        enrichment[
            "legacy_source_used"
        ] = True

        enrichment[
            "fallback_dimensions"
        ].append(
            "offerings"
        )

    else:
        display[
            "offerings"
        ] = []

        display[
            "offerings_source"
        ] = None

    enrichment[
        "frontend_sources"
    ][
        "offerings"
    ] = display.get(
        "offerings_source"
    )

    # ---------------------------------
    # FRONTEND MARKETS
    # ---------------------------------

    if direct_markets:
        display[
            "markets"
        ] = direct_markets

        display[
            "markets_source"
        ] = "v2_direct"

    elif market_product_keys:
        display[
            "markets"
        ] = market_product_keys

        display[
            "markets_source"
        ] = (
            "v2_market_products"
        )

        enrichment[
            "fallback_dimensions"
        ].append(
            "markets"
        )

    elif customer_types:
        display[
            "markets"
        ] = customer_types

        display[
            "markets_source"
        ] = (
            "v2_customer_types_proxy"
        )

        enrichment[
            "fallback_dimensions"
        ].append(
            "markets"
        )

    elif legacy_markets:
        display[
            "markets"
        ] = legacy_markets

        display[
            "markets_source"
        ] = (
            "company_analysis_v1_fallback"
        )

        enrichment[
            "legacy_source_used"
        ] = True

        enrichment[
            "fallback_dimensions"
        ].append(
            "markets"
        )

    else:
        display[
            "markets"
        ] = []

        display[
            "markets_source"
        ] = None

    enrichment[
        "frontend_sources"
    ][
        "markets"
    ] = display.get(
        "markets_source"
    )

    # ---------------------------------
    # OPERATING CAPABILITIES
    # ---------------------------------

    if direct_capabilities:
        display[
            "operating_capabilities"
        ] = direct_capabilities

        display[
            "operating_capabilities_source"
        ] = (
            "v2_direct"
        )

    elif legacy_capabilities:
        display[
            "operating_capabilities"
        ] = legacy_capabilities

        display[
            "operating_capabilities_source"
        ] = (
            "company_analysis_v1_fallback"
        )

        enrichment[
            "legacy_source_used"
        ] = True

        enrichment[
            "fallback_dimensions"
        ].append(
            "operating_capabilities"
        )

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

    enrichment[
        "fallback_dimensions"
    ] = _dedupe(
        enrichment[
            "fallback_dimensions"
        ]
    )

    enrichment[
        "evidence_ids"
    ] = (
        legacy_evidence_ids
        if enrichment[
            "legacy_source_used"
        ]
        else []
    )

    result[
        "display"
    ] = display

    result[
        "production_enrichment"
    ] = enrichment

    return result