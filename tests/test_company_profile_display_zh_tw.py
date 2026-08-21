from pathlib import Path
import importlib.util

from axiom_engine.company_profile_v2 import build_company_profile_v2
from axiom_engine.company_profile_v2.display_zh_tw import (
    build_company_profile_display_zh_tw,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_company_profile_display_zh_tw.py"
PROFILE_SCRIPT = ROOT / "scripts/build_company_profiles_v2.py"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "company_profile_translation_script",
        SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_profile_script():
    spec = importlib.util.spec_from_file_location(
        "company_profile_v2658_script",
        PROFILE_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_v24_preserves_provenance_unchanged():
    profile = build_company_profile_v2(ROOT, symbol="NVDA")
    row = build_company_profile_display_zh_tw(ROOT, profile=profile)
    assert row["value_provenance"] == profile["value_provenance"]
    assert row["evidence"] == profile["evidence"]
    assert row["canonical_schema_version"] == "axiom-company-profile.v2.3"


def test_translation_default_model_is_gpt_41_mini():
    module = _load_script()
    assert module.DEFAULT_MODEL == "gpt-4.1-mini"


def test_translation_surface_includes_semantic_fields():
    module = _load_script()
    profile = {
        "company_summary": {"one_line_business": "Example company"},
        "product_stack": ["Aries PCIe/CXL Smart DSP Retimers", "COSMOS software suite"],
        "market_products": {"data_center": ["Aries PCIe/CXL Smart DSP Retimers"]},
        "markets": ["Data Center"],
        "customer_types": ["hyperscalers"],
        "core_technologies": ["PCIe", "CXL"],
        "ai_exposure": {"summary": "AI infrastructure connectivity"},
        "demand_drivers": ["AI infrastructure"],
        "strategy_changes": [{"summary": "Expanded connectivity portfolio"}],
    }
    surface = module._extract_translation_surface(profile)
    assert surface["product_stack"] == profile["product_stack"]
    assert surface["core_technologies"] == profile["core_technologies"]
    assert surface["ai_exposure"] == profile["ai_exposure"]
    assert surface["demand_drivers"] == profile["demand_drivers"]
    assert surface["strategy_changes"] == profile["strategy_changes"]


def test_translation_validator_rejects_dropped_product():
    module = _load_script()
    source = {"product_stack": ["Aries", "Leo"]}
    translated = {"product_stack": ["Aries"]}
    try:
        module._validate_translation_shape(source=source, translated=translated)
    except ValueError as exc:
        assert "item-count mismatch" in str(exc)
    else:
        raise AssertionError("validator accepted a dropped product")


def test_translation_validator_rejects_added_key():
    module = _load_script()
    source = {"company_summary": "Example", "product_stack": ["EPYC"]}
    translated = {
        "company_summary": "範例",
        "product_stack": ["EPYC"],
        "invented_products": ["Not allowed"],
    }
    try:
        module._validate_translation_shape(source=source, translated=translated)
    except ValueError as exc:
        assert "keys mismatch" in str(exc)
    else:
        raise AssertionError("validator accepted an invented key")


def test_translation_validator_accepts_exact_shape():
    module = _load_script()
    source = {
        "company_summary": "Example",
        "product_stack": ["EPYC", "Instinct MI350"],
        "market_products": {},
        "markets": [],
        "customer_types": ["cloud providers"],
        "core_technologies": ["CDNA"],
        "ai_exposure": None,
        "demand_drivers": ["AI"],
        "strategy_changes": [],
    }
    translated = {
        "company_summary": "範例",
        "product_stack": ["EPYC", "Instinct MI350"],
        "market_products": {},
        "markets": [],
        "customer_types": ["雲端服務供應商"],
        "core_technologies": ["CDNA"],
        "ai_exposure": None,
        "demand_drivers": ["人工智慧"],
        "strategy_changes": [],
    }
    module._validate_translation_shape(source=source, translated=translated)


def _row(symbol, products):
    return {
        "symbol": symbol,
        "product_stack_full": products,
        "product_stack_preview": products[:40],
        "generic_product_count": 0,
    }


def test_v2658_clean_named_products_are_promotable():
    module = _load_profile_script()
    gate = module._promotion_quality_gate(
        _row(
            "ALAB",
            [
                "Aries PCIe/CXL Smart DSP Retimers",
                "Leo CXL Memory Connectivity Controllers",
                "Scorpio Smart Fabric Switches",
                "COSMOS software suite",
            ],
        )
    )
    assert gate["status"] == "PROMOTE"
    assert gate["issue_types"] == []


def test_v2658_nvda_style_organization_and_prose_block_promotion():
    module = _load_profile_script()
    gate = module._promotion_quality_gate(
        _row(
            "NVDA",
            [
                "H100",
                "GB200 NVL72",
                "Arista Networks",
                "Cisco Systems",
                "any China-specific product designed to comply with U.S",
            ],
        )
    )
    assert gate["status"] == "REVIEW"
    assert "PROMOTION_ORGANIZATION_NAME" in gate["issue_types"]
    assert "PROMOTION_NON_PRODUCT_CLAUSE" in gate["issue_types"]


def test_v2658_amd_style_non_product_clauses_block_promotion():
    module = _load_profile_script()
    gate = module._promotion_quality_gate(
        _row(
            "AMD",
            [
                "AMD EPYC Series processors",
                "AMD Instinct MI350 series",
                "are based on AMD CDNA architecture",
                "functionality of software design tools",
                "completeness of applicable software solutions",
            ],
        )
    )
    assert gate["status"] == "REVIEW"
    assert "PROMOTION_NON_PRODUCT_CLAUSE" in gate["issue_types"]


def test_v2658_avgo_embedded_filing_text_blocks_promotion():
    module = _load_profile_script()
    gate = module._promotion_quality_gate(
        _row(
            "AVGO",
            [
                "Ethernet NICs",
                "PCIe Switches",
                (
                    "inductive charging devices. "
                    "•RF Semiconductor Devices: Our devices selectively filter"
                ),
            ],
        )
    )
    assert gate["status"] == "REVIEW"
    assert (
        "PROMOTION_EMBEDDED_FILING_TEXT"
        in gate["issue_types"]
    )


def test_v2658_patent_text_blocks_promotion():
    module = _load_profile_script()
    gate = module._promotion_quality_gate(
        _row(
            "AXTI",
            [
                "photonic ICs (PICs)",
                (
                    "15 patents issued to ChaoYang XinMei "
                    "High Purity Semiconductor Materials Co"
                ),
            ],
        )
    )
    assert gate["status"] == "REVIEW"
    assert (
        "PROMOTION_LEGAL_OR_PATENT_TEXT"
        in gate["issue_types"]
    )


def test_v2658_empty_product_stack_fails_promotion():
    module = _load_profile_script()
    gate = module._promotion_quality_gate(
        _row(
            "PLTR",
            [],
        )
    )
    assert gate["status"] == "FAIL"
    assert "EMPTY_PRODUCT_STACK" in gate["issue_types"]