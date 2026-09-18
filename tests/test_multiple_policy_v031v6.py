import json
import math
from pathlib import Path

from axiom_engine.multiple_policy import build_multiple_policy


def _write_market_cache(tmp_path: Path, symbol: str, close: str = "100") -> None:
    path = tmp_path / "data/generated/market/previous_close_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({symbol: [float(close), "2026-07-28"]})
    )


def test_only_ready_historical_benchmarks_become_evidence_backed_assumptions(tmp_path: Path):
    payload = {"schema_version": "historical-multiple-benchmark.v030.13.3", "benchmarks": [
        {"company_id": "c1", "method": "forward_pe", "status": "ready", "confidence": "high", "selected_window": "252d", "latest_observation_date": "2026-07-28", "benchmark": {"target_multiple": 22}},
        {"company_id": "c1", "method": "price_to_book", "status": "ready", "confidence": "medium", "selected_window": "60d", "latest_observation_date": "2026-07-28", "benchmark": {"target_multiple": 3}},
        {"company_id": "c2", "method": "ev_to_ebitda", "status": "ready", "confidence": "low", "benchmark": {"target_multiple": 12}},
    ]}
    path = tmp_path / "data/generated/historical_multiple_benchmark/historical_multiple_benchmark.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))
    report = build_multiple_policy(tmp_path)
    assert report["companies"][0]["assumptions"] == {"target_forward_pe": 22, "target_forward_pb": 3}
    assert len(report["companies"][0]["evidence_ids"]) == 2
    assert (
        report["policy"]["current_spot_multiple_as_target"]
        == "allowed_with_alpha_0_5_fundamental_normalization_for_pe_ps"
    )
    assert report["policy"]["normalized_models"] == ["forward_pe", "forward_ps"]
    assert report["policy"]["normalization_alpha"] == 0.5


def test_milestone_and_peg_are_not_created_without_their_own_evidence(tmp_path: Path):
    payload = {"schema_version": "historical-multiple-benchmark.v030.13.3", "benchmarks": []}
    path = tmp_path / "data/generated/historical_multiple_benchmark/historical_multiple_benchmark.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))
    report = build_multiple_policy(tmp_path)
    assert report["companies"] == []


def test_market_multiples_normalize_forward_pe_and_ps_without_using_analyst_target_for_peg(tmp_path: Path):
    snapshot = {"symbols": {"AAA": {
        "fetched_at": "2026-07-28T00:00:00+00:00",
        "analyst_count": 10,
        "analyst_target_mean": "120",
        "forward_eps": "8",
        "forward_eps_growth": "0.2",
        "forward_revenue": "1600",
        "shares_outstanding": "10",
        "ebitda_ttm": "80",
        "total_debt": "20",
        "total_cash": "10",
        "previous_close": "999",
        "price_to_book": "5",
        "trailing_eps": "4",
        "trailing_pe": "999",
        "revenue_ttm": "800",
        "enterprise_to_ebitda": "14",
        "annual_estimates": {
            "CURRENT_FY": {
                "eps": "8",
                "revenue": "1600",
            },
            "NEXT_FY": {
                "eps": "10",
                "revenue": "1900",
            },
        },
    }}}
    company_path = tmp_path / "data/generated/company/yahoo_company_snapshot.json"
    company_path.parent.mkdir(parents=True)
    company_path.write_text(json.dumps(snapshot))

    _write_market_cache(tmp_path, "AAA", "100")

    universe = tmp_path / "data/universe"
    universe.mkdir(parents=True)
    (universe / "securities.json").write_text(
        json.dumps([{"ticker": "AAA", "company_id": "c1"}])
    )

    report = build_multiple_policy(tmp_path)
    company = report["companies"][0]
    assumptions = company["assumptions"]

    current_pe = 100.0 / 4.0
    expected_pe = current_pe / math.sqrt(8.0 / 4.0)
    current_ps = 100.0 * 10.0 / 800.0
    expected_ps = current_ps / math.sqrt(1600.0 / 800.0)

    assert math.isclose(assumptions["target_forward_pe"], expected_pe, rel_tol=1e-12)
    assert math.isclose(assumptions["target_forward_ps"], expected_ps, rel_tol=1e-12)
    assert assumptions["target_ev_ebitda"] == 14.0
    assert assumptions["target_forward_pb"] == 5.0
    assert "target_peg" not in assumptions

    assert company["policy_version"] == "yahoo-market-roll-forward-normalized-pe-ps.v031v.12"
    assert company["assumption_roles"] == {
        "target_forward_pe": "market_anchored_fundamental_normalized",
        "target_forward_ps": "market_anchored_fundamental_normalized",
        "target_ev_ebitda": "market_anchored",
        "target_forward_pb": "market_anchored",
    }

    assert report["policy"]["analyst_target_as_multiple_source"] == "forbidden"
    assert report["policy"]["peg_policy"] == "independent_classified_peer_profile_median"
    assert report["policy"]["market_price_source"] == "data/generated/market/previous_close_cache.json"
    assert report["summary"]["normalized_forward_pe_company_count"] == 1
    assert report["summary"]["normalized_forward_ps_company_count"] == 1


