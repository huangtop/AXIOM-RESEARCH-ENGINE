from pathlib import Path
import importlib.util

from axiom_engine.company_profile_v2 import build_company_profile_v2
from axiom_engine.company_profile_v2.display_zh_tw import (
    build_company_profile_display_zh_tw,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_company_profile_display_zh_tw.py"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "company_profile_translation_script",
        SCRIPT,
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