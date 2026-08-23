#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(
        0,
        str(ROOT / "src"),
    )


from axiom_engine.company_profile_v2.display_zh_tw import (  # noqa: E402
    build_company_profile_display_zh_tw,
)


CANONICAL_ROOT = (
    ROOT
    / "data/generated/company_profile_v2"
)

OUTPUT_ROOT = (
    ROOT
    / "data/generated/company_profile_display_zh_tw"
)

TRANSLATION_CENSUS = (
    CANONICAL_ROOT
    / "translation_universe_census_v2640.json"
)

DEFAULT_MODEL = "gpt-4.1-mini"

TRANSLATION_POLICY_VERSION = "v2.6.6.2c-tech-terms1"

TECHNICAL_TERMINOLOGY_RULE = (
    "技術縮寫、業界通用 acronym、介面名稱、架構名稱與產品技術名稱"
    "必須保留英文原文，不得翻成中文、不得展開全名、不得改寫縮寫。"
    "包括但不限於 AI、GPU、GPUs、CPU、CPUs、DPU、DPUs、HPC、"
    "SoC、SoCs、FPGA、FPGAs、ASIC、ASICs、NPU、NPUs、TPU、TPUs、"
    "PCIe、CXL、NVLink、CUDA、Ethernet、InfiniBand、HBM、DRAM、"
    "NAND、SSD、SSDs、NIC、NICs、DSP、DSPs、IP、API、SDK、"
    "NVMe、SATA、SAS、DDR、DDR5、LPDDR、LPDDR5、GDDR、RFFE、"
    "EDA、CFD、TSV、RRAM、OEM、OEMs、ODM、ODMs。"
    "可翻譯縮寫前後的一般描述，例如 energy efficient GPUs 應翻成"
    "「節能 GPUs」，HPC software stacks 應翻成「HPC 軟體堆疊」。"
)


OPENAI_CACHE_ROOT = (
    OUTPUT_ROOT / ".openai_cache"
)

AI_THEME_IDS = {
    "theme:ai_infrastructure",
    "theme:artificial_intelligence",
}


class CanonicalHandoffError(RuntimeError):
    """Raised when display/translation cannot prove canonical handoff integrity."""


