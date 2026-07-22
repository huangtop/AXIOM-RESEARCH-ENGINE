from __future__ import annotations

from axiom_engine.sec_companyfacts import SECCompanyFacts


def test_nullable_fact_metadata_is_normalized() -> None:
    payload = {
        "cik": 1045810,
        "entityName": "NVIDIA Corporation",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "label": None,
                    "description": None,
                    "units": {
                        "USD": [
                            {
                                "val": 100,
                                "fy": 2025,
                                "fp": "FY",
                                "form": "10-K",
                            }
                        ]
                    },
                }
            }
        },
    }

    company_facts = SECCompanyFacts.from_mapping(payload)
    fact = company_facts.facts[0]

    assert fact.label == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert fact.description == ""
    assert fact.observation_count == 1


def test_missing_or_null_units_produce_empty_fact_series() -> None:
    payload = {
        "cik": "0001045810",
        "entityName": "NVIDIA Corporation",
        "facts": {
            "us-gaap": {
                "MissingUnits": {"label": "Missing Units"},
                "NullUnits": {"label": "Null Units", "units": None},
            }
        },
    }

    company_facts = SECCompanyFacts.from_mapping(payload)

    assert company_facts.fact_count == 2
    assert company_facts.observation_count == 0
    assert all(fact.units == () for fact in company_facts.facts)


def test_empty_entity_name_and_unknown_taxonomy_are_accepted() -> None:
    payload = {
        "cik": 1,
        "entityName": None,
        "facts": {
            "issuer-custom-taxonomy": {
                "CustomMetric": {
                    "label": 123,
                    "description": False,
                    "units": {},
                }
            }
        },
    }

    company_facts = SECCompanyFacts.from_mapping(payload)
    fact = company_facts.facts[0]

    assert company_facts.entity_name == ""
    assert fact.taxonomy == "issuer-custom-taxonomy"
    assert fact.label == "123"
    assert fact.description == "False"


def test_scalar_observation_metadata_is_coerced() -> None:
    payload = {
        "cik": 1,
        "entityName": "Historical Issuer",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "val": 10,
                                "fy": "2024",
                                "fp": 4,
                                "form": 10,
                                "filed": 20250101,
                            }
                        ]
                    }
                }
            }
        },
    }

    company_facts = SECCompanyFacts.from_mapping(payload)
    observation = company_facts.facts[0].units[0].observations[0]

    assert observation.fiscal_year == 2024
    assert observation.fiscal_period == "4"
    assert observation.form == "10"
    assert observation.filed == "20250101"


def test_empty_taxonomy_is_accepted() -> None:
    company_facts = SECCompanyFacts.from_mapping(
        {
            "cik": 1,
            "entityName": "Empty Taxonomy",
            "facts": {"us-gaap": {}},
        }
    )

    assert company_facts.fact_count == 0
    assert company_facts.observation_count == 0
