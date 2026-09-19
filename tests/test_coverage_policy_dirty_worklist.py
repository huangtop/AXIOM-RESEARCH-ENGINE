import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/build_coverage_policy.py"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "build_coverage_policy",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT = _load_script()


def _payload(
    *,
    product_scope="basic_market",
    research_scope="contextual",
    scope_axes=None,
    reason_codes=None,
    review_status="automatic",
    valuation=None,
    evidence_refs=None,
):
    return {
        "records": [
            {
                "company_id": "company:A",
                "product_scope": product_scope,
                "research_scope": research_scope,
                "scope_axes": scope_axes or {
                    "company_page": True,
                    "valuation_card": True,
                    "research_page": False,
                },
                "reason_codes": reason_codes or [
                    "OPERATING_COMPANY_VALUATION_ELIGIBLE"
                ],
                "review_status": review_status,
                "valuation": valuation or {
                    "data_status": "ready",
                    "calculated_model_count": 3,
                },
                "evidence_refs": evidence_refs or [],
            }
        ]
    }


def _dirty(before, after):
    return SCRIPT._dirty_company_ids(
        SCRIPT._publication_coverage_state(before),
        SCRIPT._publication_coverage_state(after),
    )


def test_product_scope_change_is_coverage_dirty():
    before = _payload(product_scope="basic_market")
    after = _payload(product_scope="frontier_research")

    assert _dirty(before, after) == ["company:A"]


def test_research_scope_change_is_coverage_dirty():
    before = _payload(research_scope="contextual")
    after = _payload(research_scope="core")

    assert _dirty(before, after) == ["company:A"]


def test_scope_axes_change_is_coverage_dirty():
    before = _payload()

    after = _payload(
        scope_axes={
            "company_page": True,
            "valuation_card": True,
            "research_page": True,
        }
    )

    assert _dirty(before, after) == ["company:A"]


def test_reason_codes_change_is_coverage_dirty():
    before = _payload(reason_codes=["A"])
    after = _payload(reason_codes=["B"])

    assert _dirty(before, after) == ["company:A"]


def test_review_status_change_is_coverage_dirty():
    before = _payload(review_status="automatic")
    after = _payload(review_status="reviewed")

    assert _dirty(before, after) == ["company:A"]


def test_reason_code_order_does_not_create_dirty():
    before = _payload(reason_codes=["B", "A"])
    after = _payload(reason_codes=["A", "B"])

    assert _dirty(before, after) == []


def test_non_publication_valuation_change_is_not_coverage_dirty():
    before = _payload(
        valuation={
            "data_status": "ready",
            "calculated_model_count": 3,
        }
    )
    after = _payload(
        valuation={
            "data_status": "ready",
            "calculated_model_count": 7,
        }
    )

    assert _dirty(before, after) == []


def test_evidence_only_change_is_not_coverage_dirty():
    before = _payload(evidence_refs=["old"])
    after = _payload(evidence_refs=["new"])

    assert _dirty(before, after) == []


def test_added_record_is_coverage_dirty():
    before = {"records": []}
    after = _payload()

    assert _dirty(before, after) == ["company:A"]


def test_removed_record_is_coverage_dirty():
    before = _payload()
    after = {"records": []}

    assert _dirty(before, after) == ["company:A"]
