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


def test_translation_readiness_row_ready_for_complete_surface(monkeypatch):
    module = _load_script()

    profile = {
        "symbol": "TEST",
        "company_id": "company:test",
        "company_summary": {
            "one_line_business": "Example company"
        },
        "product_stack": ["Product A"],
        "market_products": {},
        "markets": ["Data Center"],
        "customer_types": [],
        "core_technologies": [],
        "ai_exposure": None,
        "demand_drivers": [],
        "strategy_changes": [],
    }

    monkeypatch.setattr(
        module,
        "_load_canonical_profile",
        lambda symbol: profile,
    )

    row = module._translation_readiness_row(
        "TEST"
    )

    assert row["status"] == "READY"
    assert row["canonical_handoff"] == "read_back_verified"
    assert row["canonical_product_count"] == 1
    assert row["translation_product_count"] == 1
    assert row["product_cardinality_match"] is True


def test_translation_readiness_row_reviews_empty_product_stack(monkeypatch):
    module = _load_script()

    profile = {
        "symbol": "TEST",
        "company_id": "company:test",
        "company_summary": {
            "one_line_business": "Example company"
        },
        "product_stack": [],
        "market_products": {},
        "markets": ["Data Center"],
        "customer_types": [],
        "core_technologies": [],
        "ai_exposure": None,
        "demand_drivers": [],
        "strategy_changes": [],
    }

    monkeypatch.setattr(
        module,
        "_load_canonical_profile",
        lambda symbol: profile,
    )

    row = module._translation_readiness_row(
        "TEST"
    )

    assert row["status"] == "REVIEW"
    assert "EMPTY_PRODUCT_STACK" in row["reasons"]


def test_translation_production_census_never_calls_openai(monkeypatch):
    module = _load_script()

    monkeypatch.setattr(
        module,
        "_canonical_index",
        lambda: {
            "symbol_to_file": {
                "AAA": "per-company/a.json",
                "BBB": "per-company/b.json",
            }
        },
    )

    rows = {
        "AAA": {
            "symbol": "AAA",
            "status": "READY",
            "reasons": [],
        },
        "BBB": {
            "symbol": "BBB",
            "status": "REVIEW",
            "reasons": [
                "EMPTY_PRODUCT_STACK",
            ],
        },
    }

    monkeypatch.setattr(
        module,
        "_translation_readiness_row",
        lambda symbol: rows[symbol],
    )

    def forbidden_openai(**kwargs):
        raise AssertionError(
            "translation census touched OpenAI"
        )

    monkeypatch.setattr(
        module,
        "_translate_with_openai",
        forbidden_openai,
    )

    census = module._translation_production_census()

    assert census["openai_used"] is False
    assert census["summary"] == {
        "total": 2,
        "ready": 1,
        "review": 1,
        "fail": 0,
        "ready_rate": 0.5,
        "usable_rate": 1.0,
    }
    assert census["reason_counts"] == {
        "EMPTY_PRODUCT_STACK": 1,
    }


def test_translation_plan_token_estimate_is_deterministic():
    module = _load_script()

    assert (
        module._estimate_input_tokens_from_characters(
            350
        )
        == 100
    )
    assert (
        module._estimate_input_tokens_from_characters(
            351
        )
        == 101
    )


def test_translation_plan_excludes_review_and_fail(monkeypatch):
    module = _load_script()

    census = {
        "canonical_company_count": 3,
        "summary": {
            "ready": 1,
        },
        "rows": [
            {
                "symbol": "AAA",
                "status": "READY",
                "reasons": [],
                "translation_product_count": 1,
                "canonical_handoff": "read_back_verified",
            },
            {
                "symbol": "BBB",
                "status": "REVIEW",
                "reasons": ["EMPTY_PRODUCT_STACK"],
                "translation_product_count": 0,
            },
            {
                "symbol": "CCC",
                "status": "FAIL",
                "reasons": ["CANONICAL_OR_HANDOFF_ERROR"],
                "translation_product_count": None,
            },
        ],
    }

    profile = {
        "symbol": "AAA",
        "company_id": "company:aaa",
        "company_summary": {
            "one_line_business": "Example"
        },
        "product_stack": ["Product A"],
        "market_products": {},
        "markets": ["Data Center"],
        "customer_types": [],
        "core_technologies": [],
        "ai_exposure": None,
        "demand_drivers": [],
        "strategy_changes": [],
    }

    monkeypatch.setattr(
        module,
        "_translation_production_census",
        lambda: census,
    )

    monkeypatch.setattr(
        module,
        "_translation_candidate_metadata_map",
        lambda: {},
    )

    monkeypatch.setattr(
        module,
        "_load_canonical_profile",
        lambda symbol: profile,
    )

    plan = (
        module._translation_production_plan()
    )

    assert plan["openai_used"] is False
    assert plan["planned_count"] == 1
    assert plan["excluded_count"] == 2
    assert plan["invariants"] == {
        "openai_used": False,
        "review_included": 0,
        "fail_included": 0,
        "product_mismatch": 0,
        "ready_equals_planned": True,
    }
    assert [
        row["symbol"]
        for row in plan["planned"]
    ] == ["AAA"]

    excluded = {
        row["symbol"]:
            row["translation_allowed"]
        for row in plan["excluded"]
    }

    assert excluded == {
        "BBB": False,
        "CCC": False,
    }


