import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from axiom_engine.models.valuation_catalog import ValuationProfileCatalogEntry


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "universe" / "valuation_profile_catalog.json"
VALUATION_PROFILES_PATH = ROOT / "data" / "valuation" / "valuation_profiles.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_catalog_records_validate() -> None:
    records = [ValuationProfileCatalogEntry.model_validate(item) for item in load_json(CATALOG_PATH)]
    assert len(records) >= 2
    assert all(record.active for record in records)


def test_catalog_profile_ids_are_unique() -> None:
    profile_ids = [item["profile_id"] for item in load_json(CATALOG_PATH)]
    assert len(profile_ids) == len(set(profile_ids))


def test_catalog_covers_existing_valuation_profiles() -> None:
    catalog_ids = {item["profile_id"] for item in load_json(CATALOG_PATH)}
    valuation_ids = {item["profile_id"] for item in load_json(VALUATION_PROFILES_PATH)}
    assert valuation_ids <= catalog_ids


def test_primary_model_has_legacy_mapping() -> None:
    for record in load_json(CATALOG_PATH):
        primary = [item for item in record["model_policy"] if item["applicability"] == "primary"]
        assert primary
        assert all(item.get("legacy_calc_type") for item in primary)


def test_duplicate_priorities_are_rejected() -> None:
    payload = load_json(CATALOG_PATH)[0]
    payload["model_policy"][1]["priority"] = payload["model_policy"][0]["priority"]
    with pytest.raises(ValidationError):
        ValuationProfileCatalogEntry.model_validate(payload)