def test_pe_ps_normalization_falls_back_to_current_multiple_when_forward_basis_is_missing(tmp_path: Path):
    snapshot = {"symbols": {"AAA": {
        "fetched_at": "2026-07-28T00:00:00+00:00",
        "shares_outstanding": "10",
        "previous_close": "999",
        "trailing_eps": "4",
        "trailing_pe": "999",
        "revenue_ttm": "800",
        "enterprise_to_ebitda": "14",
        "price_to_book": "5",
    }}}
    company_path = tmp_path / "data/generated/company/yahoo_company_snapshot.json"
    company_path.parent.mkdir(parents=True)
    company_path.write_text(json.dumps(snapshot))

    _write_market_cache(tmp_path, "AAA", "100")

    universe = tmp_path / "data/universe"
    universe.mkdir(parents=True)
    (universe / "securities.json").write_text(
        json.dumps([{"ticker": "AAA", "company_id": "c1"}])
    )

    report = build_multiple_policy(tmp_path)
    company = report["companies"][0]

    assert company["assumptions"]["target_forward_pe"] == 25.0
    assert company["assumptions"]["target_forward_ps"] == 1.25
    assert company["assumption_roles"]["target_forward_pe"] == "market_anchored"
    assert company["assumption_roles"]["target_forward_ps"] == "market_anchored"
    assert report["summary"]["normalized_forward_pe_company_count"] == 0
    assert report["summary"]["normalized_forward_ps_company_count"] == 0

