from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from axiom_engine.providers.yahoo_company_snapshot import (
    YahooCompanySnapshotCache,
    refresh_yahoo_company_snapshots,
    snapshot_from_info,
)


class FakeFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def company_info(self, symbol: str):
        self.calls.append(symbol)
        return {
            "longName": f"{symbol} Corp",
            "longBusinessSummary": "Builds advanced computing systems.",
            "sector": "Technology",
            "industry": "Semiconductors",
            "marketCap": 1000,
            "enterpriseValue": 1100,
            "sharesOutstanding": 100,
            "totalRevenue": 500,
            "ebitda": 125,
            "trailingEps": 4.2,
            "forwardEps": 5.1,
            "numberOfAnalystOpinions": 42,
        }


def test_snapshot_normalizes_fields():
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    row = snapshot_from_info("nvda", {"marketCap": 1234, "forwardEps": 5.5}, fetched_at=now)
    assert row.symbol == "NVDA"
    assert row.market_cap == "1234"
    assert row.forward_eps == "5.5"


def test_forward_estimates_prefer_next_fiscal_year_over_current_year():
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)
    row = snapshot_from_info("MU", {
        "forwardEps": "73.44",
        "earningsGrowth": "13.685",
        "__earnings_estimate__": {
            "0y": {"avg": "73.44", "growth": "13.685"},
            "+1y": {"avg": "154.89", "growth": "0.4372"},
        },
    }, fetched_at=now)
    assert row.forward_eps == "154.89"
    assert row.forward_eps_growth == "0.4372"


def test_snapshot_preserves_separate_current_and_next_fiscal_year_inputs():
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    row = snapshot_from_info("SNDK", {
        "__earnings_estimate__": {
            "0y": {"avg": "214.09818", "growth": "1.25"},
            "+1y": {"avg": "264.72162", "growth": "0.2364"},
        },
        "__revenue_estimate__": {
            "0y": {"avg": "48960258320"},
            "+1y": {"avg": "57786626660"},
        },
    }, fetched_at=now)

    assert row.forward_eps == "264.72162"
    assert row.annual_estimates == {
        "CURRENT_FY": {
            "eps": "214.09818",
            "revenue": "48960258320",
            "reported_growth": "1.25",
            "peg_growth": "0.2364",
            "growth_basis": "CURRENT_FY_TO_NEXT_FY",
        },
        "NEXT_FY": {
            "eps": "264.72162",
            "revenue": "57786626660",
            "reported_growth": "0.2364",
            "peg_growth": None,
            "growth_basis": None,
        },
    }


def test_cache_first_skips_before_provider_request(tmp_path):
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    cache = YahooCompanySnapshotCache(tmp_path / "symbols", canonical_output_path=tmp_path / "canonical.json", ttl_days=30)
    fetcher = FakeFetcher()
    first = refresh_yahoo_company_snapshots(["NVDA", "AAPL"], fetcher=fetcher, cache=cache, now=now)
    second = refresh_yahoo_company_snapshots(["NVDA", "AAPL"], fetcher=fetcher, cache=cache, now=now + timedelta(days=1))
    assert first.fetched == 2
    assert second.fetched == 0
    assert second.skipped_cached_before_request == 2
    assert fetcher.calls == ["AAPL", "NVDA"]


def test_expired_cache_refetches(tmp_path):
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    cache = YahooCompanySnapshotCache(tmp_path / "symbols", canonical_output_path=tmp_path / "canonical.json", ttl_days=30)
    fetcher = FakeFetcher()
    refresh_yahoo_company_snapshots(["NVDA"], fetcher=fetcher, cache=cache, now=now)
    report = refresh_yahoo_company_snapshots(["NVDA"], fetcher=fetcher, cache=cache, now=now + timedelta(days=31))
    assert report.fetched == 1
    assert fetcher.calls == ["NVDA", "NVDA"]