def _write_json(
    path: Path,
    payload: object,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _load_json(
    path: Path,
) -> object:
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except FileNotFoundError as exc:
        raise CanonicalHandoffError(
            f"canonical handoff file not found: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise CanonicalHandoffError(
            f"canonical handoff file is invalid JSON: {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise CanonicalHandoffError(
            f"cannot read canonical handoff file: {path}: {exc}"
        ) from exc


def _canonical_index() -> dict:
    path = CANONICAL_ROOT / "index.json"
    payload = _load_json(path)

    if not isinstance(payload, dict):
        raise CanonicalHandoffError(
            f"canonical index is not an object: {path}"
        )

    symbol_to_file = payload.get(
        "symbol_to_file"
    )

    if not isinstance(
        symbol_to_file,
        dict,
    ):
        raise CanonicalHandoffError(
            "canonical index has no symbol_to_file mapping"
        )

    return payload


def _load_canonical_profile(
    symbol: str,
) -> dict:
    """Load the already-written production canonical profile.

    This function intentionally has no fallback to build_company_profile_v2().
    Display/translation must consume the same canonical artifact produced by the
    V2.6.5.7 extraction/gate pipeline. Missing or malformed canonical data is a
    hard handoff failure.
    """
    normalized_symbol = (
        str(symbol)
        .strip()
        .upper()
    )

    if not normalized_symbol:
        raise CanonicalHandoffError(
            "canonical handoff requires a symbol"
        )

    index = _canonical_index()
    relative = (
        index.get(
            "symbol_to_file",
            {},
        ).get(
            normalized_symbol
        )
    )

    if not relative:
        raise CanonicalHandoffError(
            "canonical handoff missing symbol "
            f"{normalized_symbol} in "
            f"{CANONICAL_ROOT / 'index.json'}"
        )

    relative_path = Path(
        str(relative)
    )

    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
    ):
        raise CanonicalHandoffError(
            f"unsafe canonical path for {normalized_symbol}: {relative}"
        )

    profile_path = (
        CANONICAL_ROOT
        / relative_path
    )

    payload = _load_json(
        profile_path
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise CanonicalHandoffError(
            f"canonical profile is not an object: {profile_path}"
        )

    actual_symbol = str(
        payload.get("symbol")
        or ""
    ).strip().upper()

    if (
        actual_symbol
        != normalized_symbol
    ):
        raise CanonicalHandoffError(
            "canonical symbol mismatch: "
            f"requested={normalized_symbol} "
            f"loaded={actual_symbol or '<missing>'} "
            f"path={profile_path}"
        )

    company_id = str(
        payload.get("company_id")
        or ""
    ).strip()

    if not company_id:
        raise CanonicalHandoffError(
            f"canonical profile has no company_id: {profile_path}"
        )

    product_stack = (
        payload.get(
            "product_stack"
        )
    )

    if not isinstance(
        product_stack,
        list,
    ):
        raise CanonicalHandoffError(
            "canonical product_stack is not an array: "
            f"{profile_path}"
        )

    return payload


def _load_index() -> dict:
    path = OUTPUT_ROOT / "index.json"

    if not path.exists():
        return {
            "schema_version":
                "axiom-company-profile-display-index.zh-tw.v2.4",
            "symbol_to_file": {},
            "company_id_to_file": {},
        }

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        payload = {}

    if not isinstance(
        payload,
        dict,
    ):
        payload = {}

    payload.setdefault(
        "symbol_to_file",
        {},
    )

    payload.setdefault(
        "company_id_to_file",
        {},
    )

    payload[
        "schema_version"
    ] = (
        "axiom-company-profile-display-index.zh-tw.v2.4"
    )

    return payload


def _write_payload(
    payload: dict,
) -> Path:
    company_id = str(
        payload["company_id"]
    )

    symbol = str(
        payload["symbol"]
    ).upper()

    # Match the canonical/display batch convention without importing the
    # extractor/batch layer back into this translation-only CLI.
    from urllib.parse import quote

    relative_path = (
        Path("per-company")
        / (
            quote(
                company_id,
                safe="",
            )
            + ".json"
        )
    )

    output_path = (
        OUTPUT_ROOT
        / relative_path
    )

    _write_json(
        output_path,
        payload,
    )

    index = _load_index()

    index[
        "symbol_to_file"
    ][symbol] = str(
        relative_path
    )

    index[
        "company_id_to_file"
    ][company_id] = str(
        relative_path
    )

    index[
        "symbols"
    ] = sorted(
        index[
            "symbol_to_file"
        ]
    )

    index[
        "company_count"
    ] = len(
        index[
            "company_id_to_file"
        ]
    )

    _write_json(
        OUTPUT_ROOT
        / "index.json",
        index,
    )

    return output_path


def _load_translation_candidates() -> list[dict]:
    if not TRANSLATION_CENSUS.is_file():
        raise FileNotFoundError(
            f"translation census not found: "
            f"{TRANSLATION_CENSUS.relative_to(ROOT)}"
        )

    payload = json.loads(
        TRANSLATION_CENSUS.read_text(
            encoding="utf-8"
        )
    )

    rows = payload.get(
        "translation_candidates"
    ) or []

    return [
        row
        for row in rows
        if isinstance(row, dict)
    ]


def _resolve_symbols(
    *,
    symbols: list[str] | None,
    ai_only: bool,
) -> list[str]:
    if symbols:
        return sorted(
            {
                str(symbol)
                .strip()
                .upper()
                for symbol in symbols
                if str(symbol).strip()
            }
        )

    if not ai_only:
        return []

    rows = _load_translation_candidates()

    selected = {
        str(row.get("symbol") or "")
        .strip()
        .upper()
        for row in rows
        if row.get("theme_id")
        in AI_THEME_IDS
        and row.get("symbol")
    }

    return sorted(selected)


def _extract_translation_surface(
    profile: dict,
) -> dict:
    summary = str(
        (
            profile.get("company_summary")
            or {}
        ).get(
            "one_line_business"
        )
        or ""
    ).strip()

    product_stack = [
        str(value).strip()
        for value in (
            profile.get("product_stack")
            or []
        )
        if str(value).strip()
    ]

    market_products = {}
    raw_market_products = (
        profile.get("market_products")
        or {}
    )

    if isinstance(
        raw_market_products,
        dict,
    ):
        for key, values in (
            raw_market_products.items()
        ):
            clean = [
                str(value).strip()
                for value in (
                    values
                    or []
                )
                if str(value).strip()
            ]

            if clean:
                market_products[
                    str(key)
                ] = clean

    markets = [
        str(value).strip()
        for value in (
            profile.get("markets")
            or []
        )
        if str(value).strip()
    ]

    customer_types = [
        str(value).strip()
        for value in (
            profile.get("customer_types")
            or []
        )
        if str(value).strip()
    ]

    return {
        "company_summary":
            summary or None,
        "product_stack":
            product_stack,
        "market_products":
            market_products,
        "markets":
            markets,
        "customer_types":
            customer_types,
        "core_technologies":
            profile.get("core_technologies") or [],
        "ai_exposure":
            profile.get("ai_exposure"),
        "demand_drivers":
            profile.get("demand_drivers") or [],
        "strategy_changes":
            profile.get("strategy_changes") or [],
    }


def _assert_product_handoff(
    *,
    profile: dict,
    translation_source: dict,
) -> None:
    canonical_products = [
        str(value).strip()
        for value in (
            profile.get(
                "product_stack"
            )
            or []
        )
        if str(value).strip()
    ]

    source_products = (
        translation_source.get(
            "product_stack"
        )
    )

    if (
        source_products
        != canonical_products
    ):
        raise CanonicalHandoffError(
            "product_stack handoff mismatch: "
            "canonical written product_stack != "
            "translation_source.product_stack"
        )


TRANSLATION_CENSUS_SURFACE_FIELDS = (
    "company_summary",
    "product_stack",
    "market_products",
    "markets",
    "customer_types",
    "core_technologies",
    "ai_exposure",
    "demand_drivers",
    "strategy_changes",
)


def _surface_value_present(
    value: object,
) -> bool:
    if value is None:
        return False

    if isinstance(
        value,
        str,
    ):
        return bool(
            value.strip()
        )

    if isinstance(
        value,
        (list, dict),
    ):
        return bool(
            value
        )

    return True


def _translation_readiness_row(
    symbol: str,
) -> dict:
    normalized_symbol = (
        str(symbol)
        .strip()
        .upper()
    )

    try:
        profile = (
            _load_canonical_profile(
                normalized_symbol
            )
        )
        source = (
            _extract_translation_surface(
                profile
            )
        )
        _assert_product_handoff(
            profile=profile,
            translation_source=source,
        )
    except Exception as exc:
        return {
            "symbol": normalized_symbol,
            "status": "FAIL",
            "reasons": [
                "CANONICAL_OR_HANDOFF_ERROR",
            ],
            "error": str(exc),
            "canonical_product_count": None,
            "translation_product_count": None,
            "populated_surface_count": 0,
            "populated_surface_fields": [],
        }

    canonical_products = [
        str(value).strip()
        for value in (
            profile.get("product_stack")
            or []
        )
        if str(value).strip()
    ]

    source_products = (
        source.get("product_stack")
        or []
    )

    populated_fields = [
        field
        for field in TRANSLATION_CENSUS_SURFACE_FIELDS
        if _surface_value_present(
            source.get(field)
        )
    ]

    reasons = []

    if not source.get("company_summary"):
        reasons.append(
            "EMPTY_COMPANY_SUMMARY"
        )

    if not source_products:
        reasons.append(
            "EMPTY_PRODUCT_STACK"
        )

    semantic_context_fields = {
        "market_products",
        "markets",
        "customer_types",
        "core_technologies",
        "ai_exposure",
        "demand_drivers",
        "strategy_changes",
    }

    populated_context = [
        field
        for field in populated_fields
        if field in semantic_context_fields
    ]

    if not populated_context:
        reasons.append(
            "NO_SEMANTIC_CONTEXT"
        )

    if (
        len(source_products)
        != len(canonical_products)
    ):
        return {
            "symbol": normalized_symbol,
            "company_id": profile.get(
                "company_id"
            ),
            "status": "FAIL",
            "reasons": [
                "PRODUCT_CARDINALITY_MISMATCH",
            ],
            "canonical_product_count": len(
                canonical_products
            ),
            "translation_product_count": len(
                source_products
            ),
            "populated_surface_count": len(
                populated_fields
            ),
            "populated_surface_fields": populated_fields,
        }

    status = (
        "READY"
        if not reasons
        else "REVIEW"
    )

    return {
        "symbol": normalized_symbol,
        "company_id": profile.get(
            "company_id"
        ),
        "status": status,
        "reasons": reasons,
        "canonical_product_count": len(
            canonical_products
        ),
        "translation_product_count": len(
            source_products
        ),
        "product_cardinality_match": True,
        "canonical_handoff":
            "read_back_verified",
        "populated_surface_count": len(
            populated_fields
        ),
        "populated_surface_fields": populated_fields,
        "semantic_context_count": len(
            populated_context
        ),
    }


def _translation_production_census() -> dict:
    index = _canonical_index()

    symbols = sorted(
        {
            str(symbol)
            .strip()
            .upper()
            for symbol in (
                index.get("symbol_to_file")
                or {}
            )
            if str(symbol).strip()
        }
    )

    rows = [
        _translation_readiness_row(
            symbol
        )
        for symbol in symbols
    ]

    counts = {
        "READY": 0,
        "REVIEW": 0,
        "FAIL": 0,
    }

    for row in rows:
        status = row.get("status")
        if status in counts:
            counts[status] += 1

    reason_counts = {}

    for row in rows:
        for reason in (
            row.get("reasons")
            or []
        ):
            reason_counts[reason] = (
                reason_counts.get(
                    reason,
                    0,
                )
                + 1
            )

    attention_rows = [
        row
        for row in rows
        if row.get("status")
        != "READY"
    ]

    return {
        "schema_version":
            "axiom-company-profile-translation-production-census.v2.6.5.8",
        "mode":
            "zero_api_canonical_readback",
        "openai_used":
            False,
        "canonical_company_count":
            len(symbols),
        "summary": {
            "total": len(rows),
            "ready": counts["READY"],
            "review": counts["REVIEW"],
            "fail": counts["FAIL"],
            "ready_rate": (
                round(
                    counts["READY"]
                    / len(rows),
                    4,
                )
                if rows
                else 0.0
            ),
            "usable_rate": (
                round(
                    (
                        counts["READY"]
                        + counts["REVIEW"]
                    )
                    / len(rows),
                    4,
                )
                if rows
                else 0.0
            ),
        },
        "reason_counts":
            dict(
                sorted(
                    reason_counts.items(),
                    key=lambda item: (
                        -item[1],
                        item[0],
                    ),
                )
            ),
        "attention_rows":
            attention_rows,
        "rows":
            rows,
    }


def _translation_census_one_screen(
    census: dict,
) -> str:
    summary = (
        census.get("summary")
        or {}
    )

    lines = [
        "=== V2.6.5.8 Translation Production Census ===",
        "",
        (
            f"Canonical companies  "
            f"{summary.get('total', 0):>4}"
        ),
        (
            f"READY                "
            f"{summary.get('ready', 0):>4}"
        ),
        (
            f"REVIEW               "
            f"{summary.get('review', 0):>4}"
        ),
        (
            f"FAIL                 "
            f"{summary.get('fail', 0):>4}"
        ),
        (
            f"Ready rate           "
            f"{summary.get('ready_rate', 0.0) * 100:.1f}%"
        ),
        (
            f"Usable rate          "
            f"{summary.get('usable_rate', 0.0) * 100:.1f}%"
        ),
        "",
        "Top readiness reasons",
    ]

    reason_counts = (
        census.get("reason_counts")
        or {}
    )

    if reason_counts:
        for reason, count in list(
            reason_counts.items()
        )[:12]:
            lines.append(
                f"  {reason:<32} {count:>4}"
            )
    else:
        lines.append("  -")

    attention = (
        census.get("attention_rows")
        or []
    )

    if attention:
        lines.extend(
            [
                "",
                "Attention",
            ]
        )

        for row in attention[:40]:
            reasons = (
                ", ".join(
                    row.get("reasons")
                    or []
                )
                or "-"
            )

            lines.append(
                (
                    f"  {row.get('symbol', ''):<6} "
                    f"{row.get('status', ''):<7} "
                    f"products="
                    f"{row.get('translation_product_count')} "
                    f"surface="
                    f"{row.get('populated_surface_count', 0)} "
                    f"{reasons}"
                )
            )

        if len(attention) > 40:
            lines.append(
                (
                    f"  ... "
                    f"{len(attention) - 40} more"
                )
            )

    return "\n".join(lines)


MAJOR_TECH_SYMBOLS = (
    "NVDA",
    "AMD",
    "AVGO",
    "QCOM",
    "MRVL",
    "ALAB",
    "ARM",
    "TSM",
    "ASML",
    "MU",
    "ANET",
    "CRDO",
    "VRT",
    "SMCI",
    "DELL",
    "MSFT",
    "GOOGL",
    "GOOG",
    "AMZN",
    "META",
    "ORCL",
    "AAPL",
    "PLTR",
    "SNPS",
    "CDNS",
    "AMAT",
    "LRCX",
    "KLAC",
    "ADI",
    "MCHP",
    "NXPI",
    "INTC",
)


def _translation_candidate_metadata_map() -> dict[str, dict]:
    """
    Reuse existing translation-universe metadata for priority assignment.
    No new theme taxonomy is invented in the display/translation layer.
    """
    rows = _load_translation_candidates()

    return {
        str(row.get("symbol") or "")
        .strip()
        .upper(): row
        for row in rows
        if row.get("symbol")
    }


def _estimate_input_tokens_from_characters(
    characters: int,
) -> int:
    """
    Deterministic planning estimate only; not an OpenAI billing/tokenizer quote.
    """
    if characters <= 0:
        return 0

    return max(
        1,
        int(
            math.ceil(
                characters
                / 3.5
            )
        ),
    )


def _translation_plan_priority(
    *,
    symbol: str,
    metadata: dict[str, dict],
) -> tuple[str, str]:
    normalized = (
        str(symbol)
        .strip()
        .upper()
    )

    if normalized in MAJOR_TECH_SYMBOLS:
        return (
            "P0",
            "major_tech",
        )

    row = metadata.get(
        normalized,
        {},
    )

    if row.get("theme_id") in AI_THEME_IDS:
        return (
            "P1",
            "core_ai_tech",
        )

    return (
        "P2",
        "strategic_remainder",
    )


def _translation_plan_source_metrics(
    source: dict,
) -> dict:
    canonical = json.dumps(
        source,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    populated_surface_fields = [
        field
        for field
        in TRANSLATION_CENSUS_SURFACE_FIELDS
        if _surface_value_present(
            source.get(field)
        )
    ]

    characters = len(
        canonical
    )

    return {
        "surface_field_count":
            len(
                populated_surface_fields
            ),
        "surface_fields":
            populated_surface_fields,
        "source_characters":
            characters,
        "estimated_input_tokens":
            _estimate_input_tokens_from_characters(
                characters
            ),
    }


def _translation_plan_row(
    *,
    readiness_row: dict,
    metadata: dict[str, dict],
) -> dict:
    symbol = str(
        readiness_row.get("symbol")
        or ""
    ).strip().upper()

    status = str(
        readiness_row.get("status")
        or ""
    )

    if status != "READY":
        return {
            "symbol": symbol,
            "status": status,
            "priority": None,
            "cohort": None,
            "translation_allowed": False,
            "reasons":
                readiness_row.get("reasons")
                or [],
            "canonical_handoff":
                readiness_row.get(
                    "canonical_handoff"
                ),
            "product_count":
                readiness_row.get(
                    "translation_product_count"
                ),
        }

    profile = _load_canonical_profile(
        symbol
    )

    source = _extract_translation_surface(
        profile
    )

    _assert_product_handoff(
        profile=profile,
        translation_source=source,
    )

    if not source.get("company_summary"):
        raise CanonicalHandoffError(
            f"{symbol}: READY plan requires company_summary"
        )

    products = (
        source.get("product_stack")
        or []
    )

    if not products:
        raise CanonicalHandoffError(
            f"{symbol}: READY plan requires non-empty product_stack"
        )

    priority, cohort = (
        _translation_plan_priority(
            symbol=symbol,
            metadata=metadata,
        )
    )

    metrics = (
        _translation_plan_source_metrics(
            source
        )
    )

    return {
        "symbol": symbol,
        "company_id":
            profile.get("company_id"),
        "status": "READY",
        "priority": priority,
        "cohort": cohort,
        "translation_allowed": True,
        "product_count":
            len(products),
        "canonical_handoff":
            "read_back_verified",
        "product_cardinality_match":
            True,
        **metrics,
    }


def _translation_production_plan() -> dict:
    """
    Zero-API deterministic production plan over the translation census.

    READY companies are planned. REVIEW/FAIL companies are explicitly excluded
    and remain translation_allowed=False.
    """
    census = _translation_production_census()
    metadata = _translation_candidate_metadata_map()

    planned = []
    excluded = []

    for readiness_row in (
        census.get("rows")
        or []
    ):
        row = _translation_plan_row(
            readiness_row=readiness_row,
            metadata=metadata,
        )

        if row.get(
            "translation_allowed"
        ):
            planned.append(
                row
            )
        else:
            excluded.append(
                row
            )

    priority_order = {
        "P0": 0,
        "P1": 1,
        "P2": 2,
    }

    planned.sort(
        key=lambda row: (
            priority_order.get(
                row.get("priority"),
                99,
            ),
            row.get("symbol")
            or "",
        )
    )

    cohort_counts = {
        "P0": 0,
        "P1": 0,
        "P2": 0,
    }

    workload = {
        "companies": 0,
        "product_items": 0,
        "surface_fields": 0,
        "source_characters": 0,
        "estimated_input_tokens": 0,
    }

    cohort_workload = {
        "P0": {
            key: 0
            for key in workload
        },
        "P1": {
            key: 0
            for key in workload
        },
        "P2": {
            key: 0
            for key in workload
        },
    }

    for row in planned:
        priority = row[
            "priority"
        ]

        cohort_counts[
            priority
        ] += 1

        values = {
            "companies": 1,
            "product_items":
                row.get(
                    "product_count"
                )
                or 0,
            "surface_fields":
                row.get(
                    "surface_field_count"
                )
                or 0,
            "source_characters":
                row.get(
                    "source_characters"
                )
                or 0,
            "estimated_input_tokens":
                row.get(
                    "estimated_input_tokens"
                )
                or 0,
        }

        for key, value in (
            values.items()
        ):
            workload[
                key
            ] += value
            cohort_workload[
                priority
            ][
                key
            ] += value

    review_included = sum(
        1
        for row in planned
        if row.get("status")
        == "REVIEW"
    )

    fail_included = sum(
        1
        for row in planned
        if row.get("status")
        == "FAIL"
    )

    mismatch_count = sum(
        1
        for row in planned
        if row.get(
            "product_cardinality_match"
        )
        is not True
    )

    ready_count = (
        census.get(
            "summary",
            {},
        ).get(
            "ready",
            0,
        )
    )

    if len(
        planned
    ) != ready_count:
        raise CanonicalHandoffError(
            "translation plan READY count mismatch: "
            f"census={ready_count} planned={len(planned)}"
        )

    if (
        review_included
        or fail_included
        or mismatch_count
    ):
        raise CanonicalHandoffError(
            "translation plan invariant failed: "
            f"review_included={review_included} "
            f"fail_included={fail_included} "
            f"product_mismatch={mismatch_count}"
        )

    return {
        "schema_version":
            "axiom-company-profile-translation-production-plan.v2.6.5.9",
        "mode":
            "zero_api_translation_production_plan",
        "openai_used":
            False,
        "canonical_company_count":
            census.get(
                "canonical_company_count"
            ),
        "ready_count":
            ready_count,
        "excluded_count":
            len(
                excluded
            ),
        "planned_count":
            len(
                planned
            ),
        "cohort_counts":
            cohort_counts,
        "workload":
            workload,
        "cohort_workload":
            cohort_workload,
        "invariants": {
            "openai_used": False,
            "review_included":
                review_included,
            "fail_included":
                fail_included,
            "product_mismatch":
                mismatch_count,
            "ready_equals_planned":
                ready_count
                == len(
                    planned
                ),
        },
        "excluded":
            excluded,
        "planned":
            planned,
    }


def _translation_plan_one_screen(
    plan: dict,
) -> str:
    workload = (
        plan.get("workload")
        or {}
    )

    cohort_counts = (
        plan.get("cohort_counts")
        or {}
    )

    cohort_workload = (
        plan.get("cohort_workload")
        or {}
    )

    invariants = (
        plan.get("invariants")
        or {}
    )

    lines = [
        "=== V2.6.5.9 Translation Production Plan ===",
        "",
        (
            f"Canonical            "
            f"{plan.get('canonical_company_count', 0):>4}"
        ),
        (
            f"READY                "
            f"{plan.get('ready_count', 0):>4}"
        ),
        (
            f"Excluded             "
            f"{plan.get('excluded_count', 0):>4}"
        ),
        (
            f"Planned              "
            f"{plan.get('planned_count', 0):>4}"
        ),
        "",
        "Priority cohorts",
    ]

    for priority, label in (
        ("P0", "Major Tech"),
        ("P1", "Core AI / Tech"),
        ("P2", "Strategic remainder"),
    ):
        cohort = (
            cohort_workload.get(
                priority
            )
            or {}
        )

        lines.append(
            (
                f"  {priority} {label:<20} "
                f"companies={cohort_counts.get(priority, 0):>4} "
                f"products={cohort.get('product_items', 0):>5} "
                f"chars={cohort.get('source_characters', 0):>8} "
                f"est_tokens={cohort.get('estimated_input_tokens', 0):>7}"
            )
        )

    lines.extend(
        [
            "",
            "Translation workload",
            (
                f"  companies               "
                f"{workload.get('companies', 0)}"
            ),
            (
                f"  product items           "
                f"{workload.get('product_items', 0)}"
            ),
            (
                f"  populated surface fields "
                f"{workload.get('surface_fields', 0)}"
            ),
            (
                f"  source characters       "
                f"{workload.get('source_characters', 0)}"
            ),
            (
                f"  estimated input tokens  "
                f"{workload.get('estimated_input_tokens', 0)}"
            ),
            "",
            "Invariant",
            (
                f"  OpenAI used              "
                f"{invariants.get('openai_used')}"
            ),
            (
                f"  REVIEW included          "
                f"{invariants.get('review_included')}"
            ),
            (
                f"  FAIL included            "
                f"{invariants.get('fail_included')}"
            ),
            (
                f"  Product mismatch         "
                f"{invariants.get('product_mismatch')}"
            ),
            (
                f"  READY == Planned         "
                f"{invariants.get('ready_equals_planned')}"
            ),
        ]
    )

    excluded = (
        plan.get("excluded")
        or []
    )

    if excluded:
        lines.extend(
            [
                "",
                "Excluded from API gate",
            ]
        )

        for row in excluded:
            reasons = (
                ", ".join(
                    row.get("reasons")
                    or []
                )
                or "-"
            )

            lines.append(
                (
                    f"  {row.get('symbol', ''):<6} "
                    f"{row.get('status', ''):<7} "
                    f"{reasons}"
                )
            )

    return "\n".join(
        lines
    )


def _build_translation_prompt(
    *,
    symbol: str,
    source: dict,
) -> str:
    return (
        "你是美股研究資料的繁體中文翻譯器。"
        "請把以下英文 Company Profile 翻成台灣繁體中文。\n"
        "規則：\n"
        "1. 只能翻譯來源已有內容，不得新增、推論、補齊任何公司事實。\n"
        "2. 缺失欄位維持 null、空陣列或空物件，不得自行補內容。\n"
        "3. 保留原本 JSON keys 與資料結構，不得增加或刪除 key。\n"
        "4. 公司名、產品品牌、技術標準、商標可保留英文；"
        "產業與商業描述翻成自然、專業的台灣繁中。\n"
        "5. 不要提供投資建議、估值、評論、摘要、解釋或 Markdown。\n"
        "6. 如果來源 fragment 明顯像 SEC 法律文字、客戶名稱、"
        "競爭者名稱或不完整片段，只忠實翻譯，不要美化成新的產品或市場事實。\n"
        "7. 陣列項目數與順序必須和來源完全一致，不得合併、刪除或新增項目。"
        "每一個來源 array item 必須對應且只能對應一個輸出 array item；"
        "即使來源 item 內含逗號、斜線、and、&、括號、冒號或多個名詞，也不得拆成多項。\n"
        "8. 品牌、產品家族、型號、技術標準與商標必須保留原文拼寫；"
        "例如 Aries、Leo、Scorpio、COSMOS、EPYC、Instinct、Ryzen、Radeon、"
        "Pensando、PCIe、CXL、Ethernet。\n"
        f"9. {TECHNICAL_TERMINOLOGY_RULE}\n"
        "10. 只回傳 JSON。\n\n"
        f"SYMBOL: {symbol}\n"
        "SOURCE_JSON:\n"
        + json.dumps(
            source,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _translation_cache_key(
    *,
    model: str,
    symbol: str,
    source: dict,
) -> str:
    canonical = json.dumps(
        {
            "translation_policy_version":
                TRANSLATION_POLICY_VERSION,
            "source":
                source,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()[:20]

    safe_model = (
        model.replace("/", "_")
        .replace(":", "_")
    )

    return (
        f"{symbol.upper()}__"
        f"{safe_model}__"
        f"{digest}.json"
    )


def _validate_translation_shape(
    *,
    source: object,
    translated: object,
    path: str = "$",
) -> None:
    """Translation may change strings, never the JSON structure/cardinality."""
    if source is None:
        if translated is not None:
            raise ValueError(
                f"translation shape mismatch at {path}: expected null"
            )
        return

    if isinstance(source, dict):
        if not isinstance(translated, dict):
            raise ValueError(
                f"translation shape mismatch at {path}: expected object"
            )
        if set(translated) != set(source):
            missing = sorted(set(source) - set(translated))
            extra = sorted(set(translated) - set(source))
            raise ValueError(
                f"translation keys mismatch at {path}: "
                f"missing={missing} extra={extra}"
            )
        for key, value in source.items():
            _validate_translation_shape(
                source=value,
                translated=translated[key],
                path=f"{path}.{key}",
            )
        return

    if isinstance(source, list):
        if not isinstance(translated, list):
            raise ValueError(
                f"translation shape mismatch at {path}: expected array"
            )
        if len(translated) != len(source):
            raise ValueError(
                f"translation item-count mismatch at {path}: "
                f"source={len(source)} translated={len(translated)}"
            )
        for index, value in enumerate(source):
            _validate_translation_shape(
                source=value,
                translated=translated[index],
                path=f"{path}[{index}]",
            )
        return

    if isinstance(source, bool):
        if not isinstance(translated, bool):
            raise ValueError(
                f"translation type mismatch at {path}: expected bool"
            )
        return

    if isinstance(source, (int, float)):
        if (
            not isinstance(translated, (int, float))
            or isinstance(translated, bool)
        ):
            raise ValueError(
                f"translation type mismatch at {path}: expected number"
            )
        return

    if not isinstance(translated, str):
        raise ValueError(
            f"translation type mismatch at {path}: expected string"
        )


def _load_translation_cache(
    *,
    model: str,
    symbol: str,
    source: dict,
) -> dict | None:
    path = (
        OPENAI_CACHE_ROOT
        / _translation_cache_key(
            model=model,
            symbol=symbol,
            source=source,
        )
    )

    if not path.is_file():
        return None

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None

    translated = payload.get(
        "translation"
    )

    if not isinstance(
        translated,
        dict,
    ):
        return None

    try:
        _validate_translation_shape(
            source=source,
            translated=translated,
        )
    except ValueError:
        return None

    return translated


def _write_translation_cache(
    *,
    model: str,
    symbol: str,
    source: dict,
    translation: dict,
) -> Path:
    OPENAI_CACHE_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        OPENAI_CACHE_ROOT
        / _translation_cache_key(
            model=model,
            symbol=symbol,
            source=source,
        )
    )

    _write_json(
        path,
        {
            "symbol": symbol.upper(),
            "model": model,
            "source": source,
            "translation": translation,
        },
    )

    return path


_ARRAY_LOCK_KEY = "__axiom_array__"


def _lock_translation_arrays(
    value: object,
) -> object:
    """
    Convert every JSON array into an indexed object before sending it to the
    model. The model can translate values, but it cannot legally change array
    cardinality without also changing object keys, which exact-shape validation
    rejects.
    """
    if isinstance(
        value,
        list,
    ):
        return {
            _ARRAY_LOCK_KEY: {
                str(index):
                    _lock_translation_arrays(
                        child
                    )
                for index, child
                in enumerate(
                    value
                )
            }
        }

    if isinstance(
        value,
        dict,
    ):
        return {
            str(key):
                _lock_translation_arrays(
                    child
                )
            for key, child
            in value.items()
        }

    return value


def _unlock_translation_arrays(
    value: object,
) -> object:
    if isinstance(
        value,
        dict,
    ):
        if (
            set(value)
            == {
                _ARRAY_LOCK_KEY
            }
            and isinstance(
                value[
                    _ARRAY_LOCK_KEY
                ],
                dict,
            )
        ):
            indexed = value[
                _ARRAY_LOCK_KEY
            ]

            keys = list(
                indexed.keys()
            )

            expected = [
                str(index)
                for index
                in range(
                    len(
                        indexed
                    )
                )
            ]

            if keys != expected:
                raise ValueError(
                    "translation array lock keys mismatch: "
                    f"expected={expected} actual={keys}"
                )

            return [
                _unlock_translation_arrays(
                    indexed[
                        str(index)
                    ]
                )
                for index
                in range(
                    len(
                        indexed
                    )
                )
            ]

        return {
            str(key):
                _unlock_translation_arrays(
                    child
                )
            for key, child
            in value.items()
        }

    return value


def _build_locked_translation_prompt(
    *,
    symbol: str,
    source: dict,
) -> str:
    locked = _lock_translation_arrays(
        source
    )

    return (
        "你是美股研究資料的繁體中文翻譯器。"
        "請把 LOCKED_SOURCE_JSON 中的英文值翻成台灣繁體中文。\n"
        "這份 JSON 已把所有 array 轉成 indexed object，以強制保持 cardinality。\n"
        "硬性規則：\n"
        "1. 只能翻譯 value，不得修改、增加、刪除、重新排序任何 key。\n"
        "2. __axiom_array__、其下的數字 keys 0,1,2... 都是結構 key，絕對不可翻譯或變更。\n"
        "3. 每個來源 value 只能產生一個對應 value，不得拆分或合併。\n"
        "4. 公司名、品牌、產品家族、型號、技術標準與商標保留原文；"
        "其餘忠實翻成自然、專業的台灣繁體中文。\n"
        f"5. {TECHNICAL_TERMINOLOGY_RULE}\n"
        "6. null、空 object、空 array wrapper 維持原樣。\n"
        "7. 不得新增、推論、補齊任何公司事實。\n"
        "8. 只回傳 JSON，不要 Markdown。\n\n"
        f"SYMBOL: {symbol}\n"
        "LOCKED_SOURCE_JSON:\n"
        + json.dumps(
            locked,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _translation_shape_manifest(
    value: object,
    *,
    path: str = "$",
) -> list[str]:
    rows = []

    if isinstance(
        value,
        dict,
    ):
        rows.append(
            (
                f"{path}: object keys="
                + json.dumps(
                    list(
                        value.keys()
                    ),
                    ensure_ascii=False,
                )
            )
        )

        for key, child in (
            value.items()
        ):
            rows.extend(
                _translation_shape_manifest(
                    child,
                    path=f"{path}.{key}",
                )
            )

        return rows

    if isinstance(
        value,
        list,
    ):
        rows.append(
            f"{path}: array length={len(value)}"
        )

        for index, child in enumerate(
            value
        ):
            if isinstance(
                child,
                (dict, list),
            ):
                rows.extend(
                    _translation_shape_manifest(
                        child,
                        path=f"{path}[{index}]",
                    )
                )

        return rows

    return rows


def _build_translation_repair_prompt(
    *,
    symbol: str,
    source: dict,
    validation_error: str,
    attempt: int,
) -> str:
    manifest = "\n".join(
        _translation_shape_manifest(
            source
        )
    )

    return (
        "上一個翻譯輸出未通過 JSON shape/cardinality 驗證，"
        "請重新從 SOURCE_JSON 產生完整翻譯，不要修改或沿用上一個錯誤輸出。\n"
        f"SYMBOL: {symbol}\n"
        f"REPAIR_ATTEMPT: {attempt}\n"
        f"VALIDATION_ERROR: {validation_error}\n\n"
        "硬性規則：\n"
        "1. 輸出 JSON 的 keys、巢狀結構、null、object、array 必須和來源完全相同。\n"
        "2. 每個 array 的長度必須和來源完全相同。\n"
        "3. 每一個來源 array item 必須對應且只能對應一個輸出 item。\n"
        "4. 絕對不可因逗號、斜線、and、&、括號、冒號、破折號或多個名詞，"
        "把一個來源 item 拆成兩個以上輸出 items。\n"
        "5. 不得合併兩個來源 items，也不得新增、刪除、排序 array items。\n"
        "6. 品牌、型號、技術標準與商標保留原文，其餘忠實翻成台灣繁體中文。\n"
        f"7. {TECHNICAL_TERMINOLOGY_RULE}\n"
        "8. 只回傳 JSON，不要 Markdown。\n\n"
        "REQUIRED_SHAPE:\n"
        f"{manifest}\n\n"
        "SOURCE_JSON:\n"
        + json.dumps(
            source,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _parse_openai_translation_text(
    text: str,
) -> dict:
    clean = str(
        text
        or ""
    ).strip()

    if clean.startswith(
        "```"
    ):
        clean = clean.strip(
            "`"
        )
        if clean.startswith(
            "json"
        ):
            clean = clean[
                4:
            ].lstrip()

    translated = json.loads(
        clean
    )

    if not isinstance(
        translated,
        dict,
    ):
        raise ValueError(
            "OpenAI output is not a JSON object"
        )

    return translated


def _request_openai_translation(
    *,
    client,
    model: str,
    prompt: str,
) -> dict:
    response = client.responses.create(
        model=model,
        input=prompt,
    )

    return _parse_openai_translation_text(
        response.output_text
    )


def _translate_with_openai(
    *,
    model: str,
    symbol: str,
    source: dict,
) -> tuple[dict, str]:
    cached = _load_translation_cache(
        model=model,
        symbol=symbol,
        source=source,
    )

    if cached is not None:
        return cached, "CACHE"

    if not os.environ.get(
        "OPENAI_API_KEY"
    ):
        raise RuntimeError(
            "OPENAI_API_KEY is not set"
        )

    from openai import OpenAI

    client = OpenAI()

    locked_source = (
        _lock_translation_arrays(
            source
        )
    )

    max_attempts = 3
    last_error = None

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        if attempt == 1:
            prompt = (
                _build_locked_translation_prompt(
                    symbol=symbol,
                    source=source,
                )
            )
        else:
            manifest = "\n".join(
                _translation_shape_manifest(
                    locked_source
                )
            )

            prompt = (
                "上一個翻譯輸出未通過 exact JSON shape 驗證。"
                "請重新翻譯 LOCKED_SOURCE_JSON。\n"
                f"SYMBOL: {symbol}\n"
                f"REPAIR_ATTEMPT: {attempt}\n"
                f"VALIDATION_ERROR: {last_error}\n\n"
                "硬性規則：\n"
                "1. 所有 object keys 必須與來源完全一致。\n"
                "2. __axiom_array__ 及其數字 keys 是鎖定的 array 結構，絕對不可修改。\n"
                "3. 只能翻譯 leaf string values。\n"
                "4. 不得新增、刪除、拆分、合併、排序任何項目。\n"
                f"5. {TECHNICAL_TERMINOLOGY_RULE}\n"
                "6. 只回傳 JSON。\n\n"
                "REQUIRED_LOCKED_SHAPE:\n"
                f"{manifest}\n\n"
                "LOCKED_SOURCE_JSON:\n"
                + json.dumps(
                    locked_source,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )

        try:
            locked_translated = (
                _request_openai_translation(
                    client=client,
                    model=model,
                    prompt=prompt,
                )
            )

            _validate_translation_shape(
                source=locked_source,
                translated=locked_translated,
            )

            translated = (
                _unlock_translation_arrays(
                    locked_translated
                )
            )

            _validate_translation_shape(
                source=source,
                translated=translated,
            )

        except (
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc

            if attempt >= max_attempts:
                raise ValueError(
                    f"{symbol}: OpenAI translation failed locked exact-shape "
                    f"validation after {max_attempts} attempts: {exc}"
                ) from exc

            continue

        _write_translation_cache(
            model=model,
            symbol=symbol,
            source=source,
            translation=translated,
        )

        result_source = (
            "API_LOCKED"
            if attempt == 1
            else f"API_LOCKED_REPAIR_{attempt}"
        )

        return (
            translated,
            result_source,
        )

    raise RuntimeError(
        f"{symbol}: unreachable locked translation retry state"
    )


def _build_payload_from_canonical(
    *,
    symbol: str,
) -> tuple[dict, dict, dict]:
    profile = _load_canonical_profile(
        symbol
    )

    source = (
        _extract_translation_surface(
            profile
        )
    )

    _assert_product_handoff(
        profile=profile,
        translation_source=source,
    )

    payload = dict(
        build_company_profile_display_zh_tw(
            ROOT,
            profile=profile,
        )
    )

    return (
        profile,
        source,
        payload,
    )


def _build_openai_payload(
    *,
    symbol: str,
    model: str,
) -> dict:
    profile, source, payload = (
        _build_payload_from_canonical(
            symbol=symbol,
        )
    )

    # Important ordering:
    # canonical read-back + product handoff invariant must pass before any
    # OpenAI cache/API access. A broken handoff therefore costs $0.
    _assert_product_handoff(
        profile=profile,
        translation_source=source,
    )

    translated, translation_source = (
        _translate_with_openai(
            model=model,
            symbol=symbol,
            source=source,
        )
    )

    payload[
        "translation_engine"
    ] = {
        "provider": "openai",
        "model": model,
        "mode": "company_profile_translation_only",
        "result_source": translation_source,
        "validation": "exact_json_shape_and_array_cardinality",
        "canonical_handoff": "read_back_verified",
    }

    payload[
        "translation_source"
    ] = source

    payload[
        "translation_zh_tw"
    ] = translated

    return payload


def _run_one(
    *,
    symbol: str,
    use_openai: bool,
    model: str,
    write: bool,
) -> dict:
    if use_openai:
        payload = (
            _build_openai_payload(
                symbol=symbol,
                model=model,
            )
        )
    else:
        _, source, payload = (
            _build_payload_from_canonical(
                symbol=symbol,
            )
        )

        # Expose the exact source even in non-OpenAI preview mode so the
        # canonical -> display/translation handoff can be inspected without
        # spending API money.
        payload = dict(
            payload
        )
        payload[
            "translation_source"
        ] = source
        payload[
            "canonical_handoff"
        ] = "read_back_verified"

    result = {
        "symbol":
            str(
                payload["symbol"]
            ).upper(),
        "company_id":
            payload["company_id"],
        "schema_version":
            payload["schema_version"],
        "payload":
            payload,
    }

    if write:
        output_path = (
            _write_payload(
                payload
            )
        )

        result[
            "status"
        ] = "written"

        result[
            "output"
        ] = str(
            output_path.relative_to(
                ROOT
            )
        )
    else:
        result[
            "status"
        ] = "preview"

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build zh-TW display payload from the already-written "
            "Company Profile V2 canonical artifact; optionally use "
            "OpenAI for translation-only handoff."
        )
    )

    parser.add_argument(
        "--symbol",
        help=(
            "Single ticker symbol, e.g. NVDA. "
            "Backward-compatible with the original CLI."
        ),
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        help=(
            "Multiple ticker symbols, e.g. "
            "--symbols NVDA AMD ALAB"
        ),
    )

    parser.add_argument(
        "--ai-only",
        action="store_true",
        help=(
            "Use all translation-eligible companies "
            "from AI Infrastructure and Artificial Intelligence "
            "in translation_universe_census_v2640.json."
        ),
    )

    parser.add_argument(
        "--openai",
        action="store_true",
        help=(
            "Translate Company Profile fields with OpenAI. "
            "Canonical read-back invariant is checked first."
        ),
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            f"OpenAI model. Default: {DEFAULT_MODEL}"
        ),
    )

    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Write per-company zh-TW display JSON "
            "and update its index."
        ),
    )

    parser.add_argument(
        "--translation-census",
        action="store_true",
        help=(
            "Run a zero-API translation readiness census over every "
            "production canonical profile."
        ),
    )

    parser.add_argument(
        "--translation-census-json",
        action="store_true",
        help=(
            "With --translation-census, print full machine-readable JSON."
        ),
    )

    parser.add_argument(
        "--translation-plan",
        action="store_true",
        help=(
            "Build a deterministic zero-API production plan from READY "
            "canonical profiles."
        ),
    )

    parser.add_argument(
        "--translation-plan-json",
        action="store_true",
        help=(
            "With --translation-plan, print the full machine-readable plan."
        ),
    )

    args = parser.parse_args()

    if args.translation_plan:
        plan = (
            _translation_production_plan()
        )

        if args.translation_plan_json:
            print(
                json.dumps(
                    plan,
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                _translation_plan_one_screen(
                    plan
                )
            )

        return 0

    if args.translation_census:
        census = (
            _translation_production_census()
        )

        if args.translation_census_json:
            print(
                json.dumps(
                    census,
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                _translation_census_one_screen(
                    census
                )
            )

        return (
            1
            if (
                census.get(
                    "summary",
                    {},
                ).get(
                    "fail",
                    0,
                )
                > 0
            )
            else 0
        )

    explicit_symbols = []

    if args.symbol:
        explicit_symbols.append(
            args.symbol
        )

    if args.symbols:
        explicit_symbols.extend(
            args.symbols
        )

    symbols = _resolve_symbols(
        symbols=(
            explicit_symbols
            or None
        ),
        ai_only=args.ai_only,
    )

    if not symbols:
        parser.error(
            "provide --symbol, --symbols, or --ai-only"
        )

    results = []
    failures = []

    for symbol in symbols:
        try:
            result = _run_one(
                symbol=symbol,
                use_openai=args.openai,
                model=args.model,
                write=args.write,
            )
        except Exception as exc:
            if len(symbols) == 1:
                raise

            failure = {
                "status": "failed",
                "symbol": symbol,
                "error": str(exc),
            }
            failures.append(
                failure
            )
            print(
                json.dumps(
                    failure,
                    ensure_ascii=False,
                )
            )
            continue

        results.append(
            result
        )

        if len(symbols) > 1:
            if args.write:
                print(
                    json.dumps(
                        {
                            "status":
                                result["status"],
                            "symbol":
                                result["symbol"],
                            "company_id":
                                result["company_id"],
                            "model":
                                (
                                    args.model
                                    if args.openai
                                    else None
                                ),
                            "output":
                                result.get("output"),
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                print()
                print(
                    f"=== {result['symbol']} ==="
                )
                print(
                    json.dumps(
                        result["payload"],
                        ensure_ascii=False,
                        indent=2,
                    )
                )

    if len(results) == 1:
        result = results[0]

        if args.write:
            print(
                json.dumps(
                    {
                        "status":
                            result["status"],
                        "symbol":
                            result["symbol"],
                        "company_id":
                            result["company_id"],
                        "schema_version":
                            result["schema_version"],
                        "output":
                            result.get("output"),
                        "model":
                            (
                                args.model
                                if args.openai
                                else None
                            ),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(
                json.dumps(
                    result["payload"],
                    ensure_ascii=False,
                    indent=2,
                )
            )

    if failures:
        print(
            json.dumps(
                {
                    "batch_status": "partial_failure",
                    "success_count": len(results),
                    "failure_count": len(failures),
                    "failed_symbols": [
                        row["symbol"]
                        for row in failures
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())