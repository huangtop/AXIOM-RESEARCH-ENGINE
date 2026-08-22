from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


POLICY_PATH = Path("config/company_profile_display.zh_tw.v2.json")


# This bridge does NOT classify companies.
# It only lets filing-native V2.3 values reuse an existing, reviewed
# display_names_zh_tw entry when the semantic match is exact enough.
RAW_TO_POLICY_ID = {
    "optical transceivers": "product:optical_transceiver",
    "Internet Data Center": "end_market:data_center",
    "Data Center": "end_market:data_center",
    "Telecom": "end_market:telecommunications",
    "cloud computing": "infrastructure:cloud_computing",
}


# Only phrases not covered by the Company Profile display policy belong here.
# Keep this deliberately small. It is a display fallback, not an ontology.
DISPLAY_FALLBACK_ZH_TW = {
    # Markets
    "CATV": "有線電視（CATV）",
    "FTTH": "光纖到府（FTTH）",
    "Gaming": "遊戲",
    "Professional Visualization": "專業視覺化",
    "Automotive": "汽車",

    # Product stack / products
    "lasers": "雷射",
    "laser components": "雷射元件",
    "components": "元件",
    "subassemblies": "次組件",
    "modules": "模組",
    "turn-key equipment": "完整交鑰匙設備",
    "laser subassemblies": "雷射次組件",
    "light engines": "光引擎",
    "transmitters": "發射器",
    "transceivers": "收發模組",
    "headend": "前端設備",
    "node": "光節點設備",
    "distribution equipment": "分配設備",
    "amplifiers": "放大器",

    # Technologies
    "Molecular Beam Epitaxy (MBE)": "分子束磊晶（MBE）",
    "Metal Organic Chemical Vapor Deposition (MOCVD)":
        "金屬有機化學氣相沉積（MOCVD）",
    "high-speed optical": "高速光通訊",
    "mixed-signal semiconductor": "混合訊號半導體",
    "mechanical engineering": "機械工程",

    # Manufacturing
    "vertically integrated": "垂直整合",
    "highly automated": "高度自動化",
    "geographically distributed": "跨地區分散製造",
    "United States": "美國",
    "Taiwan": "台灣",
    "China": "中國",
    "laser chip manufacturing": "雷射晶片製造",

    # Customer types
    "large internet-based data center operators":
        "大型網際網路資料中心營運商",
    "hyperscale data center operators":
        "超大規模資料中心營運商",
    "network equipment manufacturers":
        "網路設備製造商（NEM）",
    "other manufacturers of optical transceivers":
        "其他光收發模組製造商",
    "optical transceiver manufacturers":
        "光收發模組製造商",
    "CATV MSOs":
        "有線電視多系統營運商（MSO）",
    "CATV equipment vendors":
        "有線電視設備供應商",

    # Demand drivers
    "AI": "人工智慧（AI）",
    "DOCSIS 4.0": "DOCSIS 4.0",
    "5G": "5G",
    "PON": "被動光纖網路（PON）",
    "bandwidth growth": "頻寬需求成長",
    "800Gbps+ optical networking": "800Gbps 以上高速光網路",
    "robotics": "機器人",
    "HPC": "高效能運算（HPC）",
    "generative AI": "生成式 AI",
    "agentic AI": "代理型 AI",
}


ADVANTAGE_FALLBACK_ZH_TW = {
    "Proprietary technological expertise and track record of innovation":
        "專有技術與持續創新能力",
    "Innovative light engine design and manufacturing":
        "光引擎設計與製造能力",
    "Proven system design capabilities":
        "成熟的系統設計能力",
    "Industry-leading position in the CATV market":
        "CATV 市場領先地位",
    "Vertically integrated, highly automated and geographically distributed manufacturing model":
        "垂直整合、高度自動化且跨地區配置的製造模式",
}


CUSTOMER_CANONICAL_ALIASES = {
    "large internet-based data center operators":
        "hyperscale data center operators",
    "other manufacturers of optical transceivers":
        "optical transceiver manufacturers",
}


class CompanyProfileDisplayError(RuntimeError):
    pass


