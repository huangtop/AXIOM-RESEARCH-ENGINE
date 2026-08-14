from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from axiom_engine.company_overview import (
    CompanyOverviewService,
    build_company_overviews,
    write_company_overviews,
)
from axiom_engine.valuation_http import ValuationWSGIApp


def _w(root: Path, name: str, payload):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(root: Path):
    _w(
        root,
        "config/classification_quality.v031c.5.json",
        {"theme_sector_compatibility": {"theme:space_economy": ["sector:space_systems"]}},
    )
    _w(
        root,
        "config/company_overview.v031c.6.json",
        {
            "schema_version": "canonical-company-overview-policy.v031c.6",
            "display_names_zh_tw": {
                "theme:ai_infrastructure": "人工智慧與核心科技",
                "sector:cloud_infrastructure": "雲端基礎設施與巨頭",
            },
        },
    )
    _w(
        root,
        "data/universe/companies.json",
        [{"company_id": "company:alphabet", "legal_name": "Alphabet Inc."}],
    )
    _w(
        root,
        "data/universe/securities.json",
        [
            {"company_id": "company:alphabet", "ticker": "GOOG", "status": "active"},
            {
                "company_id": "company:alphabet",
                "ticker": "GOOGL",
                "status": "active",
                "primary_listing": True,
            },
        ],
    )
    _w(
        root,
        "data/generated/canonical_business_evidence/business_evidence.json",
        [
            {
                "business_evidence_id": "e1",
                "company_id": "company:alphabet",
                "form": "10-K",
                "filing_date": "2026-02-05",
                "document_url": "https://sec.test/alphabet",
                "text_sha256": "abc",
            }
        ],
    )
    base = {"confidence": 0.9, "source_business_evidence_ids": ["e1"]}
    _w(
        root,
        "data/generated/knowledge_inference/knowledge_inference.json",
        {
            "records": [
                {
                    "company_id": "company:alphabet",
                    "source_company_signal_status": "signals_available",
                    "knowledge": [
                        {
                            "knowledge_id": "theme:ai_infrastructure",
                            "dimension": "theme",
                            "canonical_name": "AI Infrastructure",
                            **base,
                        },
                        {
                            "knowledge_id": "sector:cloud_infrastructure",
                            "dimension": "sector",
                            "canonical_name": "Cloud Infrastructure",
                            **base,
                        },
                    ],
                }
            ]
        },
    )


def test_overview_is_evidence_derived_and_uses_primary_ticker(tmp_path: Path):
    _fixture(tmp_path)
    report = build_company_overviews(tmp_path, now=datetime(2026, 8, 5, tzinfo=timezone.utc))
    row = report["records"][0]
    assert row["ticker"] == "GOOGL" and row["ticker_aliases"] == ["GOOG", "GOOGL"]
    assert row["path"]["theme"]["display_name_zh_tw"] == "人工智慧與核心科技"
    assert row["path"]["sector"]["display_name_zh_tw"] == "雲端基礎設施與巨頭"
    assert row["evidence"][0]["document_url"] == "https://sec.test/alphabet"


def test_overview_does_not_invent_path_without_evidence(tmp_path: Path):
    _fixture(tmp_path)
    _w(tmp_path, "data/generated/canonical_business_evidence/business_evidence.json", [])
    _w(
        tmp_path,
        "data/generated/knowledge_inference/knowledge_inference.json",
        {
            "records": [
                {
                    "company_id": "company:alphabet",
                    "source_company_signal_status": "business_evidence_unavailable",
                    "knowledge": [],
                }
            ]
        },
    )
    row = build_company_overviews(tmp_path)["records"][0]
    assert row["status"] == "awaiting_business_evidence" and row["path"]["theme"] is None


def test_service_resolves_goog_alias(tmp_path: Path):
    _fixture(tmp_path)
    report = build_company_overviews(tmp_path)
    write_company_overviews(report, tmp_path / "data/generated/company_overview")
    assert CompanyOverviewService(root=tmp_path).get("GOOG")["ticker"] == "GOOGL"


def test_overview_can_limit_output_to_core_companies(tmp_path: Path):
    _fixture(tmp_path)
    report = build_company_overviews(
        tmp_path,
        company_ids={"company:alphabet"},
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
    )
    assert [row["ticker"] for row in report["records"]] == ["GOOGL"]
    assert report["summary"]["company_count"] == 1


def test_overview_prefers_strong_compatible_space_path_over_weak_ai_sector(tmp_path: Path):
    _fixture(tmp_path)
    knowledge_path = tmp_path / "data/generated/knowledge_inference/knowledge_inference.json"
    payload = json.loads(knowledge_path.read_text())
    row = payload["records"][0]
    evidence = {"source_business_evidence_ids": ["e1"]}
    row["knowledge"].extend([
        {"knowledge_id": "theme:space_economy", "dimension": "theme", "canonical_name": "Space Economy", "confidence": 0.81, **evidence},
        {"knowledge_id": "sector:space_systems", "dimension": "sector", "canonical_name": "Space Systems", "confidence": 0.84, **evidence},
        {"knowledge_id": "sector:ai_compute", "dimension": "sector", "canonical_name": "AI Compute", "confidence": 0.51, **evidence},
    ])
    knowledge_path.write_text(json.dumps(payload))

    overview = build_company_overviews(tmp_path)["records"][0]

    assert overview["path"]["theme"]["id"] == "theme:space_economy"
    assert overview["path"]["sector"]["id"] == "sector:space_systems"