def test_translation_plan_priority_is_disjoint():
    module = _load_script()

    metadata = {
        "CORE": {
            "theme_id":
                "theme:artificial_intelligence"
        }
    }

    assert (
        module._translation_plan_priority(
            symbol="NVDA",
            metadata=metadata,
        )
        == (
            "P0",
            "major_tech",
        )
    )

    assert (
        module._translation_plan_priority(
            symbol="CORE",
            metadata=metadata,
        )
        == (
            "P1",
            "core_ai_tech",
        )
    )

    assert (
        module._translation_plan_priority(
            symbol="OTHER",
            metadata=metadata,
        )
        == (
            "P2",
            "strategic_remainder",
        )
    )


def test_translation_plan_never_calls_openai(monkeypatch):
    module = _load_script()

    census = {
        "canonical_company_count": 0,
        "summary": {
            "ready": 0,
        },
        "rows": [],
    }

    monkeypatch.setattr(
        module,
        "_translation_production_census",
        lambda: census,
    )

    monkeypatch.setattr(
        module,
        "_translation_candidate_metadata_map",
        lambda: {},
    )

    def forbidden_openai(**kwargs):
        raise AssertionError(
            "translation plan touched OpenAI"
        )

    monkeypatch.setattr(
        module,
        "_translate_with_openai",
        forbidden_openai,
    )

    plan = (
        module._translation_production_plan()
    )

    assert plan["openai_used"] is False
    assert plan["planned_count"] == 0


def test_translation_repair_prompt_preserves_array_cardinality_rule():
    module = _load_script()

    source = {
        "markets": [
            "Data Center and AI",
            "Automotive/Industrial",
        ]
    }

    prompt = module._build_translation_repair_prompt(
        symbol="TEST",
        source=source,
        validation_error=(
            "translation item-count mismatch at $.markets: "
            "source=2 translated=3"
        ),
        attempt=2,
    )

    assert "$.markets: array length=2" in prompt
    assert "只能對應一個輸出 item" in prompt
    assert "斜線" in prompt
    assert "and" in prompt


def test_openai_translation_retries_shape_mismatch_then_passes(
    monkeypatch,
    tmp_path,
):
    module = _load_script()

    monkeypatch.setattr(
        module,
        "OPENAI_CACHE_ROOT",
        tmp_path,
    )

    monkeypatch.setenv(
        "OPENAI_API_KEY",
        "test-key",
    )

    source = {
        "markets": [
            "Data Center and AI",
            "Automotive/Industrial",
        ]
    }

    calls = []

    class FakeClient:
        pass

    def fake_request(
        *,
        client,
        model,
        prompt,
    ):
        calls.append(prompt)

        if len(calls) == 1:
            return {
                "markets": [
                    "資料中心",
                    "人工智慧",
                    "汽車／工業",
                ]
            }

        return {
            "markets": [
                "資料中心與人工智慧",
                "汽車／工業",
            ]
        }

    class FakeOpenAI:
        def __new__(cls):
            return FakeClient()

    import types
    fake_module = types.SimpleNamespace(
        OpenAI=FakeOpenAI
    )

    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        fake_module,
    )

    monkeypatch.setattr(
        module,
        "_request_openai_translation",
        fake_request,
    )

    translated, result_source = (
        module._translate_with_openai(
            model="gpt-4.1-mini",
            symbol="TEST",
            source=source,
        )
    )

    assert len(calls) == 2
    assert translated["markets"] == [
        "資料中心與人工智慧",
        "汽車／工業",
    ]
    assert result_source == "API_REPAIR_2"


def test_translation_array_lock_roundtrip_preserves_cardinality():
    module = _load_script()

    source = {
        "markets": [
            "Data Center and AI",
            "Automotive/Industrial",
        ],
        "nested": {
            "items": [
                {"name": "A"},
                {"name": "B"},
            ]
        },
    }

    locked = module._lock_translation_arrays(
        source
    )

    assert locked["markets"] == {
        "__axiom_array__": {
            "0": "Data Center and AI",
            "1": "Automotive/Industrial",
        }
    }

    restored = (
        module._unlock_translation_arrays(
            locked
        )
    )

    assert restored == source
    assert len(restored["markets"]) == 2
    assert len(
        restored["nested"]["items"]
    ) == 2


def test_locked_translation_rejects_changed_array_keys():
    module = _load_script()

    broken = {
        "__axiom_array__": {
            "0": "A",
            "1": "B",
            "2": "C",
        }
    }

    restored = (
        module._unlock_translation_arrays(
            broken
        )
    )

    assert restored == [
        "A",
        "B",
        "C",
    ]


def test_locked_translation_prompt_contains_array_guard():
    module = _load_script()

    prompt = (
        module._build_locked_translation_prompt(
            symbol="TEST",
            source={
                "markets": [
                    "Data Center and AI",
                    "Automotive/Industrial",
                ]
            },
        )
    )

    assert "__axiom_array__" in prompt
    assert '"0":"Data Center and AI"' in prompt
    assert '"1":"Automotive/Industrial"' in prompt
    assert "絕對不可翻譯或變更" in prompt