def test_peer_target_peg_uses_normalized_growth_and_migrates_legacy_published_peg(
    tmp_path: Path,
):
    coverage_root = tmp_path / "data/generated/full_market_coverage"
    per_company = coverage_root / "per-company"
    per_company.mkdir(parents=True)

    overview_root = tmp_path / "data/generated/company_overview"
    overview_per_company = overview_root / "per-company"
    overview_per_company.mkdir(parents=True)

    companies = [
        ("AAA", "c1", "1.20"),
        ("BBB", "c2", "1.25"),
        ("CCC", "c3", "1.50"),
        ("DDD", "c4", "1.75"),
    ]
    yahoo_root = tmp_path / "data/generated/company"
    yahoo_root.mkdir(parents=True)

    (yahoo_root / "yahoo_company_snapshot.json").write_text(
        json.dumps(
            {
                "symbols": {
                    ticker: {
                        "symbol": ticker,
                        "forward_eps": "10",
                        "normalized_peg_growth": normalized_growth,
                        "normalized_peg_growth_basis": (
                            "YAHOO_GROWTH_ESTIMATES_PLUS_1Y"
                        ),
                    }
                    for ticker, _, normalized_growth in companies
                }
            }
        )
    )

    ticker_to_file = {}
    overview_ticker_to_file = {}

    for ticker, company_id, normalized_growth in companies:
        filename = f"{company_id}.json"
        ticker_to_file[ticker] = f"per-company/{filename}"
        overview_filename = f"{company_id}.json"
        overview_ticker_to_file[ticker] = overview_filename

        overview_profile = {
            "company_id": company_id,
            "path": {
                "sector": {"id": "sector:test"},
                "theme": {"id": "theme:test"},
            },
        }

        (overview_per_company / overview_filename).write_text(
            json.dumps(overview_profile)
        )

        card = {
            "company_id": company_id,
            "primary_security": {"ticker": ticker},
            "classification": {
                "sector": "sector:test",
                "theme": "theme:test",
            },
            "market": {
                "current_price": "100",
            },
            "financials": {},
            "estimates": {
                "forward_eps": {
                    "status": "ready",
                    "value": "10",
                },
                # Deliberately incompatible fiscal-transition growth.
                "forward_eps_growth": {
                    "status": "ready",
                    "value": "0.01",
                    "growth_kind": "period_transition",
                },
                # Dedicated PEG valuation/calibration growth.
                "normalized_peg_growth": {
                    "status": "ready",
                    "value": normalized_growth,
                    "growth_kind": "normalized_peg_growth",
                    "growth_basis": "YAHOO_GROWTH_ESTIMATES_PLUS_1Y",
                },
            },
        }

        (per_company / filename).write_text(json.dumps(card))

    (coverage_root / "full_market_coverage.json").write_text(
        json.dumps(
            {
                "indexes": {
                    "ticker_to_file": ticker_to_file,
                }
            }
        )
    )
    (overview_root / "index.json").write_text(
        json.dumps(
            {
                "ticker_to_file": overview_ticker_to_file,
            }
        )
    )

    existing_path = tmp_path / "data/knowledge/valuation_assumptions.json"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text(
        json.dumps(
            [
                {
                    "company_id": "c1",
                    "policy_version": "legacy-peg-contract",
                    "evidence_ids": [
                        "legacy-evidence",
                        "peer-median:operating-market:target_peg:n500",
                        "peer-median:theme:old_theme:target_peg:n20",
                        "peer-median:sector:old_sector:target_forward_pe:n10",
                    ],
                    "assumptions": {
                        "target_forward_pe": 77.0,
                        "target_peg": 4.99,
                    },
                }
            ]
        )
    )

    report = build_multiple_policy(tmp_path)

    by_company = {
        row["company_id"]: row
        for row in report["companies"]
    }
    c1 = by_company["c1"]

    # Yahoo normalized PEG growth is a fractional rate even above 1:
    # 1.50 means 150%, not 1.50%.
    #
    # Subject company c1 is excluded. Peer PEG observations are:
    #
    # BBB: (100 / 10) / (1.25 * 100) = 0.08
    # CCC: (100 / 10) / (1.50 * 100) = 1/15
    # DDD: (100 / 10) / (1.75 * 100) = 2/35
    #
    # Median = 1/15.
    assert math.isclose(
        c1["assumptions"]["target_peg"],
        1.0 / 15.0,
        rel_tol=1e-12,
    )

    # Unrelated already-published assumptions retain the existing
    # publication-stability contract.
    assert c1["assumptions"]["target_forward_pe"] == 77.0

    # The legacy PEG value must not survive migration.
    assert c1["assumptions"]["target_peg"] != 4.99

    # Recalibrating any peer-derived assumption replaces provenance from
    # prior generations for that same assumption.
    pe_evidence = [
        evidence_id
        for evidence_id in c1["evidence_ids"]
        if evidence_id.startswith("peer-median:")
        and ":target_forward_pe:" in evidence_id
    ]

    assert len(pe_evidence) == 1
    assert (
        "peer-median:sector:old_sector:target_forward_pe:n10"
        not in c1["evidence_ids"]
    )

    # Non-peer provenance still survives the merge.
    assert "legacy-evidence" in c1["evidence_ids"]

