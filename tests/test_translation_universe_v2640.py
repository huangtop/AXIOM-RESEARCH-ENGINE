from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "census_translation_universe_v2640.py"
)

spec = importlib.util.spec_from_file_location("census_v2640", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def _write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _overview(
    symbol,
    company_id,
    *,
    theme=None,
    category="software_and_data_services",
    locked=True,
    source="curated_core_override",
):
    row = {
        "ticker": symbol,
        "company_id": company_id,
        "display_name": symbol,
        "status": "classified" if theme else "unclassified",
        "primary_business": {
            "status": "verified" if locked else "pending",
            "classification_source": (
                "SEC_SIC+SEC_ITEM1_OFFERING_EVIDENCE"
            ),
            "category": {"id": category},
        },
        "primary_business_lock": {
            "status": "locked" if locked else "pending"
        },
    }

    if theme:
        row.update(
            {
                "thematic_classification": {"status": "classified"},
                "classification_source": source,
                "classification_lock": {
                    "status": "locked",
                    "update_mode": "manual_override_only",
                },
                "evidence": [
                    {
                        "business_evidence_id": (
                            f"evidence:{symbol}"
                        )
                    }
                ],
                "path": {
                    "theme": {
                        "id": theme,
                        "name": theme,
                    },
                    "sector": {
                        "id": "sector:test",
                        "name": "Test",
                    },
                },
            }
        )

    return row


def _fixture(tmp_path: Path, rows, census_records=None):
    mapping = {}

    for row in rows:
        filename = f"{row['ticker']}.json"
        mapping[row["ticker"]] = filename
        _write(
            tmp_path
            / "data/generated/company_overview/per-company"
            / filename,
            row,
        )

    _write(
        tmp_path / "data/generated/company_overview/index.json",
        {"ticker_to_file": mapping},
    )

    if census_records is not None:
        _write(
            tmp_path
            / "data/generated/company_profile_v2/full_market_census.json",
            {"records": census_records},
        )


def _semantic_profile(
    summary=(
        "A company provides advanced systems and services "
        "to enterprise markets."
    ),
    offerings=None,
    markets=None,
    customers=None,
):
    return {
        "company_summary": {
            "one_line_business": summary,
        },
        "product_stack": (
            offerings
            if offerings is not None
            else ["Compute systems"]
        ),
        "market_products": {},
        "markets": (
            markets
            if markets is not None
            else ["Data Center"]
        ),
        "customer_types": (
            customers
            if customers is not None
            else ["OEMs"]
        ),
    }


def _with_builder(builder):
    original = mod._build_profile_for_audit
    mod._build_profile_for_audit = builder
    return original


def test_reuses_existing_production_ready_profile(tmp_path):
    _fixture(
        tmp_path,
        [_overview("NVDA", "c1", theme="theme:ai_infrastructure")],
        [
            {
                "symbol": "NVDA",
                "company_id": "c1",
                "production_ready": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    assert report["summary"]["reuse_translate_count"] == 1
    assert report["records"][0]["recommended_action"] == "REUSE_TRANSLATE"


def test_existing_nonready_profile_is_repair_not_rebuild(tmp_path):
    _fixture(
        tmp_path,
        [_overview("MU", "c2", theme="theme:advanced_semiconductors")],
        [
            {
                "symbol": "MU",
                "company_id": "c2",
                "production_ready": False,
                "generated": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    assert report["records"][0]["recommended_action"] == "PROFILE_REPAIR"


def test_missing_profile_is_new_build(tmp_path):
    _fixture(
        tmp_path,
        [_overview("RKLB", "c3", theme="theme:space_economy")],
        [],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    assert report["records"][0]["recommended_action"] == "NEW_PROFILE_BUILD"


def test_primary_business_candidate_requires_classification_review(
    tmp_path,
):
    _fixture(
        tmp_path,
        [
            _overview(
                "CHIP",
                "c4",
                category=(
                    "semiconductors_and_electronic_components"
                ),
            )
        ],
        [
            {
                "symbol": "CHIP",
                "company_id": "c4",
                "production_ready": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    row = report["records"][0]
    assert row["match_basis"] == "locked_primary_business_candidate"
    assert row["recommended_action"] == "CLASSIFICATION_REVIEW"
    assert row["translation_eligible"] is True


def test_pending_company_does_not_enter_strategic_universe(tmp_path):
    _fixture(
        tmp_path,
        [
            _overview(
                "PEND",
                "c5",
                theme="theme:ai_infrastructure",
                locked=False,
            )
        ],
        [],
    )

    report = mod.build_report(tmp_path)
    assert report["summary"]["strategic_company_count"] == 0
    assert report["summary"]["primary_business_pending_count"] == 1


def test_non_strategic_company_is_skipped_without_destroying_profile(
    tmp_path,
):
    _fixture(
        tmp_path,
        [_overview("BANK", "c6", category="commercial_banking")],
        [
            {
                "symbol": "BANK",
                "company_id": "c6",
                "production_ready": True,
            }
        ],
    )

    report = mod.build_report(tmp_path)
    assert report["summary"]["strategic_company_count"] == 0


def test_multiple_themes_do_not_double_count_company(tmp_path):
    _fixture(
        tmp_path,
        [
            _overview(
                "AVGO",
                "c7",
                theme="theme:ai_infrastructure",
                category=(
                    "semiconductors_and_electronic_components"
                ),
            )
        ],
        [
            {
                "symbol": "AVGO",
                "company_id": "c7",
                "production_ready": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    assert report["summary"]["strategic_company_count"] == 1
    assert len(report["records"]) == 1


def test_current_index_marks_profile_existing(tmp_path):
    _fixture(
        tmp_path,
        [
            _overview(
                "QCOM",
                "c8",
                theme="theme:advanced_communications",
            )
        ],
        [],
    )

    _write(
        tmp_path / "data/generated/company_profile_v2/index.json",
        {
            "symbol_to_file": {
                "QCOM": "per-company/qcom.json"
            }
        },
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    row = report["records"][0]
    assert row["profile_generated"] is True
    assert row["recommended_action"] == "PROFILE_REPAIR"


def test_v2640_recovers_profile_ready_from_historical_translation_census(
    tmp_path,
):
    _fixture(
        tmp_path,
        [_overview("NVDA", "c9", theme="theme:ai_infrastructure")],
        None,
    )

    _write(
        tmp_path
        / "data/generated/company_profile_v2/"
        "translation_universe_census_v2640.json",
        {
            "records": [
                {
                    "ticker": "NVDA",
                    "company_id": "c9",
                    "profile_production_ready": True,
                }
            ]
        },
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    row = report["records"][0]
    assert row["previous_production_ready"] is True
    assert row["recommended_action"] == "REUSE_TRANSLATE"


def test_v2640_historical_translation_census_does_not_invent_missing_members(
    tmp_path,
):
    _fixture(
        tmp_path,
        [_overview("RKLB", "c10", theme="theme:space_economy")],
        None,
    )

    _write(
        tmp_path
        / "data/generated/company_profile_v2/"
        "translation_universe_census_v2640.json",
        {
            "summary": {
                "profile_ready_symbol_count": 1809
            },
            "records": [],
        },
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    row = report["records"][0]
    assert row["previous_production_ready"] is False
    assert row["recommended_action"] == "NEW_PROFILE_BUILD"


def test_v2640_accepts_locked_evidence_backed_legacy_thematic_without_source(
    tmp_path,
):
    row = _overview(
        "LEGACY",
        "c11",
        theme="theme:ai_infrastructure",
        source="",
    )

    _fixture(
        tmp_path,
        [row],
        [
            {
                "symbol": "LEGACY",
                "company_id": "c11",
                "production_ready": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    result = report["records"][0]
    assert result["classification_authority"] is True
    assert (
        result["classification_gate_reason"]
        == "legacy_locked_evidence_backed"
    )
    assert result["translation_eligible"] is True


def test_v2640_rejects_unapproved_explicit_classification_source(
    tmp_path,
):
    row = _overview(
        "RAW",
        "c12",
        theme="theme:ai_infrastructure",
        source="raw_automatic_inference",
    )

    _fixture(
        tmp_path,
        [row],
        [
            {
                "symbol": "RAW",
                "company_id": "c12",
                "production_ready": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    result = report["records"][0]
    assert result["classification_authority"] is False
    assert (
        result["classification_gate_reason"]
        == "unapproved_explicit_source:raw_automatic_inference"
    )
    assert result["translation_eligible"] is True


def test_v2640_requires_manual_override_only_for_thematic_lock(
    tmp_path,
):
    row = _overview(
        "LOCK",
        "c13",
        theme="theme:advanced_semiconductors",
    )
    row["classification_lock"]["update_mode"] = "automatic"

    _fixture(
        tmp_path,
        [row],
        [
            {
                "symbol": "LOCK",
                "company_id": "c13",
                "production_ready": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )
    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    result = report["records"][0]
    assert (
        result["classification_gate_reason"]
        == "classification_lock_not_publication_grade"
    )
    assert result["translation_eligible"] is True


def test_v2640_written_report_preserves_historical_inventory_for_next_run(
    tmp_path,
):
    _fixture(
        tmp_path,
        [_overview("NVDA", "c14", theme="theme:ai_infrastructure")],
        None,
    )

    historical = {
        "records": [
            {
                "ticker": "NVDA",
                "company_id": "c14",
                "profile_production_ready": True,
            }
        ]
    }

    path = (
        tmp_path
        / "data/generated/company_profile_v2/"
        "translation_universe_census_v2640.json"
    )
    _write(path, historical)

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )

    try:
        first = mod.build_report(tmp_path)
        _write(path, first)
        second = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    assert (
        second["summary"]["historical_profile_ready_recovered_count"]
        == 1
    )
    assert second["records"][0]["previous_production_ready"] is True


def test_v2640_semantic_clean_profile_is_translate_now(tmp_path):
    _fixture(
        tmp_path,
        [_overview("CLEAN", "c15", theme="theme:ai_infrastructure")],
        [
            {
                "symbol": "CLEAN",
                "company_id": "c15",
                "production_ready": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    row = report["records"][0]
    assert row["semantic_audit_status"] == "TRANSLATE_NOW"
    assert row["translation_eligible"] is True
    assert row["translation_quality"] == "STRICT"


def test_v2640_semantic_market_customer_pollution_requires_market_repair(
    tmp_path,
):
    _fixture(
        tmp_path,
        [_overview("MARKET", "c16", theme="theme:ai_infrastructure")],
        [
            {
                "symbol": "MARKET",
                "company_id": "c16",
                "production_ready": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile(
            markets=["OEMs"],
            customers=["OEMs"],
        )
    )

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    row = report["records"][0]
    assert row["semantic_audit_status"] == "REPAIR_MARKETS"
    assert "markets:customer_type_as_market" in row[
        "semantic_quality_flags"
    ]
    assert row["translation_eligible"] is True
    assert row["translation_quality"] == "PARTIAL"


def test_v2640_semantic_multi_field_repair(tmp_path):
    _fixture(
        tmp_path,
        [
            _overview(
                "BAD",
                "c17",
                theme="theme:advanced_semiconductors",
            )
        ],
        [
            {
                "symbol": "BAD",
                "company_id": "c17",
                "production_ready": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile(
            summary="Our strategy is shareholder value.",
            offerings=[],
            markets=["China"],
        )
    )

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    row = report["records"][0]
    assert row["semantic_audit_status"] == "MULTI_FIELD_REPAIR"
    assert report["summary"]["profile_repair_count"] == 1
    assert row["translation_eligible"] is True


def test_v2640_semantic_build_failure_is_evidence_missing(tmp_path):
    _fixture(
        tmp_path,
        [_overview("MISS", "c18", theme="theme:ai_infrastructure")],
        [
            {
                "symbol": "MISS",
                "company_id": "c18",
                "production_ready": True,
            }
        ],
    )

    def fail(root, symbol):
        raise RuntimeError("missing evidence")

    original = _with_builder(fail)

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    row = report["records"][0]
    assert (
        row["semantic_audit_status"]
        == "PROFILE_ARTIFACT_MISSING"
    )
    assert row["translation_eligible"] is False
    assert row["translation_quality"] == "EVIDENCE_MISSING"


def test_v2640_semantic_resolver_prefers_indexed_existing_artifact(
    tmp_path,
):
    row = _overview(
        "ART",
        "company:test-art",
        theme="theme:ai_infrastructure",
    )

    _fixture(
        tmp_path,
        [row],
        [
            {
                "symbol": "ART",
                "company_id": "company:test-art",
                "production_ready": True,
            }
        ],
    )

    profile_rel = "per-company/company%3Atest-art.json"

    _write(
        tmp_path / "data/generated/company_profile_v2/index.json",
        {
            "symbol_to_file": {"ART": profile_rel},
            "company_id_to_file": {
                "company:test-art": profile_rel
            },
        },
    )

    _write(
        tmp_path
        / "data/generated/company_profile_v2/per-company/"
        "company:test-art.json",
        {
            **_semantic_profile(),
            "symbol": "ART",
            "company_id": "company:test-art",
        },
    )

    original = _with_builder(
        lambda root, symbol: (_ for _ in ()).throw(
            AssertionError(
                "rebuild must not run when artifact exists"
            )
        )
    )

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    result = report["records"][0]
    assert result["semantic_profile_source"] == "EXISTING_ARTIFACT"
    assert (
        result["semantic_profile_resolution_reason"]
        == "indexed_symbol_artifact"
    )


def test_v2640_semantic_resolver_finds_unindexed_legacy_artifact(
    tmp_path,
):
    row = _overview(
        "OLD",
        "company:legacy-old",
        theme="theme:ai_infrastructure",
    )

    _fixture(
        tmp_path,
        [row],
        [
            {
                "symbol": "OLD",
                "company_id": "company:legacy-old",
                "production_ready": True,
            }
        ],
    )

    _write(
        tmp_path
        / "data/generated/company_profile_v2/per-company/"
        "random-old-file.json",
        {
            **_semantic_profile(),
            "symbol": "OLD",
            "company_id": "company:legacy-old",
        },
    )

    original = _with_builder(
        lambda root, symbol: (_ for _ in ()).throw(
            AssertionError(
                "rebuild must not run when legacy artifact exists"
            )
        )
    )

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    result = report["records"][0]
    assert result["semantic_profile_source"] == "EXISTING_ARTIFACT"
    assert (
        result["semantic_profile_resolution_reason"]
        == "legacy_per_company_scan"
    )


def test_v2640_semantic_resolver_reports_rebuild_source(tmp_path):
    _fixture(
        tmp_path,
        [_overview("REBUILD", "c19", theme="theme:ai_infrastructure")],
        [
            {
                "symbol": "REBUILD",
                "company_id": "c19",
                "production_ready": True,
            }
        ],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    result = report["records"][0]
    assert (
        result["semantic_profile_source"]
        == "REBUILT_FROM_EVIDENCE"
    )
    assert (
        result["semantic_profile_resolution_reason"]
        == "rebuilt_from_canonical_evidence"
    )


def test_v2640_semantic_resolver_keeps_unresolved_reason(tmp_path):
    _fixture(
        tmp_path,
        [_overview("NOPE", "c20", theme="theme:ai_infrastructure")],
        [
            {
                "symbol": "NOPE",
                "company_id": "c20",
                "production_ready": True,
            }
        ],
    )

    def fail(root, symbol):
        raise FileNotFoundError(symbol)

    original = _with_builder(fail)

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    result = report["records"][0]
    assert result["semantic_profile_source"] == "UNRESOLVED"
    assert (
        result["semantic_profile_resolution_reason"]
        == "canonical_evidence_not_found"
    )


def test_v2640_audits_profile_for_strategic_new_profile_build_row(
    tmp_path,
):
    row = _overview(
        "NEW",
        "c22",
        theme="theme:ai_infrastructure",
    )
    _fixture(tmp_path, [row], [])

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    result = report["records"][0]
    assert result["recommended_action"] == "NEW_PROFILE_BUILD"
    assert result["semantic_audit_status"] == "TRANSLATE_NOW"
    assert result["translation_eligible"] is True


def test_v2640_strategic_profile_coverage_counts_partition_all_audited(
    tmp_path,
):
    rows = [
        _overview("GOOD", "c23", theme="theme:ai_infrastructure"),
        _overview(
            "BADMKT",
            "c24",
            theme="theme:advanced_semiconductors",
        ),
    ]
    _fixture(tmp_path, rows, [])

    def builder(root, symbol):
        if symbol == "GOOD":
            return _semantic_profile()
        return _semantic_profile(
            markets=["OEMs"],
            customers=["OEMs"],
        )

    original = _with_builder(builder)

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    summary = report["summary"]
    assert summary["strategic_profile_audited_count"] == 2
    assert summary["strategic_profile_ready_count"] == 1
    assert summary["strategic_profile_repair_count"] == 1
    assert summary["strategic_profile_build_failed_count"] == 0
    assert summary["translation_eligible_count"] == 2


def test_v2640_semantic_failure_diagnostics_include_previews_and_flags():
    records = [
        {
            "symbol": "MKT",
            "company_id": "c30",
            "display_name": "Market Co",
            "theme_id": "theme:ai_infrastructure",
            "priority": "P0",
            "semantic_audit_status": "REPAIR_MARKETS",
            "semantic_profile_source": "REBUILT_FROM_EVIDENCE",
            "semantic_profile_resolution_reason": (
                "rebuilt_from_canonical_evidence"
            ),
            "semantic_quality_flags": [
                "markets:customer_type_as_market"
            ],
            "semantic_field_flags": {
                "summary": [],
                "offerings": [],
                "markets": ["customer_type_as_market"],
            },
            "summary_available": True,
            "offerings_available": True,
            "markets_available": True,
            "summary_preview": "A useful company summary.",
            "offerings_preview": ["AI accelerators"],
            "markets_preview": ["OEMs"],
        }
    ]

    diagnostics = mod._semantic_failure_diagnostics(records)
    assert diagnostics["counts"]["REPAIR_MARKETS"] == 1
    assert (
        diagnostics["semantic_flag_counts"][
            "markets:customer_type_as_market"
        ]
        == 1
    )
    sample = diagnostics["repair_samples"]["REPAIR_MARKETS"][0]
    assert sample["markets_preview"] == ["OEMs"]
    assert sample["offerings_preview"] == ["AI accelerators"]


def test_v2640_semantic_failure_diagnostics_keep_all_build_failures():
    records = []

    for i in range(36):
        records.append(
            {
                "symbol": f"FAIL{i:02d}",
                "company_id": f"c{i}",
                "display_name": f"Fail {i}",
                "theme_id": "theme:advanced_semiconductors",
                "priority": "P0",
                "semantic_audit_status": (
                    "PROFILE_ARTIFACT_MISSING"
                ),
                "semantic_profile_source": "UNRESOLVED",
                "semantic_profile_resolution_reason": (
                    "profile_rebuild_failed:"
                    "CompanyProfileV2Error:"
                    "no canonical business evidence"
                ),
                "semantic_quality_flags": [],
                "semantic_field_flags": {},
            }
        )

    diagnostics = mod._semantic_failure_diagnostics(records)
    assert len(diagnostics["build_failures"]) == 36
    assert diagnostics["build_failures"][0]["symbol"] == "FAIL00"
    assert diagnostics["build_failures"][-1]["symbol"] == "FAIL35"


def test_v2640_theme_counts_include_profile_semantic_status(tmp_path):
    _fixture(
        tmp_path,
        [_overview("THEME", "c31", theme="theme:ai_infrastructure")],
        [],
    )

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    counts = report["theme_counts"]["theme:ai_infrastructure"]
    assert counts["profile:TRANSLATE_NOW"] == 1
    assert counts["translation:ELIGIBLE"] == 1


def test_v2640_resolution_reason_preserves_builder_error_message(
    tmp_path,
):
    original_artifact = mod._load_profile_artifact
    original_builder = mod._build_profile_for_audit

    mod._load_profile_artifact = (
        lambda root, symbol, company_id: (None, None, None)
    )

    def fail(root, symbol):
        raise RuntimeError(
            "specific canonical evidence failure"
        )

    mod._build_profile_for_audit = fail

    try:
        profile, source, reason = mod._resolve_profile_for_audit(
            tmp_path,
            symbol="ERR",
            company_id="c32",
        )
    finally:
        mod._load_profile_artifact = original_artifact
        mod._build_profile_for_audit = original_builder

    assert profile is None
    assert source == "UNRESOLVED"
    assert (
        reason
        == "profile_rebuild_failed:RuntimeError:"
        "specific canonical evidence failure"
    )


def test_v2643_semantic_pass_is_strict_translation_candidate():
    row = {
        "strategic": True,
        "match_basis": "thematic_classification",
        "classification_authority": True,
        "semantic_audit_status": "TRANSLATE_NOW",
    }

    eligible, quality, reason = (
        mod._translation_eligibility(row)
    )

    assert eligible is True
    assert quality == "STRICT"
    assert reason == "semantic_pass"


def test_v2643_semantic_repair_does_not_block_translation():
    for status in (
        "REPAIR_SUMMARY",
        "REPAIR_OFFERINGS",
        "REPAIR_MARKETS",
        "MULTI_FIELD_REPAIR",
    ):
        row = {
            "strategic": True,
            "match_basis": "thematic_classification",
            "classification_authority": True,
            "semantic_audit_status": status,
        }

        eligible, quality, reason = (
            mod._translation_eligibility(row)
        )

        assert eligible is True
        assert quality == "PARTIAL"
        assert (
            reason
            == f"semantic_repair_retained:{status}"
        )


def test_v2643_profile_artifact_missing_blocks_translation():
    row = {
        "strategic": True,
        "match_basis": "thematic_classification",
        "classification_authority": True,
        "semantic_audit_status": "PROFILE_ARTIFACT_MISSING",
        "semantic_profile_resolution_reason": (
            "profile_rebuild_failed:"
            "CompanyProfileV2Error:"
            "no canonical business evidence"
        ),
    }

    eligible, quality, reason = (
        mod._translation_eligibility(row)
    )

    assert eligible is False
    assert quality == "EVIDENCE_MISSING"
    assert "no canonical business evidence" in reason


def test_v2643_primary_business_bridge_can_enter_translation_once_profile_resolves():
    row = {
        "strategic": True,
        "match_basis": "locked_primary_business_candidate",
        "classification_authority": False,
        "semantic_audit_status": "TRANSLATE_NOW",
    }

    eligible, quality, reason = (
        mod._translation_eligibility(row)
    )

    assert eligible is True
    assert quality == "STRICT"
    assert reason == "semantic_pass"


def test_v2644_translation_candidates_include_all_resolved_strategic_rows(
    tmp_path,
):
    rows = [
        _overview(
            "NVDA",
            "c40",
            theme="theme:ai_infrastructure",
        ),
        _overview(
            "BRIDGE",
            "c41",
            category="semiconductors_and_electronic_components",
        ),
    ]
    _fixture(tmp_path, rows, [])

    original = _with_builder(
        lambda root, symbol: _semantic_profile()
    )

    try:
        report = mod.build_report(tmp_path)
    finally:
        mod._build_profile_for_audit = original

    assert {
        row["symbol"]
        for row in report["translation_candidates"]
    } == {"NVDA", "BRIDGE"}

    assert report["summary"]["translation_eligible_count"] == 2
    assert report["summary"]["translation_blocked_count"] == 0