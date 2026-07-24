from __future__ import annotations

import json
from pathlib import Path

import pytest

from axiom_engine.production_orchestrator import (
    ProductionOrchestratorError,
    run_production_orchestrator,
    validate_production_orchestrator,
)


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "production_orchestrator_fixture"


def test_orchestrator_builds_and_enriches_outputs(tmp_path: Path) -> None:
    result = run_production_orchestrator(
        registry_dir=FIXTURE / "company_registry",
        financial_dir=FIXTURE / "financial_data",
        estimate_dir=FIXTURE / "estimate_data",
        market_dir=FIXTURE / "market_data",
        valuation_dir=FIXTURE / "valuation_data",
        output_dir=tmp_path,
        batch_size=1,
        write=True,
    )
    assert result["valid"] is True
    assert result["company_count"] == 1
    assert result["completed"] == 1
    assert result["research_bundles_enriched"] == 1
    assert result["valuation_cards_enriched"] == 1

    bundles = json.loads((tmp_path / "canonical_pipeline/research_data/company_research.json").read_text())
    cards = json.loads((tmp_path / "canonical_pipeline/valuation_card/valuation_cards.json").read_text())
    assert bundles[0]["valuation_strategy"]["coverage_tier"] == "A"
    assert cards[0]["valuation_strategy"]["method"] in {"forward_pe", "forward_ev_ebitda"}


def test_orchestrator_validator_accepts_fixture_output(tmp_path: Path) -> None:
    run_production_orchestrator(
        registry_dir=FIXTURE / "company_registry",
        financial_dir=FIXTURE / "financial_data",
        estimate_dir=FIXTURE / "estimate_data",
        market_dir=FIXTURE / "market_data",
        valuation_dir=FIXTURE / "valuation_data",
        output_dir=tmp_path,
        write=True,
    )
    report = validate_production_orchestrator(output_dir=tmp_path)
    assert report["valid"] is True
    assert report["research_bundles"] == 1
    assert report["valuation_cards"] == 1


def test_orchestrator_resume_marks_company_resumed(tmp_path: Path) -> None:
    kwargs = dict(
        registry_dir=FIXTURE / "company_registry",
        financial_dir=FIXTURE / "financial_data",
        estimate_dir=FIXTURE / "estimate_data",
        market_dir=FIXTURE / "market_data",
        valuation_dir=FIXTURE / "valuation_data",
        output_dir=tmp_path,
        batch_size=1,
        write=True,
    )
    run_production_orchestrator(**kwargs)
    run_production_orchestrator(**kwargs, resume=True)
    state = json.loads((tmp_path / "canonical_pipeline/pipeline_state.json").read_text())
    assert next(iter(state["companies"].values()))["status"] == "resumed"


def test_orchestrator_rejects_invalid_batch_size(tmp_path: Path) -> None:
    with pytest.raises(ProductionOrchestratorError):
        run_production_orchestrator(output_dir=tmp_path, batch_size=0)
