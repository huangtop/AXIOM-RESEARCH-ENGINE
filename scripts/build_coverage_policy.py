#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from axiom_engine.coverage_policy import (  # noqa: E402
    build_coverage_policy,
    write_coverage_policy,
)

COVERAGE_PATH = (
    ROOT
    / "data/generated/coverage_policy/coverage_policy.json"
)


def _load_coverage(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError(
            f"Expected coverage policy projection to be an object: {path}"
        )

    return payload


def _publication_coverage_state(
    payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    Return only Coverage Policy fields materialized by Publication Gate.

    Publication company projections consume:
      - product_scope
      - research_scope
      - scope_axes
      - reason_codes
      - review_status

    Other Coverage Policy fields must not create publication dirty work.
    """
    state: dict[str, dict[str, Any]] = {}

    records = payload.get("records")
    if not isinstance(records, list):
        return state

    for row in records:
        if not isinstance(row, dict):
            continue

        company_id = str(row.get("company_id") or "")
        if not company_id:
            continue

        scope_axes = row.get("scope_axes")
        if not isinstance(scope_axes, dict):
            scope_axes = {}

        reason_codes = row.get("reason_codes")
        if not isinstance(reason_codes, list):
            reason_codes = []

        state[company_id] = {
            "product_scope": row.get("product_scope"),
            "research_scope": row.get("research_scope"),
            "scope_axes": scope_axes,
            "reason_codes": sorted(
                str(value)
                for value in reason_codes
                if str(value)
            ),
            "review_status": row.get("review_status"),
        }

    return state


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


def _company_symbols(root: Path) -> dict[str, set[str]]:
    """
    Match Full Market's active + valuation-eligible security semantics.
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
            "Expected security identity payload to be an object: "
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
            "Build Coverage Policy and optionally emit symbols whose "
            "Publication-visible coverage state changed."
        )
    )
    parser.add_argument(
        "--dirty-symbols-output",
        type=Path,
        help=(
            "Write ticker symbols whose Publication-visible Coverage "
            "Policy state changed."
        ),
    )
    args = parser.parse_args()

    before_payload = _load_coverage(COVERAGE_PATH)
    before_state = _publication_coverage_state(before_payload)

    report = build_coverage_policy(ROOT)
    write_coverage_policy(report, COVERAGE_PATH)

    after_payload = _load_coverage(COVERAGE_PATH)
    after_state = _publication_coverage_state(after_payload)

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
                "Publication-visible Coverage Policy changes could not "
                "be mapped to ticker symbols. "
                f"unresolved_count={len(unresolved)} "
                f"examples={preview}"
            )

    print(report["summary"])

    if args.dirty_symbols_output is not None:
        print(
            {
                "coverage_dirty_company_count": len(
                    dirty_company_ids
                ),
                "coverage_dirty_symbol_count": len(
                    dirty_symbols
                ),
                "dirty_symbols_output": str(
                    args.dirty_symbols_output
                ),
                "comparison_fields": [
                    "product_scope",
                    "research_scope",
                    "scope_axes",
                    "reason_codes",
                    "review_status",
                ],
            }
        )


if __name__ == "__main__":
    main()
