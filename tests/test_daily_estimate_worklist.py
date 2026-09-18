from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def test_legacy_snapshot_missing_normalized_peg_contract_enters_worklist(
    tmp_path: Path,
) -> None:
    repo = tmp_path

    publication = repo / "data/generated/publication_gate"
    publication.mkdir(parents=True)

    company = repo / "data/generated/company"
    company.mkdir(parents=True)

    (publication / "company_catalog.json").write_text(
        json.dumps(
            {
                "companies": [
                    {
                        "ticker": "AAA",
                        "research_scope": "core",
                        "scope_axes": {},
                        "valuation_status": "ready",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # Deliberately fresh by TTL and complete under the legacy estimate contract,
    # but missing the normalized PEG schema keys.
    (company / "yahoo_company_snapshot.json").write_text(
        json.dumps(
            {
                "symbols": {
                    "AAA": {
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "current_fiscal_year": 2026,
                        "annual_estimates": {
                            "CURRENT_FY": {},
                            "NEXT_FY": {},
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    script = (
        Path(__file__).resolve().parents[1]
        / "scripts/build_daily_estimate_worklist.py"
    )
    output = repo / "worklist.txt"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--output",
            str(output),
            "--limit",
            "200",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8").splitlines() == ["AAA"]


def test_migrated_snapshot_with_null_normalized_peg_remains_fresh(
    tmp_path: Path,
) -> None:
    repo = tmp_path

    publication = repo / "data/generated/publication_gate"
    publication.mkdir(parents=True)

    company = repo / "data/generated/company"
    company.mkdir(parents=True)

    (publication / "company_catalog.json").write_text(
        json.dumps(
            {
                "companies": [
                    {
                        "ticker": "AAA",
                        "research_scope": "core",
                        "scope_axes": {},
                        "valuation_status": "ready",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # Key presence marks the schema migration complete. Yahoo is allowed to
    # legitimately provide no +1y stockTrend value.
    (company / "yahoo_company_snapshot.json").write_text(
        json.dumps(
            {
                "symbols": {
                    "AAA": {
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "current_fiscal_year": 2026,
                        "annual_estimates": {
                            "CURRENT_FY": {},
                            "NEXT_FY": {},
                        },
                        "normalized_peg_growth": None,
                        "normalized_peg_growth_basis": None,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    script = (
        Path(__file__).resolve().parents[1]
        / "scripts/build_daily_estimate_worklist.py"
    )
    output = repo / "worklist.txt"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--output",
            str(output),
            "--limit",
            "200",
            "--allow-empty",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8") == ""
