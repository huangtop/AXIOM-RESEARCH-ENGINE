from pathlib import Path

from axiom_engine.company_profile_v2 import (
    build_company_profile_v2,
)

from axiom_engine.company_profile_v2.display_zh_tw import (
    build_company_profile_display_zh_tw,
)


ROOT = Path(__file__).resolve().parents[1]


def _display(
    symbol: str,
):
    profile = build_company_profile_v2(
        ROOT,
        symbol=symbol,
    )

    return (
        build_company_profile_display_zh_tw(
            ROOT,
            profile=profile,
        )
    )


def test_v24_aaoi_reuses_existing_policy_labels():
    row = _display("AAOI")

    assert (
        row["schema_version"]
        == "axiom-company-profile-display.zh-tw.v2.4"
    )

    assert (
        row["generation_mode"]
        == "reuse_existing_display_names_zh_tw"
    )

    display = row["display"]

    # Internet Data Center maps through the existing
    # end_market:data_center policy label.
    assert "雲端與資料中心" in (
        display["markets"]
    )

    # optical transceivers maps through the existing
    # product:optical_transceiver policy label.
    dc = display[
        "market_products"
    ][
        "雲端與資料中心"
    ]

    assert "光收發模組" in dc


def test_v24_aaoi_keeps_v23_detail_in_chinese_display():
    display = _display("AAOI")[
        "display"
    ]

    assert (
        display[
            "company_summary"
        ][
            "one_line_business"
        ]
        == "垂直整合的光纖網路產品供應商"
    )

    assert "有線電視（CATV）" in (
        display["markets"]
    )

    assert "光纖到府（FTTH）" in (
        display["markets"]
    )

    assert {
        "雷射",
        "雷射元件",
        "元件",
        "次組件",
        "模組",
        "完整交鑰匙設備",
    }.issubset(
        set(
            display[
                "product_stack"
            ]
        )
    )

    catv = display[
        "market_products"
    ][
        "有線電視（CATV）"
    ]

    assert "放大器" in catv

    telecom = display[
        "market_products"
    ][
        "電信與通訊"
    ]

    assert "雷射次組件" in telecom


def test_v24_aaoi_translates_technology_and_manufacturing():
    display = _display("AAOI")[
        "display"
    ]

    assert "分子束磊晶（MBE）" in (
        display[
            "core_technologies"
        ]
    )

    assert (
        "金屬有機化學氣相沉積（MOCVD）"
        in display[
            "core_technologies"
        ]
    )

    manufacturing = display[
        "manufacturing"
    ]

    assert "垂直整合" in (
        manufacturing["model"]
    )

    assert "高度自動化" in (
        manufacturing["model"]
    )

    assert {
        "美國",
        "台灣",
        "中國",
    }.issubset(
        set(
            manufacturing[
                "locations"
            ]
        )
    )

    assert (
        manufacturing[
            "critical_assets"
        ][0][
            "asset"
        ]
        == "雷射晶片製造"
    )

    assert (
        manufacturing[
            "critical_assets"
        ][0][
            "location"
        ]
        == "Sugar Land, Texas"
    )


def test_v24_aaoi_customer_types_are_display_deduped():
    display = _display("AAOI")[
        "display"
    ]

    customers = set(
        display[
            "customer_types"
        ]
    )

    assert (
        "超大規模資料中心營運商"
        in customers
    )

    assert (
        "光收發模組製造商"
        in customers
    )

    assert (
        "大型網際網路資料中心營運商"
        not in customers
    )

    assert (
        "其他光收發模組製造商"
        not in customers
    )


def test_v24_aaoi_ai_strategy_and_financial_display():
    display = _display("AAOI")[
        "display"
    ]

    assert "800Gbps" in (
        display[
            "ai_exposure"
        ][
            "summary"
        ]
    )

    assert (
        "高速光網路"
        in display[
            "ai_exposure"
        ][
            "summary"
        ]
    )

    assert (
        display[
            "strategy_changes"
        ][0][
            "brand"
        ]
        == "Quantum Bandwidth"
    )

    financial = display[
        "financial_snapshot"
    ]

    assert (
        financial["revenue"]
        == "$455.7M"
    )

    assert (
        financial["gross_margin"]
        == "30.0%"
    )

    assert (
        financial["net_loss"]
        == "$38.2M"
    )

    assert (
        financial[
            "revenue_mix"
        ][
            "有線電視（CATV）"
        ]
        == "53.8%"
    )

    assert (
        financial[
            "revenue_mix"
        ][
            "雲端與資料中心"
        ]
        == "42.9%"
    )

    assert (
        financial[
            "customer_concentration"
        ][
            "Digicomm"
        ]
        == "53.1%"
    )

    assert (
        financial[
            "customer_concentration"
        ][
            "Microsoft"
        ]
        == "28.8%"
    )


def test_v24_preserves_v23_provenance_unchanged():
    profile = build_company_profile_v2(
        ROOT,
        symbol="AAOI",
    )

    row = (
        build_company_profile_display_zh_tw(
            ROOT,
            profile=profile,
        )
    )

    assert (
        row["value_provenance"]
        == profile[
            "value_provenance"
        ]
    )

    assert (
        row["evidence"]
        == profile["evidence"]
    )

    assert (
        row[
            "canonical_schema_version"
        ]
        == "axiom-company-profile.v2.3"
    )


def test_v24_nvda_uses_same_adapter():
    display = _display("NVDA")[
        "display"
    ]

    assert {
        "雲端與資料中心",
        "遊戲",
        "專業視覺化",
        "汽車",
    }.issubset(
        set(
            display["markets"]
        )
    )

    assert (
        display[
            "company_summary"
        ][
            "one_line_business"
        ]
    )