def test_peer_target_peg_uses_current_yahoo_growth_not_previous_full_market_generation(
    tmp_path: Path,
):
    coverage_root = tmp_path / "data/generated/full_market_coverage"
    coverage_per_company = coverage_root / "per-company"
    coverage_per_company.mkdir(parents=True)

    overview_root = tmp_path / "data/generated/company_overview"
    overview_per_company = overview_root / "per-company"
    overview_per_company.mkdir(parents=True)

    universe_root = tmp_path / "data/universe"
    universe_root.mkdir(parents=True)

    tickers = [
        ("AAA", "c1"),
        ("BBB", "c2"),
        ("CCC", "c3"),
        ("DDD", "c4"),
    ]

    (universe_root / "securities.json").write_text(
        json.dumps(
            [
                {"ticker": ticker, "company_id": company_id}
                for ticker, company_id in tickers
            ]
        )
    )

    coverage_index = {}
    overview_index = {}

    # Previous Full Market generation deliberately contains stale PEG growth.
    stale_growth = {
        "AAA": "0.10",
        "BBB": "0.10",
        "CCC": "0.10",
        "DDD": "0.10",
    }

    for ticker, company_id in tickers:
        filename = f"{company_id}.json"
        coverage_index[ticker] = f"per-company/{filename}"
        overview_index[ticker] = filename

        (overview_per_company / filename).write_text(
            json.dumps(
                {
                    "company_id": company_id,
                    "path": {
                        "sector": {"id": "sector:test"},
                        "theme": {"id": "theme:test"},
                    },
                }
            )
        )

        (coverage_per_company / filename).write_text(
            json.dumps(
                {
                    "company_id": company_id,
                    "primary_security": {"ticker": ticker},
                    "market": {"current_price": "100"},
                    "financials": {},
                    "estimates": {
                        "forward_eps": {
                            "status": "ready",
                            "value": "10",
                        },
                        "normalized_peg_growth": {
                            "status": "ready",
                            "value": stale_growth[ticker],
                            "growth_kind": "normalized_peg_growth",
                            "growth_basis": "YAHOO_GROWTH_ESTIMATES_PLUS_1Y",
                        },
                    },
                }
            )
        )

    (coverage_root / "full_market_coverage.json").write_text(
        json.dumps(
            {
                "indexes": {
                    "ticker_to_file": coverage_index,
                }
            }
        )
    )

    (overview_root / "index.json").write_text(
        json.dumps(
            {
                "ticker_to_file": overview_index,
            }
        )
    )

    # Current canonical Yahoo generation contains newer PEG inputs.
    #
    # For c1, peer observations should therefore be:
    # BBB: (100 / 10) / (0.25 * 100) = 0.4
    # CCC: (100 / 10) / (0.30 * 100) = 1/3
    # DDD: (100 / 10) / (0.35 * 100) = 2/7
    # Median = 1/3.
    snapshot_root = tmp_path / "data/generated/company"
    snapshot_root.mkdir(parents=True)

    current_growth = {
        "AAA": "0.20",
        "BBB": "0.25",
        "CCC": "0.30",
        "DDD": "0.35",
    }

    (snapshot_root / "yahoo_company_snapshot.json").write_text(
        json.dumps(
            {
                "symbols": {
                    ticker: {
                        "symbol": ticker,
                        "forward_eps": "10",
                        "normalized_peg_growth": current_growth[ticker],
                        "normalized_peg_growth_basis": (
                            "YAHOO_GROWTH_ESTIMATES_PLUS_1Y"
                        ),
                    }
                    for ticker, _ in tickers
                }
            }
        )
    )

    report = build_multiple_policy(tmp_path)

    by_company = {
        row["company_id"]: row
        for row in report["companies"]
    }

    assert math.isclose(
        by_company["c1"]["assumptions"]["target_peg"],
        1.0 / 3.0,
        rel_tol=1e-12,
    )