def test_committed_canonical_output_is_durable_ttl_checkpoint(tmp_path):
    now = datetime(2026, 8, 7, tzinfo=timezone.utc)
    output = tmp_path / "canonical.json"
    output.write_text(json.dumps({"symbols": {"PLTR": {
        "symbol": "PLTR",
        "fetched_at": (now - timedelta(days=1)).isoformat(),
        "forward_eps": "1.59",
        "annual_estimates": {"CURRENT_FY": {}, "NEXT_FY": {}},
        "current_fiscal_year": 2026,
    }}}))
    cache = YahooCompanySnapshotCache(tmp_path / "ignored-symbol-cache", canonical_output_path=output, ttl_days=30)
    fetcher = FakeFetcher()

    report = refresh_yahoo_company_snapshots(["PLTR"], fetcher=fetcher, cache=cache, now=now)

    assert report.fetched == 0
    assert report.skipped_cached_before_request == 1
    assert fetcher.calls == []


def test_fresh_legacy_snapshot_without_fiscal_year_is_refetched(tmp_path):
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    output = tmp_path / "canonical.json"
    output.write_text(json.dumps({"symbols": {"SNDK": {
        "symbol": "SNDK",
        "fetched_at": (now - timedelta(days=1)).isoformat(),
        "forward_eps": "264.72",
        "annual_estimates": {"CURRENT_FY": {}, "NEXT_FY": {}},
    }}}))
    cache = YahooCompanySnapshotCache(
        tmp_path / "ignored-symbol-cache",
        canonical_output_path=output,
        ttl_days=30,
    )

    assert cache.is_fresh("SNDK", now=now) is False


def test_canonical_output_contains_all_cached_symbols(tmp_path):
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    output = tmp_path / "canonical.json"
    cache = YahooCompanySnapshotCache(tmp_path / "symbols", canonical_output_path=output, ttl_days=30)
    refresh_yahoo_company_snapshots(["NVDA", "AAPL"], fetcher=FakeFetcher(), cache=cache, now=now)
    payload = json.loads(output.read_text())
    assert sorted(payload["symbols"]) == ["AAPL", "NVDA"]
    assert payload["symbols"]["NVDA"]["revenue_ttm"] == "500"


def test_partial_refresh_preserves_symbols_already_in_canonical_output(tmp_path):
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    output = tmp_path / "canonical.json"
    output.write_text(json.dumps({"symbols": {"OLD": {"symbol": "OLD", "forward_eps": "1"}}}))
    cache = YahooCompanySnapshotCache(tmp_path / "symbols", canonical_output_path=output, ttl_days=30)
    refresh_yahoo_company_snapshots(["NEW"], fetcher=FakeFetcher(), cache=cache, now=now)
    payload = json.loads(output.read_text())
    assert sorted(payload["symbols"]) == ["NEW", "OLD"]


def test_field_level_fallback_keeps_company_successful(tmp_path):
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)

    class PartialFetcher:
        def company_info(self, symbol: str):
            return {
                "shortName": "Fallback Corp",
                "marketCap": 1000,
                "previousClose": 10,
                "trailingEps": 2.5,
                "__financials__": {"Total Revenue": {"2025-12-31": 900}},
            }

    cache = YahooCompanySnapshotCache(tmp_path / "symbols", canonical_output_path=tmp_path / "canonical.json")
    report = refresh_yahoo_company_snapshots(["TEST"], fetcher=PartialFetcher(), cache=cache, now=now)
    payload = json.loads((tmp_path / "symbols" / "TEST.json").read_text())
    diagnostic = json.loads(cache.diagnostic_path.read_text())

    assert report.succeeded == 1
    assert report.failed == 0
    assert payload["company_name"] == "Fallback Corp"
    assert payload["shares_outstanding"] == "100"
    assert payload["forward_eps"] is None
    assert payload["revenue_ttm"] == "900"
    assert diagnostic["TEST"]["company_name"] == "fallback"
    assert diagnostic["TEST"]["shares"] == "fallback"
    assert diagnostic["TEST"]["forward_eps"] == "missing"


