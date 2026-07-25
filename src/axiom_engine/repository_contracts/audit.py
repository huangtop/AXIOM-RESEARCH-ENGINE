from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import CONTRACTS, ContractDefinition


@dataclass(frozen=True, slots=True)
class PathObservation:
    path: str
    exists: bool
    kind: str
    record_count: int | None
    empty: bool | None
    parse_error: str | None = None


@dataclass(frozen=True, slots=True)
class ContractObservation:
    contract_id: str
    canonical_owner: str
    status: str
    canonical_paths: tuple[PathObservation, ...]
    accepted_inputs: tuple[PathObservation, ...]
    legacy_paths: tuple[PathObservation, ...]
    findings: tuple[str, ...]


def _json_count(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("records", "items", "companies", "securities", "facts", "observations", "results"):
            if isinstance(value.get(key), list):
                return len(value[key])
        return len(value)
    return None


def _observe(root: Path, relative: str) -> PathObservation:
    path = root / relative
    if not path.exists():
        return PathObservation(relative, False, "missing", None, None)
    if path.is_dir():
        children = [candidate for candidate in path.rglob("*") if candidate.is_file()]
        return PathObservation(relative, True, "directory", len(children), len(children) == 0)
    if path.suffix.lower() != ".json":
        return PathObservation(relative, True, "file", None, path.stat().st_size == 0)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return PathObservation(relative, True, "json", None, None, str(exc))
    count = _json_count(value)
    empty = count == 0 if count is not None else None
    return PathObservation(relative, True, "json", count, empty)


def _observe_many(root: Path, paths: tuple[str, ...]) -> tuple[PathObservation, ...]:
    return tuple(_observe(root, path) for path in paths)


def _findings(contract: ContractDefinition, canonical: tuple[PathObservation, ...], inputs: tuple[PathObservation, ...]) -> tuple[str, ...]:
    findings: list[str] = []
    existing_canonical = [item for item in canonical if item.exists]
    existing_inputs = [item for item in inputs if item.exists]
    if not existing_canonical:
        findings.append("canonical_output_missing")
    if len(existing_canonical) > 1:
        findings.append("multiple_canonical_path_candidates_exist")
    if any(item.parse_error for item in (*canonical, *inputs)):
        findings.append("invalid_json_detected")
    if any(item.empty is True for item in existing_canonical):
        findings.append("canonical_output_empty")
    if any(item.empty is True for item in existing_inputs):
        findings.append("accepted_input_empty")
    if not existing_inputs and contract.accepted_inputs:
        findings.append("no_accepted_input_present")
    if contract.status.value == "pending":
        findings.append("reserved_for_future_version")
    return tuple(findings)


def audit_repository(repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    observations: list[ContractObservation] = []
    for contract in CONTRACTS:
        canonical = _observe_many(root, contract.canonical_paths)
        inputs = _observe_many(root, contract.accepted_inputs)
        legacy = _observe_many(root, contract.legacy_paths)
        observations.append(
            ContractObservation(
                contract_id=contract.contract_id,
                canonical_owner=contract.canonical_owner.value,
                status=contract.status.value,
                canonical_paths=canonical,
                accepted_inputs=inputs,
                legacy_paths=legacy,
                findings=_findings(contract, canonical, inputs),
            )
        )

    owner_ids = [contract.canonical_owner.value for contract in CONTRACTS]
    duplicate_owner_contracts = sorted({owner for owner in owner_ids if owner_ids.count(owner) > 1})
    return {
        "schema_version": "v030.2",
        "generated_at": datetime.now(UTC).isoformat(),
        "repository_root": str(root),
        "read_only": True,
        "contract_count": len(CONTRACTS),
        "contracts": [
            {
                **asdict(observation),
                "canonical_paths": [asdict(item) for item in observation.canonical_paths],
                "accepted_inputs": [asdict(item) for item in observation.accepted_inputs],
                "legacy_paths": [asdict(item) for item in observation.legacy_paths],
            }
            for observation in observations
        ],
        "summary": {
            "contracts_with_missing_canonical_output": sum("canonical_output_missing" in item.findings for item in observations),
            "contracts_with_empty_inputs": sum("accepted_input_empty" in item.findings for item in observations),
            "contracts_reserved_for_future": sum("reserved_for_future_version" in item.findings for item in observations),
            "shared_owner_names": duplicate_owner_contracts,
        },
    }


def write_audit_report(repository_root: str | Path, output_path: str | Path) -> dict[str, Any]:
    report = audit_repository(repository_root)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
