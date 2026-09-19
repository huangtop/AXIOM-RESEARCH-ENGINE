import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/build_multiple_policy_v031v6.py"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "build_multiple_policy_v031v6",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT = _load_script()


def _row(
    company_id: str,
    *,
    assumptions: dict[str, Any] | None = None,
    assumption_roles: dict[str, Any] | None = None,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "company_id": company_id,
        "assumptions": assumptions or {},
        "assumption_roles": assumption_roles or {},
        "evidence_ids": evidence_ids or [],
    }


def test_assumption_value_change_is_policy_dirty() -> None:
    before_rows = [
        _row(
            "company:A",
            assumptions={"target_peg": "0.9"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=[
                "peer-median:sector:test:target_peg:n10",
            ],
        ),
    ]

    after_rows = [
        _row(
            "company:A",
            assumptions={"target_peg": "1.1"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=[
                "peer-median:sector:test:target_peg:n10",
            ],
        ),
    ]

    before = SCRIPT._valuation_policy_state(before_rows)
    after = SCRIPT._valuation_policy_state(after_rows)

    assert SCRIPT._dirty_company_ids(before, after) == [
        "company:A",
    ]


def test_assumption_role_change_is_policy_dirty() -> None:
    before_rows = [
        _row(
            "company:A",
            assumptions={"target_peg": "0.9"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=[
                "peer-median:sector:test:target_peg:n10",
            ],
        ),
    ]

    after_rows = [
        _row(
            "company:A",
            assumptions={"target_peg": "0.9"},
            assumption_roles={"target_peg": "routing_input"},
            evidence_ids=[
                "peer-median:sector:test:target_peg:n10",
            ],
        ),
    ]

    before = SCRIPT._valuation_policy_state(before_rows)
    after = SCRIPT._valuation_policy_state(after_rows)

    assert SCRIPT._dirty_company_ids(before, after) == [
        "company:A",
    ]


def test_evidence_only_change_is_not_policy_dirty() -> None:
    before_rows = [
        _row(
            "company:A",
            assumptions={"target_peg": "0.9"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=[
                "peer-median:sector:test:target_peg:n10",
            ],
        ),
    ]

    after_rows = [
        _row(
            "company:A",
            assumptions={"target_peg": "0.9"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=[
                "peer-median:sector:test:target_peg:n40",
            ],
        ),
    ]

    before = SCRIPT._valuation_policy_state(before_rows)
    after = SCRIPT._valuation_policy_state(after_rows)

    assert SCRIPT._dirty_company_ids(before, after) == []


def test_added_policy_row_is_dirty() -> None:
    before_rows: list[dict[str, Any]] = []

    after_rows = [
        _row(
            "company:A",
            assumptions={"target_peg": "0.9"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=[
                "peer-median:sector:test:target_peg:n10",
            ],
        ),
    ]

    before = SCRIPT._valuation_policy_state(before_rows)
    after = SCRIPT._valuation_policy_state(after_rows)

    assert SCRIPT._dirty_company_ids(before, after) == [
        "company:A",
    ]


def test_removed_policy_row_is_dirty() -> None:
    before_rows = [
        _row(
            "company:A",
            assumptions={"target_peg": "0.9"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=[
                "peer-median:sector:test:target_peg:n10",
            ],
        ),
    ]

    after_rows: list[dict[str, Any]] = []

    before = SCRIPT._valuation_policy_state(before_rows)
    after = SCRIPT._valuation_policy_state(after_rows)

    assert SCRIPT._dirty_company_ids(before, after) == [
        "company:A",
    ]


def test_multiple_companies_only_returns_semantically_changed_rows() -> None:
    before_rows = [
        _row(
            "company:A",
            assumptions={"target_peg": "0.9"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=["evidence:A:old"],
        ),
        _row(
            "company:B",
            assumptions={"target_peg": "1.0"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=["evidence:B:old"],
        ),
        _row(
            "company:C",
            assumptions={"target_peg": "1.1"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=["evidence:C:old"],
        ),
    ]

    after_rows = [
        # A: evidence only -> NOT dirty.
        _row(
            "company:A",
            assumptions={"target_peg": "0.9"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=["evidence:A:new"],
        ),

        # B: assumption value changed -> dirty.
        _row(
            "company:B",
            assumptions={"target_peg": "1.2"},
            assumption_roles={"target_peg": "valuation_input"},
            evidence_ids=["evidence:B:new"],
        ),

        # C: role changed -> dirty.
        _row(
            "company:C",
            assumptions={"target_peg": "1.1"},
            assumption_roles={"target_peg": "routing_input"},
            evidence_ids=["evidence:C:new"],
        ),
    ]

    before = SCRIPT._valuation_policy_state(before_rows)
    after = SCRIPT._valuation_policy_state(after_rows)

    assert SCRIPT._dirty_company_ids(before, after) == [
        "company:B",
        "company:C",
    ]


def test_company_symbols_matches_full_market_security_semantics(
    tmp_path: Path,
) -> None:
    securities_path = tmp_path / "data/universe/securities.json"
    identity_path = (
        tmp_path
        / "data/generated/security_identity"
        / "security_identity_normalization.json"
    )

    securities_path.parent.mkdir(parents=True)
    identity_path.parent.mkdir(parents=True)

    securities = [
        {
            "security_id": "security:A:primary",
            "company_id": "company:A",
            "ticker": "AAA",
            "status": "active",
            "primary_listing": True,
        },
        {
            "security_id": "security:A:secondary",
            "company_id": "company:A",
            "ticker": "AAA.B",
            "status": "active",
            "primary_listing": False,
        },
        {
            "security_id": "security:A:inactive",
            "company_id": "company:A",
            "ticker": "AAA.OLD",
            "status": "inactive",
            "primary_listing": False,
        },
        {
            "security_id": "security:B:ineligible",
            "company_id": "company:B",
            "ticker": "BBB",
            "status": "active",
            "primary_listing": True,
        },
    ]

    identity = {
        "companies": [],
        "securities": [
            {
                "security_id": "security:A:primary",
                "valuation_eligible": True,
            },
            {
                "security_id": "security:A:secondary",
                "valuation_eligible": True,
            },
            {
                "security_id": "security:A:inactive",
                "valuation_eligible": True,
            },
            {
                "security_id": "security:B:ineligible",
                "valuation_eligible": False,
            },
        ],
    }

    securities_path.write_text(
        json.dumps(securities),
        encoding="utf-8",
    )
    identity_path.write_text(
        json.dumps(identity),
        encoding="utf-8",
    )

    result = SCRIPT._company_symbols(tmp_path)

    assert result == {
        "company:A": {"AAA", "AAA.B"},
    }


def test_company_symbols_uses_full_market_empty_identity_fallback(
    tmp_path: Path,
) -> None:
    securities_path = tmp_path / "data/universe/securities.json"
    identity_path = (
        tmp_path
        / "data/generated/security_identity"
        / "security_identity_normalization.json"
    )

    securities_path.parent.mkdir(parents=True)
    identity_path.parent.mkdir(parents=True)

    securities = [
        {
            "security_id": "security:A",
            "company_id": "company:A",
            "ticker": "aaa",
            "status": "active",
        },
        {
            "security_id": "security:B",
            "company_id": "company:B",
            "ticker": "bbb",
            "status": None,
        },
        {
            "security_id": "security:C",
            "company_id": "company:C",
            "ticker": "ccc",
            "status": "inactive",
        },
    ]

    identity = {
        "companies": [],
        "securities": [],
    }

    securities_path.write_text(
        json.dumps(securities),
        encoding="utf-8",
    )
    identity_path.write_text(
        json.dumps(identity),
        encoding="utf-8",
    )

    result = SCRIPT._company_symbols(tmp_path)

    assert result == {
        "company:A": {"AAA"},
        "company:B": {"BBB"},
    }


def test_dirty_symbol_writer_emits_all_eligible_company_tickers(
    tmp_path: Path,
) -> None:
    output = tmp_path / "policy-dirty.txt"

    symbols_by_company = {
        "company:A": {"AAA", "AAA.B"},
        "company:B": {"BBB"},
        "company:C": {"CCC"},
    }

    symbols, unresolved = SCRIPT._write_dirty_symbols(
        output,
        ["company:A", "company:C"],
        symbols_by_company,
    )

    assert symbols == [
        "AAA",
        "AAA.B",
        "CCC",
    ]
    assert unresolved == []

    assert output.read_text(encoding="utf-8") == (
        "AAA\n"
        "AAA.B\n"
        "CCC\n"
    )


def test_dirty_symbol_writer_reports_unresolved_company_ids(
    tmp_path: Path,
) -> None:
    output = tmp_path / "policy-dirty.txt"

    symbols, unresolved = SCRIPT._write_dirty_symbols(
        output,
        [
            "company:A",
            "company:MISSING",
        ],
        {
            "company:A": {"AAA"},
        },
    )

    assert symbols == ["AAA"]
    assert unresolved == ["company:MISSING"]

    assert output.read_text(encoding="utf-8") == "AAA\n"