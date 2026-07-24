import json
from pathlib import Path

from axiom_engine.batch_pipeline import run_batch_pipeline, validate_batch_pipeline


FIXTURE = Path(__file__).parents[1] / "examples" / "batch_pipeline_fixture"


def kwargs(tmp_path):
    return {
        "registry_dir": FIXTURE / "company_registry",
        "financial_dir": FIXTURE / "financial_data",
        "estimate_dir": FIXTURE / "estimate_data",
        "market_dir": FIXTURE / "market_data",
        "valuation_dir": FIXTURE / "valuation_data",
        "output_dir": tmp_path / "production",
    }


def test_batch_pipeline_builds_research_and_cards(tmp_path):
    report = run_batch_pipeline(**kwargs(tmp_path), batch_size=1, write=True)
    assert report == {
        "valid": True,
        "company_count": 1,
        "completed": 1,
        "failed": 0,
        "output_dir": str(tmp_path / "production"),
        "dry_run": False,
    }
    validation = validate_batch_pipeline(output_dir=tmp_path / "production")
    assert validation["valid"] is True
    assert validation["research_bundles"] == 1
    assert validation["valuation_cards"] == 1


def test_resume_reuses_completed_company(tmp_path):
    run_batch_pipeline(**kwargs(tmp_path), write=True)
    report = run_batch_pipeline(**kwargs(tmp_path), resume=True, write=True)
    assert report["completed"] == 1
    state = json.loads((tmp_path / "production" / "pipeline_state.json").read_text())
    company = state["companies"]["company:US-CIK0000320193"]
    assert company["status"] == "resumed"


def test_company_filter(tmp_path):
    report = run_batch_pipeline(**kwargs(tmp_path), company="AAPL", write=True)
    assert report["company_count"] == 1
    assert report["completed"] == 1


def test_validation_detects_count_mismatch(tmp_path):
    run_batch_pipeline(**kwargs(tmp_path), write=True)
    path = tmp_path / "production" / "research_data" / "company_research.json"
    path.write_text("[]\n", encoding="utf-8")
    validation = validate_batch_pipeline(output_dir=tmp_path / "production")
    assert validation["valid"] is False
    assert any("completed count" in error for error in validation["errors"])
