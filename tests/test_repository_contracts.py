from __future__ import annotations

import json
from pathlib import Path

from axiom_engine.repository_contracts import CONTRACTS, audit_repository, write_audit_report


def test_contract_ids_are_unique() -> None:
    ids = [item.contract_id for item in CONTRACTS]
    assert len(ids) == len(set(ids))


def test_contracts_define_canonical_owner_and_paths() -> None:
    assert CONTRACTS
    for contract in CONTRACTS:
        assert contract.canonical_owner.value
        assert contract.canonical_paths


def test_audit_is_read_only_and_reports_empty_input(tmp_path: Path) -> None:
    input_dir = tmp_path / "data" / "company_registry"
    input_dir.mkdir(parents=True)
    (input_dir / "business_descriptions.json").write_text("[]\n", encoding="utf-8")
    report = audit_repository(tmp_path)
    assert report["read_only"] is True
    contract = next(item for item in report["contracts"] if item["contract_id"] == "business_description")
    assert "accepted_input_empty" in contract["findings"]
    assert not (tmp_path / "data" / "generated").exists()


def test_write_report_creates_machine_readable_output(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    report = write_audit_report(tmp_path, output)
    assert output.exists()
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "v030.2"
    assert loaded["contract_count"] == report["contract_count"]


def test_pending_structure_contract_is_explicit() -> None:
    contract = next(item for item in CONTRACTS if item.contract_id == "investment_classification")
    assert contract.status.value == "pending"
    assert "structure.json" in contract.accepted_inputs
