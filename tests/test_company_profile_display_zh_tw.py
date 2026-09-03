import pytest
import json
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
                "theme:ai_infrastructure"
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
                "markets": {
                    "__axiom_array__": {
                        "0": "資料中心",
                        "1": "人工智慧",
                        "2": "汽車／工業",
                    }
                }
            }

        return {
            "markets": {
                "__axiom_array__": {
                    "0": "資料中心與人工智慧",
                    "1": "汽車／工業",
                }
            }
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
    assert result_source == "API_LOCKED_REPAIR_2"


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


def test_v2660_summary_selector_rejects_aapl_ip_personnel_sentence():
    module = _load_profile_script()

    text = (
        "Although the Company believes the ownership of such intellectual "
        "property rights is an important factor in differentiating its business "
        "and that its success does depend in part on such ownership, the Company "
        "relies primarily on the innovative skills, technical competence and "
        "marketing abilities of its personnel. "
        "The Company designs, manufactures and markets smartphones, personal "
        "computers, tablets, wearables and accessories, and sells related services."
    )

    result = module._select_company_summary(
        text
    )

    assert result["selected"].startswith(
        "The Company designs, manufactures and markets"
    )
    assert "IP_OR_PERSONNEL" not in result["reasons"]


def test_v2660_summary_selector_rejects_segment_only_summary():
    module = _load_profile_script()

    text = (
        "Applied Global Services Our AGS segment provides services, spares and "
        "factory automation software to customer fabrication plants globally. "
        "Applied Materials is a leader in materials engineering solutions used "
        "to produce virtually every new chip and advanced display in the world."
    )

    result = module._select_company_summary(
        text
    )

    assert result["selected"].startswith(
        "Applied Materials is a leader"
    )


def test_v2660_summary_selector_rejects_founders_letter():
    module = _load_profile_script()

    text = (
        "As our founders Larry and Sergey wrote in the original founders' letter, "
        "\"Google is not a conventional company.\" "
        "Google offers products and platforms including Search, YouTube, Android, "
        "Chrome, Maps, Play, devices and Google Cloud."
    )

    result = module._select_company_summary(
        text
    )

    assert result["selected"].startswith(
        "Google offers products and platforms"
    )


def test_v2660_summary_selector_rejects_incorporation_boilerplate():
    module = _load_profile_script()

    text = (
        "Business Incorporated in 1980, Lam Research Corporation is a Delaware "
        "corporation, headquartered in Fremont, California. "
        "Lam Research supplies wafer fabrication equipment and services to the "
        "semiconductor industry."
    )

    result = module._select_company_summary(
        text
    )

    assert result["selected"].startswith(
        "Lam Research supplies wafer fabrication equipment"
    )


def test_v2660_summary_selector_rejects_competitive_advantage():
    module = _load_profile_script()

    text = (
        "We believe that our scale and capacity, particularly for advanced "
        "technologies, is a major competitive advantage. "
        "TSMC manufactures semiconductors for customers using a broad portfolio "
        "of advanced and specialty process technologies."
    )

    result = module._select_company_summary(
        text
    )

    assert result["selected"].startswith(
        "TSMC manufactures semiconductors"
    )


def test_v2660_summary_selector_strips_section_heading():
    module = _load_profile_script()

    value = (
        "BUSINESS Company Overview, Strategy and Mission "
        "Analog Devices, Inc. is a global semiconductor leader dedicated to "
        "solving customers' most complex engineering challenges."
    )

    clean = module._strip_summary_heading(
        value
    )

    assert clean.startswith(
        "Analog Devices, Inc. is a global semiconductor leader"
    )


def test_v2660_summary_selector_downranks_strategy_only_anet_sentence():
    module = _load_profile_script()

    text = (
        "Our Centers of Data strategy is a fundamental pivot from legacy "
        "networking approaches to a unified data-driven approach. "
        "Arista Networks is an industry leader in data-driven, client-to-cloud "
        "networking for large data center, campus and routing environments."
    )

    result = module._select_company_summary(
        text
    )

    assert result["selected"].startswith(
        "Arista Networks is an industry leader"
    )


def test_v2660_summary_selector_integration_uses_core_helpers(monkeypatch):
    module = _load_profile_script()

    report = {
        "_canonical_profiles": [
            {
                "symbol": "TEST",
                "company_id": "company:test",
                "company_summary": {
                    "one_line_business": "Bad legacy summary."
                },
                "field_evidence": {},
                "value_provenance": {},
            }
        ]
    }

    monkeypatch.setattr(
        module,
        "_core_load_business_evidence",
        lambda root, company_id: [
            {
                "business_evidence_id": "e1",
                "form": "10-K",
                "accession_number": "1",
                "filing_date": "2025-01-01",
                "section_type": "item_1_business",
                "document_url": None,
                "text_sha256": "x",
                "text": (
                    "TEST Corporation provides semiconductor products "
                    "and software solutions to data center customers."
                ),
            }
        ],
    )

    monkeypatch.setattr(
        module,
        "_core_latest_business_evidence",
        lambda rows, symbol: rows[0],
    )

    monkeypatch.setattr(
        module,
        "_core_clean_text",
        lambda text: text,
    )

    monkeypatch.setattr(
        module,
        "_core_build_value_provenance",
        lambda **kwargs: {
            "company_summary.one_line_business": {
                "value": kwargs["profile"]["company_summary"][
                    "one_line_business"
                ],
                "evidence": None,
            }
        },
    )

    rows = module._apply_company_summary_semantic_selector(
        report
    )

    assert rows[0]["status"] == "REPLACE"
    assert rows[0]["selected_summary"].startswith(
        "TEST Corporation provides semiconductor products"
    )
    assert (
        report["_canonical_profiles"][0]["company_summary"][
            "one_line_business"
        ]
        == rows[0]["selected_summary"]
    )


def test_v2661_challenger_keeps_good_vrt_summary():
    module = _load_profile_script()

    existing = (
        "Vertiv is a global leader in critical digital infrastructure "
        "for applications in data centers, communication networks, and "
        "commercial and industrial environments."
    )

    text = (
        "Over the next decade, Emerson Network Power expanded through "
        "acquisitions of Avansys, Marconi and Avocent. "
        + existing
    )

    result = module._challenge_company_summary(
        existing_summary=existing,
        text=text,
    )

    assert result["decision"] == "KEEP"
    assert result["selected_summary"] == existing


def test_v2661_challenger_replaces_founders_letter_with_google_business_model():
    module = _load_profile_script()

    existing = (
        "As our founders Larry and Sergey wrote in the original founders' "
        'letter, "Google is not a conventional company.'
    )

    text = (
        existing
        + " At the foundation of our full-stack approach is our "
        "AI-optimized infrastructure — a key differentiator enabling us "
        "to power our own products, such as Search and YouTube, and "
        "support the services we provide to our Google Cloud customers."
    )

    result = module._challenge_company_summary(
        existing_summary=existing,
        text=text,
    )

    assert result["decision"] == "REPLACE"
    assert "AI-optimized infrastructure" in result["selected_summary"]


def test_v2661_challenger_cleans_adi_heading_without_unnecessary_replace():
    module = _load_profile_script()

    existing = (
        "BUSINESS Company Overview, Strategy and Mission "
        "Analog Devices, Inc. is a global semiconductor leader dedicated "
        "to solving customers' most complex engineering challenges."
    )

    text = (
        existing
        + " These include devices that shape signals for transmission."
    )

    result = module._challenge_company_summary(
        existing_summary=existing,
        text=text,
    )

    assert result["decision"] in {"CLEAN", "KEEP"}
    assert result["selected_summary"].startswith(
        "Analog Devices, Inc. is a global semiconductor leader"
    )


def test_v2661_challenger_keeps_good_cadence_identity_over_pillar_detail():
    module = _load_profile_script()

    existing = (
        "Cadence is a global technology leader that develops computational, "
        "AI-driven software, accelerated hardware, and silicon intellectual "
        "property products and solutions."
    )

    text = (
        existing
        + " Design Excellence: This pillar leverages our core expertise in "
        "AI-driven computational software and accelerated computing to deliver "
        "electronic design and verification products."
    )

    result = module._challenge_company_summary(
        existing_summary=existing,
        text=text,
    )

    assert result["decision"] == "KEEP"
    assert result["selected_summary"] == existing


def test_v2661_challenger_replaces_incorporation_with_lam_identity():
    module = _load_profile_script()

    existing = (
        "Business Incorporated in 1980, Lam Research Corporation is a "
        "Delaware corporation, headquartered in Fremont, California."
    )

    text = (
        existing
        + " We are a global supplier of innovative wafer fabrication "
        "equipment and services to the semiconductor industry."
    )

    result = module._challenge_company_summary(
        existing_summary=existing,
        text=text,
    )

    assert result["decision"] == "REPLACE"
    assert result["selected_summary"].startswith(
        "We are a global supplier of innovative wafer fabrication equipment"
    )


def test_v2661a_ip_product_language_does_not_make_good_summary_hard_bad():
    module = _load_profile_script()
    result = module._summary_quality_score(
        "Cadence is a global technology leader that develops computational, "
        "AI-driven software, accelerated hardware, and silicon intellectual "
        "property products and solutions."
    )
    assert "IP_OR_PERSONNEL" in result["reasons"]
    assert result["hard_bad"] is False


def test_v2661a_detail_candidate_cannot_auto_replace_bad_incumbent():
    module = _load_profile_script()
    existing = (
        "We believe that our scale and capacity, particularly for advanced "
        "technologies, is a major competitive advantage."
    )
    text = (
        existing
        + " Furthermore, for both premium and mainstream product applications, "
        "we offer specialty technologies including RF, sensors, display chips, "
        "and advanced packaging services."
    )
    result = module._challenge_company_summary(
        existing_summary=existing,
        text=text,
    )
    assert result["decision"] == "REVIEW"
    assert result["candidate_eligible"] is False
    assert "PRODUCT_OR_APPLICATION_DETAIL" in result["candidate_blockers"]


def test_v2661a_customer_description_cannot_replace_incorporation_boilerplate():
    module = _load_profile_script()
    existing = (
        "Business Incorporated in 1980, Lam Research Corporation is a Delaware "
        "corporation, headquartered in Fremont, California."
    )
    text = (
        existing
        + " Our customer base includes leading semiconductor memory, foundry, "
        "and integrated device manufacturers that make DRAM and logic devices."
    )
    result = module._challenge_company_summary(
        existing_summary=existing,
        text=text,
    )
    assert result["decision"] == "REVIEW"
    assert result["candidate_eligible"] is False
    assert "CUSTOMER_DESCRIPTION" in result["candidate_blockers"]


def test_v2661b_good_existing_protects_adi_from_filing_prose():
    module = _load_profile_script()

    existing = (
        "BUSINESS Company Overview, Strategy and Mission "
        "Analog Devices, Inc. is a global semiconductor leader dedicated "
        "to solving customers' most complex engineering challenges."
    )

    text = (
        existing
        + " These include devices that shape the signal for transmission "
        "over the medium or reconstruct the received signal after transmission "
        "to recover the intended signal integrity. "
        "•Software, Digital Platforms and Artificial Intelligence—As part of "
        "our evolution from a component supplier to a full-system and solutions "
        "provider, we introduced CodeFusion Studio 2.0."
    )

    result = module._challenge_company_summary(
        existing_summary=existing,
        text=text,
    )

    assert result["decision"] in {"CLEAN", "KEEP"}
    assert result["selected_summary"].startswith(
        "Analog Devices, Inc. is a global semiconductor leader"
    )
    assert result["good_existing"] is True


def test_v2661b_eligibility_diagnostics_block_customer_description():
    module = _load_profile_script()

    candidate_eval = module._summary_quality_score(
        (
            "Our customer base includes leading semiconductor memory, "
            "foundry, and integrated device manufacturers."
        ),
        position=0,
    )

    result = module._candidate_summary_eligibility(
        candidate_eval
    )

    assert result["eligible"] is False
    assert "CUSTOMER_DESCRIPTION" in result["blockers"]


def test_v2661b_eligibility_diagnostics_block_product_detail():
    module = _load_profile_script()

    candidate_eval = module._summary_quality_score(
        (
            "Furthermore, for both premium and mainstream product "
            "applications, we offer specialty technologies including RF, "
            "sensors, display chips and advanced packaging services."
        ),
        position=0,
    )

    result = module._candidate_summary_eligibility(
        candidate_eval
    )

    assert result["eligible"] is False
    assert "PRODUCT_OR_APPLICATION_DETAIL" in result["blockers"]


def test_v2661b_vrt_keep_still_holds():
    module = _load_profile_script()

    existing = (
        "Vertiv is a global leader in critical digital infrastructure "
        "for applications in data centers, communication networks, and "
        "commercial and industrial environments."
    )

    text = (
        "Over the next decade, Emerson Network Power expanded through "
        "acquisitions of Avansys, Marconi and Avocent. "
        + existing
    )

    result = module._challenge_company_summary(
        existing_summary=existing,
        text=text,
    )

    assert result["decision"] == "KEEP"
    assert result["selected_summary"] == existing


def test_v2661c_selector_function_restored_and_callable():
    module = _load_profile_script()

    assert hasattr(
        module,
        "_select_company_summary",
    )

    result = module._select_company_summary(
        (
            "As our founders Larry and Sergey wrote in the original "
            "founders' letter, \"Google is not a conventional company.\" "
            "Google offers products and platforms including Search, "
            "YouTube, Android, Chrome, Maps, Play, devices and Google Cloud."
        )
    )

    assert result["selected"] is not None
    assert result["selected"].startswith(
        "Google offers products and platforms"
    )


def test_v2661c_challenger_still_exposes_eligibility_diagnostics():
    module = _load_profile_script()

    existing = (
        "We believe that our scale and capacity, particularly for advanced "
        "technologies, is a major competitive advantage."
    )

    text = (
        existing
        + " Furthermore, for both premium and mainstream product applications, "
        "we offer specialty technologies including RF, sensors, display chips, "
        "and advanced packaging services."
    )

    result = module._challenge_company_summary(
        existing_summary=existing,
        text=text,
    )

    assert "candidate_eligible" in result
    assert "candidate_eligibility_reason" in result
    assert "candidate_blockers" in result


def test_v2662_sanitizer_drops_financial_note_pollution():
    module = _load_profile_script()

    result = module._sanitize_product_stack_values(
        [
            "broadband switches suitable for radio",
            "hearing health) See Note 4",
            "Geographic Information",
            (
                "of the Notes to Consolidated Financial Statements "
                "contained in Part II"
            ),
            "other high-performance sensors",
        ]
    )

    assert result["kept"] == [
        "broadband switches suitable for radio",
        "other high-performance sensors",
    ]

    reasons = {
        row["reason"]
        for row in result["removed"]
    }

    assert "FINANCIAL_STATEMENT_NOTE" in reasons
    assert "NON_PRODUCT_DOCUMENT_OR_FRAGMENT" in reasons


def test_v2662_sanitizer_drops_hr_facility_pollution():
    module = _load_profile_script()

    result = module._sanitize_product_stack_values(
        [
            "PCIe Gen6 SSDs",
            "health clinics at certain Micron sites",
            "DDR5",
        ]
    )

    assert result["kept"] == [
        "PCIe Gen6 SSDs",
        "DDR5",
    ]
    assert result["removed"][0]["reason"] == "HR_OR_FACILITY_TEXT"


def test_v2662_sanitizer_drops_form_10k():
    module = _load_profile_script()

    result = module._sanitize_product_stack_values(
        [
            "Form 10-K",
            "SuperDoctor 5",
        ]
    )

    assert result["kept"] == [
        "SuperDoctor 5",
    ]


def test_v2662_sanitizer_drops_dell_truncated_fragments():
    module = _load_profile_script()

    result = module._sanitize_product_stack_values(
        [
            (
                "modern and traditional storage solutions "
                "that span primary"
            ),
            "software-defined",
        ]
    )

    assert result["kept"] == []
    assert {
        row["reason"]
        for row in result["removed"]
    } == {
        "TRUNCATED_FRAGMENT",
        "NON_PRODUCT_DOCUMENT_OR_FRAGMENT",
    }


def test_v2662_sanitizer_preserves_named_products():
    module = _load_profile_script()

    products = [
        "OCTEON DPUs",
        "PCIe and CXL Switches",
        "Allegro X",
        "OrCAD X platforms for PCB",
        "Google Gemini",
        "Google Maps",
        "low/medium voltage switchgear",
        "critical digital infrastructure software",
    ]

    result = module._sanitize_product_stack_values(
        products
    )

    assert result["kept"] == products
    assert result["removed"] == []


def test_v2662_safe_upsert_sanitizes_only_production_copy(
    monkeypatch,
    tmp_path,
):
    module = _load_profile_script()

    monkeypatch.setattr(
        module,
        "CANONICAL_ROOT",
        tmp_path,
    )

    profile = {
        "symbol": "TEST",
        "company_id": "company:test",
        "product_stack": [
            "Form 10-K",
            "OCTEON DPUs",
        ],
    }

    original = json.loads(
        json.dumps(
            profile
        )
    )

    result = module._safe_upsert_canonical_profiles(
        [
            profile
        ]
    )

    assert profile == original
    assert result["written_count"] == 1
    assert result["sanitizer_removed_item_count"] == 1

    rel = (
        result[
            "written"
        ][0][
            "relative_path"
        ]
    )

    written = json.loads(
        (
            tmp_path
            / rel
        ).read_text(
            encoding="utf-8"
        )
    )

    assert written["product_stack"] == [
        "OCTEON DPUs",
    ]
    assert (
        written[
            "product_stack_sanitizer"
        ][
            "version"
        ]
        == "v2.6.6.2a"
    )


def test_v2662_sanitizer_refuses_empty_production_stack(
    monkeypatch,
    tmp_path,
):
    module = _load_profile_script()

    monkeypatch.setattr(
        module,
        "CANONICAL_ROOT",
        tmp_path,
    )

    with pytest.raises(
        ValueError,
        match="refuses empty production product_stack",
    ):
        module._safe_upsert_canonical_profiles(
            [
                {
                    "symbol": "TEST",
                    "company_id": "company:test",
                    "product_stack": [
                        "Form 10-K",
                        "Geographic Information",
                    ],
                }
            ]
        )


def test_v2662a_preserves_valid_covering_product_family():
    module = _load_profile_script()

    products = [
        (
            "a broad portfolio of high-performance RF and microwave ICs "
            "covering the entire RF signal chain"
        ),
        "microwave ICs covering the entire RF signal chain",
    ]

    result = module._sanitize_product_stack_values(
        products
    )

    assert result["kept"] == products
    assert result["removed"] == []


def test_v2662a_preserves_named_product_after_such_as():
    module = _load_profile_script()

    result = module._sanitize_product_stack_values(
        [
            "such as YouTube TV",
            "YouTube Music",
        ]
    )

    assert result["kept"] == [
        "such as YouTube TV",
        "YouTube Music",
    ]


def test_v2662a_drops_high_precision_known_pollution():
    module = _load_profile_script()

    result = module._sanitize_product_stack_values(
        [
            "Authorization of Chemicals SVHC Substances Directive",
            "revenue from licensing our software",
            "Hong Kong",
            "those in the Middle East",
            "strong third-party software",
            "consumer electronics",
            "Corporate Controller",
            "OCTEON DPUs",
        ]
    )

    assert result["kept"] == [
        "OCTEON DPUs",
    ]

    reasons = {
        row["reason"]
        for row in result["removed"]
    }

    assert "REGULATORY_OR_COMPLIANCE_TEXT" in reasons
    assert "REVENUE_OR_LICENSING_PROSE" in reasons
    assert "GEOGRAPHY_TEXT" in reasons
    assert "GENERIC_NON_PRODUCT_TEXT" in reasons


def test_v2662a_diagnostics_marks_empty_stack_blocked():
    module = _load_profile_script()

    payload = module._product_sanitizer_diagnostics(
        [
            {
                "symbol": "DELL",
                "product_stack": [
                    (
                        "modern and traditional storage solutions "
                        "that span primary"
                    ),
                    "software-defined",
                ],
            }
        ]
    )

    assert payload["blocked_empty_company_count"] == 1
    assert payload["rows"][0]["status"] == (
        "BLOCKED_EMPTY_AFTER_SANITIZE"
    )
    assert payload["rows"][0][
        "blocked_empty_after_sanitize"
    ] is True