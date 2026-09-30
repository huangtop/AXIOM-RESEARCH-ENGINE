from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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


def _complete_snapshot(fetched_at: str) -> dict:
    return {
        "fetched_at": fetched_at,
        "current_fiscal_year": 2026,
        "annual_estimates": {
            "CURRENT_FY": {},
            "NEXT_FY": {},
        },
        "normalized_peg_growth": None,
        "normalized_peg_growth_basis": None,
    }


def _run_worklist(
    repo: Path,
    *,
    limit: int,
    priority_symbols: list[str] | None = None,
) -> list[str]:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts/build_daily_estimate_worklist.py"
    )
    output = repo / "worklist.txt"

    command = [
        sys.executable,
        str(script),
        "--output",
        str(output),
        "--limit",
        str(limit),
    ]

    if priority_symbols is not None:
        priority_path = repo / "priority.json"
        priority_path.write_text(
            json.dumps({"symbols": priority_symbols}),
            encoding="utf-8",
        )
        command.extend(["--priority-symbols", str(priority_path)])

    completed = subprocess.run(
        command,
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    return output.read_text(encoding="utf-8").splitlines()


def test_severely_stale_company_beats_higher_tech_tier_normal_stale_company(
    tmp_path: Path,
) -> None:
    repo = tmp_path

    publication = repo / "data/generated/publication_gate"
    publication.mkdir(parents=True)

    company_dir = repo / "data/generated/company"
    company_dir.mkdir(parents=True)

    now = datetime.now(timezone.utc)

    catalog = {
        "companies": [
            {
                "ticker": "TECH",
                "research_scope": "core",
                "scope_axes": {"news_ai": True},
                "valuation_status": "unavailable",
            },
            {
                "ticker": "OLD",
                "research_scope": "candidate",
                "scope_axes": {},
                "valuation_status": "ready",
            },
        ]
    }

    snapshots = {
        "symbols": {
            "TECH": _complete_snapshot(
                (now - timedelta(days=31)).isoformat()
            ),
            "OLD": _complete_snapshot(
                (now - timedelta(days=90)).isoformat()
            ),
        }
    }

    (publication / "company_catalog.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )
    (company_dir / "yahoo_company_snapshot.json").write_text(
        json.dumps(snapshots),
        encoding="utf-8",
    )

    assert _run_worklist(repo, limit=1) == ["OLD"]


def test_schema_incomplete_beats_normal_stale_with_same_priority_class(
    tmp_path: Path,
) -> None:
    repo = tmp_path

    publication = repo / "data/generated/publication_gate"
    publication.mkdir(parents=True)

    company_dir = repo / "data/generated/company"
    company_dir.mkdir(parents=True)

    now = datetime.now(timezone.utc)

    catalog = {
        "companies": [
            {
                "ticker": "STALE",
                "research_scope": "core",
                "scope_axes": {},
                "valuation_status": "ready",
            },
            {
                "ticker": "SCHEMA",
                "research_scope": "core",
                "scope_axes": {},
                "valuation_status": "ready",
            },
        ]
    }

    stale = _complete_snapshot(
        (now - timedelta(days=31)).isoformat()
    )
    schema = _complete_snapshot(
        (now - timedelta(days=31)).isoformat()
    )
    schema.pop("normalized_peg_growth")

    (publication / "company_catalog.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )
    (company_dir / "yahoo_company_snapshot.json").write_text(
        json.dumps(
            {
                "symbols": {
                    "STALE": stale,
                    "SCHEMA": schema,
                }
            }
        ),
        encoding="utf-8",
    )

    assert _run_worklist(repo, limit=1) == ["SCHEMA"]


def test_oldest_fetched_at_breaks_same_tier_queue_before_ticker(
    tmp_path: Path,
) -> None:
    repo = tmp_path

    publication = repo / "data/generated/publication_gate"
    publication.mkdir(parents=True)

    company_dir = repo / "data/generated/company"
    company_dir.mkdir(parents=True)

    now = datetime.now(timezone.utc)

    catalog = {
        "companies": [
            {
                "ticker": "AAA",
                "research_scope": "core",
                "scope_axes": {},
                "valuation_status": "ready",
            },
            {
                "ticker": "ZZZ",
                "research_scope": "core",
                "scope_axes": {},
                "valuation_status": "ready",
            },
        ]
    }

    snapshots = {
        "symbols": {
            "AAA": _complete_snapshot(
                (now - timedelta(days=35)).isoformat()
            ),
            "ZZZ": _complete_snapshot(
                (now - timedelta(days=50)).isoformat()
            ),
        }
    }

    (publication / "company_catalog.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )
    (company_dir / "yahoo_company_snapshot.json").write_text(
        json.dumps(snapshots),
        encoding="utf-8",
    )

    # Alphabetical ordering would choose AAA. Aging/fairness must choose ZZZ.
    assert _run_worklist(repo, limit=1) == ["ZZZ"]


def test_frontier_priority_still_beats_severe_stale_general_queue(
    tmp_path: Path,
) -> None:
    repo = tmp_path

    publication = repo / "data/generated/publication_gate"
    publication.mkdir(parents=True)

    company_dir = repo / "data/generated/company"
    company_dir.mkdir(parents=True)

    now = datetime.now(timezone.utc)

    catalog = {
        "companies": [
            {
                "ticker": "FRONT",
                "research_scope": "candidate",
                "scope_axes": {},
                "valuation_status": "ready",
            },
            {
                "ticker": "ANCIENT",
                "research_scope": "core",
                "scope_axes": {"news_ai": True},
                "valuation_status": "unavailable",
            },
        ]
    }

    snapshots = {
        "symbols": {
            "FRONT": _complete_snapshot(
                (now - timedelta(days=31)).isoformat()
            ),
            "ANCIENT": _complete_snapshot(
                (now - timedelta(days=120)).isoformat()
            ),
        }
    }

    (publication / "company_catalog.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )
    (company_dir / "yahoo_company_snapshot.json").write_text(
        json.dumps(snapshots),
        encoding="utf-8",
    )

    assert _run_worklist(
        repo,
        limit=1,
        priority_symbols=["FRONT"],
    ) == ["FRONT"]


def test_capacity_limited_queue_does_not_starve_oldest_same_tier_company(
    tmp_path: Path,
) -> None:
    repo = tmp_path

    publication = repo / "data/generated/publication_gate"
    publication.mkdir(parents=True)

    company_dir = repo / "data/generated/company"
    company_dir.mkdir(parents=True)

    now = datetime.now(timezone.utc)

    companies = []
    snapshots: dict[str, dict] = {}

    # 250 companies compete for only 200 slots.
    # T249 is oldest but alphabetically last. Under the old policy it loses to
    # T000..T199; under the aging policy it must be selected.
    for index in range(250):
        symbol = f"T{index:03d}"
        companies.append(
            {
                "ticker": symbol,
                "research_scope": "core",
                "scope_axes": {},
                "valuation_status": "ready",
            }
        )

        age = 59 if index < 249 else 60
        snapshots[symbol] = _complete_snapshot(
            (now - timedelta(days=age)).isoformat()
        )

    (publication / "company_catalog.json").write_text(
        json.dumps({"companies": companies}),
        encoding="utf-8",
    )
    (company_dir / "yahoo_company_snapshot.json").write_text(
        json.dumps({"symbols": snapshots}),
        encoding="utf-8",
    )

    selected = _run_worklist(repo, limit=200)

    assert len(selected) == 200
    assert "T249" in selected
    assert selected[0] == "T249"
