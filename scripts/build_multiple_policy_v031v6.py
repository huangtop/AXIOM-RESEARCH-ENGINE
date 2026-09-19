#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.multiple_policy import (  # noqa: E402
    build_multiple_policy,
    write_multiple_policy,
)


POLICY_PATH = ROOT / "data/knowledge/valuation_assumptions.json"


def _load_policy_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, list):
        raise ValueError(
            f"Expected valuation assumptions to be a list: {path}"
        )

    return [
        row
        for row in payload
        if isinstance(row, dict) and row.get("company_id")
    ]


def _valuation_policy_state(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Return only policy fields that can affect downstream valuation.

    evidence_ids are deliberately excluded.

    A provenance-only change must not make Full Market or Publication dirty
    because Full Market materializes assumption values / roles, not Multiple
    Policy evidence provenance.
    """
    state: dict[str, dict[str, Any]] = {}

    for row in rows:
        company_id = str(row["company_id"])

        assumptions = row.get("assumptions")
        if not isinstance(assumptions, dict):
            assumptions = {}

        assumption_roles = row.get("assumption_roles")
        if not isinstance(assumption_roles, dict):
            assumption_roles = {}

        state[company_id] = {
            "assumptions": assumptions,
            "assumption_roles": assumption_roles,
        }

    return state


def _company_symbols(root: Path) -> dict[str, set[str]]:
    """
    Build company_id -> ticker symbols using the exact security population
    semantics used by Full Market Coverage.

    Canonical security registry:
        data/universe/securities.json

    Valuation eligibility:
        data/generated/security_identity/
        security_identity_normalization.json

    Only active (or status-less) valuation-eligible securities participate.
    """
    securities_path = root / "data/universe/securities.json"
    identity_path = (
        root
        / "data/generated/security_identity"
        / "security_identity_normalization.json"
    )

    securities = json.loads(
        securities_path.read_text(encoding="utf-8")
    )
    identity = json.loads(
        identity_path.read_text(encoding="utf-8")
    )

    if not isinstance(securities, list):
        raise ValueError(
            f"Expected securities registry to be a list: {securities_path}"
        )

    if not isinstance(identity, dict):
        raise ValueError(
            f"Expected security identity payload to be an object: "
            f"{identity_path}"
        )

    identity_securities = identity.get("securities", [])

    if not isinstance(identity_securities, list):
        raise ValueError(
            "security_identity_normalization.json "
            "'securities' must be a list"
        )

    eligible_security_ids = {
        str(row.get("security_id"))
        for row in identity_securities
        if isinstance(row, dict)
        and row.get("valuation_eligible") is True
    }

    # Match Full Market's fallback semantics exactly:
    # if the identity layer contains no eligible-security population,
    # fall back to all canonical securities.
    if not eligible_security_ids:
        eligible_security_ids = {
            str(row.get("security_id"))
            for row in securities
            if isinstance(row, dict)
        }

    result: dict[str, set[str]] = {}

    for row in securities:
        if not isinstance(row, dict):
            continue

        if row.get("status") not in (None, "active"):
            continue

        security_id = str(row.get("security_id") or "")

        if security_id not in eligible_security_ids:
            continue

        company_id = str(row.get("company_id") or "")
        ticker = str(row.get("ticker") or "").strip().upper()

        if not company_id or not ticker:
            continue

        result.setdefault(company_id, set()).add(ticker)

    return result


def _dirty_company_ids(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> list[str]:
    company_ids = set(before) | set(after)

    return sorted(
        company_id
        for company_id in company_ids
        if before.get(company_id) != after.get(company_id)
    )


def _write_dirty_symbols(
    path: Path,
    dirty_company_ids: list[str],
    symbols_by_company: dict[str, set[str]],
) -> tuple[list[str], list[str]]:
    symbols: set[str] = set()
    unresolved: list[str] = []

    for company_id in dirty_company_ids:
        company_symbols = symbols_by_company.get(company_id)

        if not company_symbols:
            unresolved.append(company_id)
            continue

        symbols.update(company_symbols)

    ordered_symbols = sorted(symbols)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{symbol}\n" for symbol in ordered_symbols),
        encoding="utf-8",
    )

    return ordered_symbols, unresolved


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build Multiple Policy and optionally emit the ticker symbols "
            "whose valuation-affecting policy state changed."
        )
    )
    parser.add_argument(
        "--dirty-symbols-output",
        type=Path,
        help=(
            "Write ticker symbols whose assumptions or assumption_roles "
            "changed. evidence_ids-only changes are intentionally excluded."
        ),
    )
    args = parser.parse_args()

    before_rows = _load_policy_rows(POLICY_PATH)
    before_state = _valuation_policy_state(before_rows)

    report = build_multiple_policy(ROOT)
    write_multiple_policy(report, POLICY_PATH)

    after_rows = _load_policy_rows(POLICY_PATH)
    after_state = _valuation_policy_state(after_rows)

    dirty_company_ids = _dirty_company_ids(
        before_state,
        after_state,
    )

    dirty_symbols: list[str] = []
    unresolved: list[str] = []

    if args.dirty_symbols_output is not None:
        symbols_by_company = _company_symbols(ROOT)

        dirty_symbols, unresolved = _write_dirty_symbols(
            args.dirty_symbols_output,
            dirty_company_ids,
            symbols_by_company,
        )

        if unresolved:
            preview = ", ".join(unresolved[:10])
            raise RuntimeError(
                "Valuation-affecting Multiple Policy changes could not be "
                "mapped to ticker symbols. "
                f"unresolved_count={len(unresolved)} "
                f"examples={preview}"
            )

    print(report["summary"])

    if args.dirty_symbols_output is not None:
        print(
            {
                "policy_dirty_company_count": len(dirty_company_ids),
                "policy_dirty_symbol_count": len(dirty_symbols),
                "dirty_symbols_output": str(
                    args.dirty_symbols_output
                ),
                "comparison_fields": [
                    "assumptions",
                    "assumption_roles",
                ],
                "evidence_ids_affect_dirty": False,
            }
        )


if __name__ == "__main__":
    main()