def test_missing_optional_fields_are_diagnostic_not_company_failure(tmp_path):
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)

    class MinimalFetcher:
        def company_info(self, symbol: str):
            return {"longName": "Minimal Corp"}

    cache = YahooCompanySnapshotCache(tmp_path / "symbols", canonical_output_path=tmp_path / "canonical.json")
    report = refresh_yahoo_company_snapshots(["MIN"], fetcher=MinimalFetcher(), cache=cache, now=now)
    diagnostic = json.loads(cache.diagnostic_path.read_text())

    assert report.succeeded == 1
    assert report.failed == 0
    assert diagnostic["MIN"]["forward_revenue"] == "missing"
    assert diagnostic["MIN"]["market_cap"] == "missing"


def test_json_safe_serializes_decimal_datetime_and_numpy_like_values(tmp_path):
    from decimal import Decimal

    from axiom_engine.providers.yahoo_company_snapshot import json_safe

    class NumpyLike:
        def item(self):
            return 12.5

    payload = json_safe({"decimal": Decimal("1.20"), "timestamp": datetime(2026, 7, 27, tzinfo=timezone.utc), "numpy": NumpyLike()})
    assert payload == {"decimal": "1.20", "timestamp": "2026-07-27T00:00:00+00:00", "numpy": 12.5}


def test_provider_exception_is_logged_and_other_symbols_continue(tmp_path):
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)

    class MixedFetcher:
        def company_info(self, symbol: str):
            if symbol == "BAD":
                raise KeyError("forwardRevenue")
            return {"longName": "Good Corp"}

    cache = YahooCompanySnapshotCache(tmp_path / "symbols", canonical_output_path=tmp_path / "canonical.json")
    report = refresh_yahoo_company_snapshots(["BAD", "GOOD"], fetcher=MixedFetcher(), cache=cache, now=now)

    assert report.succeeded == 1
    assert report.failed == 1
    assert "KeyError" in report.failures["BAD"]
    assert "forwardRevenue" in cache.error_log_path.read_text()


def test_trailing_eps_is_never_relabelled_as_forward_eps():
    snapshot = snapshot_from_info(
        "TEST",
        {"longName": "Test", "trailingEps": 4.2},
        fetched_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )
    assert snapshot.trailing_eps == "4.2"
    assert snapshot.forward_eps is None


def test_rate_limit_retry_is_bounded_and_circuit_breaker_preserves_checkpoint(tmp_path):
    class LimitedFetcher:
        def __init__(self):
            self.calls = 0

        def company_info(self, symbol: str):
            self.calls += 1
            raise RuntimeError("Too Many Requests: rate limited")

    fetcher = LimitedFetcher()
    sleeps = []
    cache = YahooCompanySnapshotCache(tmp_path / "symbols", canonical_output_path=tmp_path / "canonical.json")
    report = refresh_yahoo_company_snapshots(
        ["A", "B", "C"], fetcher=fetcher, cache=cache,
        now=datetime(2026, 7, 28, tzinfo=timezone.utc), sleep=sleeps.append,
        rate_limit_retries=1, rate_limit_backoff_seconds=2, rate_limit_circuit_breaker=2,
    )
    assert fetcher.calls == 4
    assert sleeps == [2, 2]
    assert report.failed == 2
    assert json.loads(cache.diagnostic_path.read_text())["__batch__"]["state"] == "rate_limit_circuit_open"


def test_max_fetch_limits_only_uncached_requests(tmp_path):
    fetcher = FakeFetcher()
    cache = YahooCompanySnapshotCache(tmp_path / "symbols", canonical_output_path=tmp_path / "canonical.json")
    now = datetime(2026, 7, 28, tzinfo=timezone.utc)
    refresh_yahoo_company_snapshots(["A"], fetcher=fetcher, cache=cache, now=now)
    fetcher.calls.clear()
    report = refresh_yahoo_company_snapshots(["A", "B", "C"], fetcher=fetcher, cache=cache, now=now, max_fetch=1)
    assert fetcher.calls == ["B"]
    assert report.skipped_cached_before_request == 1
    assert report.fetched == 1
