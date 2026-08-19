from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.company_overview import build_company_overviews
from axiom_engine.company_signals import build_company_signals
from axiom_engine.knowledge_inference import build_knowledge_inference


ROOT = Path(__file__).resolve().parents[1]


def test_reviewed_business_offering_cohort_is_inferred_without_company_rules():
    expected = {
        "SILC": ("theme:ai_infrastructure", "sector:ai_networking"),
        "MASS": ("theme:industrial_technology", "sector:industrial_instruments"),
        "FLEX": ("theme:advanced_manufacturing", "sector:electronics_manufacturing_services"),
        "JBL": ("theme:advanced_manufacturing", "sector:electronics_manufacturing_services"),
        "HPE": ("theme:ai_infrastructure", "sector:ai_servers"),
        "SMCI": ("theme:ai_infrastructure", "sector:ai_servers"),
        "ADI": ("theme:advanced_semiconductors", "sector:semiconductors"),
        "GFS": ("theme:advanced_semiconductors", "sector:semiconductors"),
        "UMC": ("theme:advanced_semiconductors", "sector:semiconductors"),
        "STM": ("theme:advanced_semiconductors", "sector:semiconductors"),
        "VIAV": ("theme:industrial_technology", "sector:industrial_instruments"),
        "WU": ("theme:financial_services_technology", "sector:financial_technology"),
        "ACN": ("theme:enterprise_software", "sector:it_consulting_services"),
        "INFY": ("theme:enterprise_software", "sector:it_consulting_services"),
        "CLPS": ("theme:enterprise_software", "sector:it_consulting_services"),
        "VMAR": ("theme:travel_leisure", "sector:marine_recreation"),
        "TIMB": ("theme:advanced_communications", "sector:telecom_infrastructure"),
        "SNDK": ("theme:ai_infrastructure", "sector:data_infrastructure"),
    }
    securities = json.loads((ROOT / "data/universe/securities.json").read_text())
    ticker_by_company = {
        str(row["company_id"]): str(row["ticker"])
        for row in securities
        if row.get("ticker") in expected
    }

    signals = build_company_signals(ROOT, company_ids=set(ticker_by_company))
    knowledge = build_knowledge_inference(ROOT, signals_payload=signals)
    overviews = build_company_overviews(
        ROOT,
        company_ids=set(ticker_by_company),
        knowledge_payload=knowledge,
        respect_existing_locks=False,
    )
    knowledge_by_company = {
        str(row["company_id"]): row for row in knowledge["records"]
    }

    actual = {}
    for row in overviews["records"]:
        ticker = str(row.get("ticker") or "")
        if ticker not in expected:
            continue
        actual[ticker] = (
            row["path"]["theme"]["id"],
            row["path"]["sector"]["id"],
        )
        sector = next(
            item
            for item in knowledge_by_company[row["company_id"]]["knowledge"]
            if item["knowledge_id"] == expected[ticker][1]
        )
        assert sector["primary_business_score"] == 3

    assert actual == expected