def _load_policy_labels(root: Path) -> dict[str, str]:
    path = root / POLICY_PATH

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyProfileDisplayError(
            f"cannot read display-name policy {path}: {exc}"
        ) from exc

    if payload.get("schema_version") != "axiom-company-profile-display-policy.v2":
        raise CompanyProfileDisplayError(
            "unsupported company-analysis policy"
        )

    labels = payload.get("display_names_zh_tw")

    if not isinstance(labels, dict):
        raise CompanyProfileDisplayError(
            "display_names_zh_tw missing from company-analysis policy"
        )

    return {
        str(key): str(value)
        for key, value in labels.items()
    }


def _display_value(
    value: Any,
    *,
    labels: Mapping[str, str],
) -> Any:
    if not isinstance(value, str):
        return value

    policy_id = RAW_TO_POLICY_ID.get(value)

    if policy_id:
        policy_value = labels.get(policy_id)
        if policy_value:
            return policy_value

    return DISPLAY_FALLBACK_ZH_TW.get(
        value,
        value,
    )


def _display_list(
    values: list[Any],
    *,
    labels: Mapping[str, str],
) -> list[Any]:
    return [
        _display_value(
            value,
            labels=labels,
        )
        for value in values
    ]


def _dedupe_customer_types(
    values: list[str],
) -> list[str]:
    output = []
    seen = set()

    for value in values:
        normalized = CUSTOMER_CANONICAL_ALIASES.get(
            value,
            value,
        )

        key = normalized.lower()

        if key in seen:
            continue

        seen.add(key)
        output.append(normalized)

    return output


def _format_money(
    value: Any,
) -> str | None:
    if value is None:
        return None

    numeric = float(value)

    if abs(numeric) >= 1_000_000_000:
        return f"${numeric / 1_000_000_000:.1f}B"

    if abs(numeric) >= 1_000_000:
        return f"${numeric / 1_000_000:.1f}M"

    return f"${numeric:,.0f}"


def _format_percent(
    value: Any,
) -> str | None:
    if value is None:
        return None

    return f"{float(value) * 100:.1f}%"


def _display_company_summary(
    value: str,
) -> str:
    lower = value.lower()

    if (
        "vertically integrated" in lower
        and "fiber-optic networking products" in lower
    ):
        return "垂直整合的光纖網路產品供應商"

    if (
        "accelerated computing" in lower
        and "nvidia" in lower
    ):
        return "加速運算與 AI 基礎設施平台供應商"

    return value


