from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.company_profile_v2.batch import (
    build_company_profile_census,
    evidence_scope_inventory,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v26_inventory_matches_business_evidence_index():
    index = json.loads(
        (
            ROOT
            / "data/generated/canonical_business_evidence/index.json"
        ).read_text(encoding="utf-8")
    )

    mapping = index.get("company_id_to_file") or {}

    expected = (
        len(mapping)
        if isinstance(mapping, dict)
        else len(
            {
                str(value)
                for value in mapping
                if str(value)
            }
        )
    )

    inventory = evidence_scope_inventory(ROOT)

    assert inventory["evidence_company_count"] == expected
    assert (
        inventory["mapped_company_count"]
        + inventory["unresolved_company_count"]
        == expected
    )


def test_v26_smoke_census_reports_success_failure_and_readiness_taxonomy():
    report = build_company_profile_census(
        ROOT,
        symbols=["AAOI", "NVDA"],
        checkpoint_every=0,
    )

    summary = report["summary"]

    assert summary["attempted_company_count"] == 2
    assert (
        summary["generated_company_count"]
        + summary["build_failed_company_count"]
        == 2
    )
    assert (
        summary["production_ready_count"]
        + summary["not_production_ready_count"]
        == summary["generated_company_count"]
    )

    assert isinstance(report["failure_reasons"], dict)
    assert isinstance(report["readiness_reasons"], dict)
    assert isinstance(report["publishable_symbols"], list)