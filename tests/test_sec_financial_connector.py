from __future__ import annotations

import gzip
import json
import urllib.error
import zlib
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from axiom_engine.sec_companyfacts import (
    SECCompanyFacts,
    SECCompanyFactsValidationError,
    normalize_cik,
)
from axiom_engine.sec_financial_connector import (
    SECConnectorConfig,
    SECFinancialConnector,
    SECFinancialHTTPError,
    SECFinancialResponseError,
    _decode_body,
)

SAMPLE_PAYLOAD: dict[str, Any] = {
    "cik": 1045810,
    "entityName": "NVIDIA CORP",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "description": "Revenue earned.",
                "units": {
                    "USD": [
                        {
                            "start": "2024-01-01",
                            "end": "2024-12-31",
                            "val": 100,
                            "accn": "0001045810-25-000001",
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-02-01",
                            "frame": "CY2024",
                        }
                    ]
                },
            }
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "label": "Entity Common Stock Shares Outstanding",
                "description": "Shares outstanding.",
                "units": {"shares": [{"end": "2025-01-31", "val": 24_000}]},
            }
        },
    },
}
SAMPLE_JSON = json.dumps(SAMPLE_PAYLOAD)


class FakeResponse:
    def __init__(self, body: bytes, encoding: str | None = None) -> None:
        self.body = body
        self.headers = {} if encoding is None else {"Content-Encoding": encoding}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_normalize_cik() -> None:
    assert normalize_cik(1045810) == "0001045810"
    assert normalize_cik("CIK0001045810") == "0001045810"
    with pytest.raises(ValueError, match="digits"):
        normalize_cik("NVDA")


def test_company_facts_model_parses_and_finds_fact() -> None:
    facts = SECCompanyFacts.from_json(SAMPLE_JSON)
    assert facts.cik == "0001045810"
    assert facts.entity_name == "NVIDIA CORP"
    assert facts.fact_count == 2
    assert facts.observation_count == 2
    revenue = facts.find_fact("us-gaap", "Revenues")
    assert revenue is not None
    assert revenue.units[0].observations[0].fiscal_year == 2025


def test_company_facts_rejects_invalid_shape() -> None:
    with pytest.raises(SECCompanyFactsValidationError, match="facts"):
        SECCompanyFacts.from_json('{"cik": 1, "entityName": "Bad", "facts": []}')


def test_connector_builds_sec_url_headers_and_returns_model() -> None:
    observed: dict[str, object] = {}

    def opener(request: object, *, timeout: float) -> FakeResponse:
        observed["url"] = request.full_url  # type: ignore[attr-defined]
        observed["user_agent"] = request.get_header("User-agent")  # type: ignore[attr-defined]
        observed["timeout"] = timeout
        return FakeResponse(SAMPLE_JSON.encode())

    connector = SECFinancialConnector(
        SECConnectorConfig(user_agent="AXIOM test@example.com"), opener=opener
    )
    facts = connector.company_facts("1045810")
    assert facts.entity_name == "NVIDIA CORP"
    assert observed == {
        "url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json",
        "user_agent": "AXIOM test@example.com",
        "timeout": 30.0,
    }


def test_connector_rejects_cik_mismatch() -> None:
    payload = {**SAMPLE_PAYLOAD, "cik": 320193}
    connector = SECFinancialConnector(
        SECConnectorConfig(user_agent="AXIOM test@example.com"),
        opener=lambda *_args, **_kwargs: FakeResponse(json.dumps(payload).encode()),
    )
    with pytest.raises(SECFinancialResponseError, match="mismatch"):
        connector.company_facts("1045810")


def test_connector_uses_fresh_cache_without_network(tmp_path: Path) -> None:
    cache_path = tmp_path / "CIK0001045810.json"
    cache_path.write_text(SAMPLE_JSON)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("network should not be called")

    connector = SECFinancialConnector(
        SECConnectorConfig(user_agent="AXIOM test@example.com", cache_directory=tmp_path),
        opener=fail,
    )
    assert connector.company_facts(1045810).fact_count == 2


def test_refresh_replaces_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "CIK0001045810.json"
    stale = {**SAMPLE_PAYLOAD, "entityName": "OLD"}
    cache_path.write_text(json.dumps(stale))
    connector = SECFinancialConnector(
        SECConnectorConfig(user_agent="AXIOM test@example.com", cache_directory=tmp_path),
        opener=lambda *_args, **_kwargs: FakeResponse(SAMPLE_JSON.encode()),
    )
    assert connector.company_facts(1045810, refresh=True).entity_name == "NVIDIA CORP"
    assert json.loads(cache_path.read_text())["entityName"] == "NVIDIA CORP"


def test_retry_after_is_honored() -> None:
    calls = 0
    sleeps: list[float] = []

    def opener(*_args: object, **_kwargs: object) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            headers = Message()
            headers["Retry-After"] = "2"
            raise urllib.error.HTTPError("https://example.test", 429, "slow", headers, None)
        return FakeResponse(SAMPLE_JSON.encode())

    connector = SECFinancialConnector(
        SECConnectorConfig(
            user_agent="AXIOM test@example.com",
            minimum_interval_seconds=0,
            backoff_base_seconds=0,
        ),
        opener=opener,
        sleep=sleeps.append,
    )
    assert connector.company_facts(1045810).entity_name == "NVIDIA CORP"
    assert sleeps == [2.0]


def test_non_retryable_http_error_fails_immediately() -> None:
    def opener(*_args: object, **_kwargs: object) -> FakeResponse:
        raise urllib.error.HTTPError("https://example.test", 404, "missing", Message(), None)

    connector = SECFinancialConnector(
        SECConnectorConfig(user_agent="AXIOM test@example.com"), opener=opener
    )
    with pytest.raises(SECFinancialHTTPError, match="HTTP 404"):
        connector.company_facts(1045810)


def test_rate_limit_waits_between_requests() -> None:
    ticks = iter([10.0, 10.04, 10.11])
    sleeps: list[float] = []
    connector = SECFinancialConnector(
        SECConnectorConfig(
            user_agent="AXIOM test@example.com", minimum_interval_seconds=0.11
        ),
        opener=lambda *_args, **_kwargs: FakeResponse(SAMPLE_JSON.encode()),
        sleep=sleeps.append,
        monotonic=lambda: next(ticks),
    )
    connector.company_facts(1045810)
    connector.company_facts(1045810)
    assert sleeps == [pytest.approx(0.07)]


def test_decode_body_supports_plain_gzip_and_deflate() -> None:
    assert _decode_body(b"plain", None) == "plain"
    assert _decode_body(gzip.compress(b"gzip"), "gzip") == "gzip"
    assert _decode_body(zlib.compress(b"deflate"), "deflate") == "deflate"