def _display_ai_exposure(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not value:
        return None

    summary = str(value.get("summary") or "")
    lower = summary.lower()

    if (
        "800gbps" in lower
        and "bandwidth" in lower
        and "ai" in lower
    ):
        summary_zh_tw = (
            "AI 應用需要更高運算能力與頻寬，"
            "推動資料中心升級至 800Gbps 以上高速光網路。"
        )
    elif summary:
        summary_zh_tw = summary
    else:
        summary_zh_tw = None

    return {
        "type": value.get("type"),
        "summary": summary_zh_tw,
    }


def _display_strategy_changes(
    rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output = []

    for row in rows:
        year = row.get("year")
        change = str(row.get("change") or "")
        brand = row.get("brand")

        if (
            year
            and brand
            and "MSO" in change
            and "CATV" in change
        ):
            display_change = (
                f"{year} 年起，開始以 {brand} 品牌"
                "直接向有線電視多系統營運商（MSO）"
                "銷售部分 CATV 產品。"
            )
        else:
            display_change = change

        item = {
            "year": year,
            "change": display_change,
        }

        if brand:
            item["brand"] = brand

        output.append(item)

    return output


def _display_market_products(
    payload: Mapping[str, Any],
    *,
    labels: Mapping[str, str],
) -> dict[str, list[str]]:
    market_key_names = {
        "internet_data_center": _display_value(
            "Internet Data Center",
            labels=labels,
        ),
        "data_center": _display_value(
            "Data Center",
            labels=labels,
        ),
        "catv": _display_value(
            "CATV",
            labels=labels,
        ),
        "telecom": _display_value(
            "Telecom",
            labels=labels,
        ),
        "ftth": _display_value(
            "FTTH",
            labels=labels,
        ),
        "gaming": _display_value(
            "Gaming",
            labels=labels,
        ),
        "professional_visualization": _display_value(
            "Professional Visualization",
            labels=labels,
        ),
        "automotive": _display_value(
            "Automotive",
            labels=labels,
        ),
    }

    output: dict[str, list[str]] = {}

    for key, values in payload.items():
        display_key = market_key_names.get(
            key,
            key,
        )

        output[display_key] = _display_list(
            list(values or []),
            labels=labels,
        )

    return output


def _display_financial_snapshot(
    payload: Mapping[str, Any],
    *,
    labels: Mapping[str, str],
) -> dict[str, Any]:
    revenue_mix = {
        _display_value(
            str(key),
            labels=labels,
        ): _format_percent(value)
        for key, value in (
            payload.get("revenue_mix") or {}
        ).items()
    }

    customer_concentration = {
        str(key): _format_percent(value)
        for key, value in (
            payload.get("customer_concentration") or {}
        ).items()
    }

    return {
        "fiscal_year":
            payload.get("fiscal_year"),
        "revenue":
            _format_money(
                payload.get("revenue")
            ),
        "gross_margin":
            _format_percent(
                payload.get("gross_margin")
            ),
        "net_loss":
            _format_money(
                payload.get("net_loss")
            ),
        "revenue_mix":
            revenue_mix,
        "customer_concentration":
            customer_concentration,
    }


def build_company_profile_display_zh_tw(
    root: Path,
    *,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    labels = _load_policy_labels(root)

    manufacturing = (
        profile.get("manufacturing")
        or {}
    )

    summary = (
        profile.get("company_summary")
        or {}
    )

    customer_types = _dedupe_customer_types(
        list(
            profile.get("customer_types")
            or []
        )
    )

    critical_assets = []

    for row in (
        manufacturing.get("critical_assets")
        or []
    ):
        critical_assets.append(
            {
                "asset": _display_value(
                    row.get("asset"),
                    labels=labels,
                ),
                # Specific place names remain source-faithful.
                "location": row.get("location"),
            }
        )

    display = {
        "locale": "zh-TW",
        "symbol": profile.get("symbol"),
        "as_of": profile.get("as_of"),

        "company_summary": {
            "one_line_business":
                _display_company_summary(
                    str(
                        summary.get(
                            "one_line_business"
                        )
                        or ""
                    )
                ),
        },

        "markets":
            _display_list(
                list(
                    profile.get("markets")
                    or []
                ),
                labels=labels,
            ),

        "product_stack":
            _display_list(
                list(
                    profile.get("product_stack")
                    or []
                ),
                labels=labels,
            ),

        "market_products":
            _display_market_products(
                profile.get("market_products")
                or {},
                labels=labels,
            ),

        "core_technologies":
            _display_list(
                list(
                    profile.get("core_technologies")
                    or []
                ),
                labels=labels,
            ),

        "manufacturing": {
            "model":
                _display_list(
                    list(
                        manufacturing.get("model")
                        or []
                    ),
                    labels=labels,
                ),
            "locations":
                _display_list(
                    list(
                        manufacturing.get(
                            "locations"
                        )
                        or []
                    ),
                    labels=labels,
                ),
            "critical_assets":
                critical_assets,
        },

        "customer_types":
            _display_list(
                customer_types,
                labels=labels,
            ),

        "ai_exposure":
            _display_ai_exposure(
                profile.get("ai_exposure")
            ),

        "competitive_advantages": [
            ADVANTAGE_FALLBACK_ZH_TW.get(
                str(value),
                str(value),
            )
            for value in (
                profile.get(
                    "competitive_advantages"
                )
                or []
            )
        ],

        "demand_drivers":
            _display_list(
                list(
                    profile.get("demand_drivers")
                    or []
                ),
                labels=labels,
            ),

        "strategy_changes":
            _display_strategy_changes(
                list(
                    profile.get(
                        "strategy_changes"
                    )
                    or []
                )
            ),

        "financial_snapshot":
            _display_financial_snapshot(
                profile.get(
                    "financial_snapshot"
                )
                or {},
                labels=labels,
            ),
    }

    return {
        "schema_version":
            "axiom-company-profile-display.zh-tw.v2.4",

        "generation_mode":
            "reuse_existing_display_names_zh_tw",

        "company_id":
            profile.get("company_id"),

        "symbol":
            profile.get("symbol"),

        "canonical_schema_version":
            profile.get("schema_version"),

        "display":
            display,

        # Preserve the V2.3 audit trail unchanged.
        "value_provenance":
            profile.get("value_provenance")
            or {},

        "evidence":
            profile.get("evidence")
            or [],
    }