def test_writer_removes_stale_company_overviews(tmp_path: Path):
    _fixture(tmp_path)
    output = tmp_path / "data/generated/company_overview"
    stale = output / "per-company/STALE.json"
    _w(tmp_path, "data/generated/company_overview/per-company/STALE.json", {"ticker": "STALE"})

    report = build_company_overviews(tmp_path)
    write_company_overviews(report, output)

    assert not stale.exists()
    assert (output / "per-company/GOOGL.json").is_file()


def test_curated_core_override_is_published_without_rerunning_evidence(tmp_path: Path):
    _fixture(tmp_path)
    policy_path = tmp_path / "config/company_overview.v031c.6.json"
    policy = json.loads(policy_path.read_text())
    policy["curated_overrides"] = [{
        "company_id": "company:alphabet",
        "theme_id": "theme:artificial_intelligence",
        "theme_name": "Artificial Intelligence",
        "sector_id": "sector:cloud_infrastructure",
        "sector_name": "Cloud Infrastructure",
        "confidence": 1.0,
    }]
    policy["display_names_zh_tw"]["theme:artificial_intelligence"] = "人工智慧"
    _w(tmp_path, "config/company_overview.v031c.6.json", policy)
    _w(tmp_path, "data/generated/canonical_business_evidence/business_evidence.json", [])
    _w(tmp_path, "data/generated/knowledge_inference/knowledge_inference.json", {
        "records": [{
            "company_id": "company:alphabet",
            "source_company_signal_status": "business_evidence_unavailable",
            "knowledge": [],
        }]
    })
    report = build_company_overviews(tmp_path, company_ids=set())
    row = report["records"][0]
    assert row["status"] == "classified"
    assert row["ticker"] == "GOOGL"
    assert row["ticker_aliases"] == ["GOOG", "GOOGL"]
    assert row["path"]["theme"]["display_name_zh_tw"] == "人工智慧"
    assert row["path"]["sector"]["display_name_zh_tw"] == "雲端基礎設施與巨頭"
    assert row["classification_source"] == "curated_core_override"
    assert row["evidence"] == []


def test_published_classification_is_locked_against_new_inference(tmp_path: Path):
    _fixture(tmp_path)
    first = build_company_overviews(tmp_path)
    write_company_overviews(first, tmp_path / "data/generated/company_overview")

    knowledge_path = tmp_path / "data/generated/knowledge_inference/knowledge_inference.json"
    knowledge = json.loads(knowledge_path.read_text())
    knowledge["records"][0]["knowledge"] = [
        {
            "knowledge_id": "theme:space_economy",
            "dimension": "theme",
            "canonical_name": "Space Economy",
            "confidence": 1.0,
            "source_business_evidence_ids": ["e1"],
        },
        {
            "knowledge_id": "sector:space_systems",
            "dimension": "sector",
            "canonical_name": "Space Systems",
            "confidence": 1.0,
            "source_business_evidence_ids": ["e1"],
        },
    ]
    knowledge_path.write_text(json.dumps(knowledge))

    row = build_company_overviews(tmp_path)["records"][0]

    assert row["path"]["theme"]["id"] == "theme:ai_infrastructure"
    assert row["path"]["sector"]["id"] == "sector:cloud_infrastructure"
    assert row["classification_lock"] == {
        "status": "locked",
        "update_mode": "manual_override_only",
    }


def test_manual_override_can_replace_locked_classification(tmp_path: Path):
    _fixture(tmp_path)
    first = build_company_overviews(tmp_path)
    write_company_overviews(first, tmp_path / "data/generated/company_overview")
    policy_path = tmp_path / "config/company_overview.v031c.6.json"
    policy = json.loads(policy_path.read_text())
    policy["curated_overrides"] = [{
        "company_id": "company:alphabet",
        "theme_id": "theme:space_economy",
        "theme_name": "Space Economy",
        "sector_id": "sector:space_systems",
        "sector_name": "Space Systems",
        "confidence": 1.0,
    }]
    policy_path.write_text(json.dumps(policy))

    row = build_company_overviews(tmp_path)["records"][0]

    assert row["path"]["theme"]["id"] == "theme:space_economy"
    assert row["path"]["sector"]["id"] == "sector:space_systems"
    assert row["classification_source"] == "curated_core_override"


def test_http_exposes_canonical_company_overview(tmp_path: Path):
    _fixture(tmp_path)
    report = build_company_overviews(tmp_path)
    write_company_overviews(report, tmp_path / "data/generated/company_overview")

    class Coverage:
        def require_public(self, ticker, capability=None):
            return {"ticker": ticker}

    app = ValuationWSGIApp(
        company_overview_service=CompanyOverviewService(root=tmp_path),
        coverage_service=Coverage(),
    )
    observed = {}

    def start(status, headers):
        observed["status"] = status

    body = b"".join(
        app(
            {
                "REQUEST_METHOD": "GET",
                "PATH_INFO": "/v1/companies/GOOG/overview",
                "wsgi.input": io.BytesIO(),
            },
            start,
        )
    )
    payload = json.loads(body)
    assert observed["status"] == "200 OK"
    assert payload["ticker"] == "GOOGL"
    assert payload["path"]["sector"]["id"] == "sector:cloud_infrastructure"
