from __future__ import annotations

import gzip
import random
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Callable

from axiom_engine.sec_companyfacts import (
    SECCompanyFacts,
    SECCompanyFactsValidationError,
    normalize_cik,
)

SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class SECFinancialConnectorError(RuntimeError):
    """Base error raised by the SEC financial connector."""


class SECFinancialHTTPError(SECFinancialConnectorError):
    """Raised when SEC returns a non-retryable response or retries are exhausted."""


class SECFinancialResponseError(SECFinancialConnectorError):
    """Raised when a SEC response cannot be decoded or validated."""


@dataclass(frozen=True, slots=True)
class SECConnectorConfig:
    user_agent: str
    timeout_seconds: float = 30.0
    max_attempts: int = 4
    minimum_interval_seconds: float = 0.11
    backoff_base_seconds: float = 0.5
    cache_directory: Path | None = None
    cache_ttl_seconds: float | None = 86_400.0

    def __post_init__(self) -> None:
        if not self.user_agent.strip():
            raise ValueError("user_agent is required for SEC data access")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.minimum_interval_seconds < 0 or self.backoff_base_seconds < 0:
            raise ValueError("timing values cannot be negative")
        if self.cache_ttl_seconds is not None and self.cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds cannot be negative")


class SECFinancialConnector:
    """Download and validate SEC XBRL Company Facts documents.

    The connector preserves the SEC payload as a raw snapshot while exposing a
    typed read model for downstream normalization in later commits.
    """

    def __init__(
        self,
        config: SECConnectorConfig,
        *,
        opener: Callable[..., object] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_time: Callable[[], float] = time.time,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.config = config
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleep
        self._monotonic = monotonic
        self._wall_time = wall_time
        self._random_value = random_value
        self._last_request_at: float | None = None

    def company_facts(self, cik: str | int, *, refresh: bool = False) -> SECCompanyFacts:
        normalized_cik = normalize_cik(cik)
        cache_path = self._cache_path(normalized_cik)
        if not refresh and cache_path is not None and self._cache_is_fresh(cache_path):
            return self._read_cached(cache_path, normalized_cik)

        payload = self._fetch(normalized_cik)
        try:
            company_facts = SECCompanyFacts.from_json(payload)
        except SECCompanyFactsValidationError as exc:
            raise SECFinancialResponseError(
                f"invalid SEC Company Facts response for CIK {normalized_cik}"
            ) from exc
        if company_facts.cik != normalized_cik:
            raise SECFinancialResponseError(
                f"SEC Company Facts CIK mismatch: requested {normalized_cik}, "
                f"received {company_facts.cik}"
            )
        if cache_path is not None:
            company_facts.write_json(cache_path)
        return company_facts

    def _fetch(self, cik: str) -> str:
        url = SEC_COMPANYFACTS_URL.format(cik=cik)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.config.user_agent.strip(),
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        last_error: BaseException | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            self._respect_rate_limit()
            try:
                with self._opener(request, timeout=self.config.timeout_seconds) as response:
                    self._last_request_at = self._monotonic()
                    body = response.read()
                    encoding = response.headers.get("Content-Encoding", "")
                    return _decode_body(body, encoding)
            except urllib.error.HTTPError as exc:
                self._last_request_at = self._monotonic()
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt == self.config.max_attempts:
                    raise SECFinancialHTTPError(
                        f"SEC request failed for CIK {cik}: HTTP {exc.code}"
                    ) from exc
                self._sleep(self._retry_delay(attempt, exc.headers))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._last_request_at = self._monotonic()
                last_error = exc
                if attempt == self.config.max_attempts:
                    raise SECFinancialHTTPError(
                        f"SEC request failed for CIK {cik} after {attempt} attempts"
                    ) from exc
                self._sleep(self._retry_delay(attempt, None))
        raise SECFinancialHTTPError(f"SEC request failed for CIK {cik}") from last_error

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._monotonic() - self._last_request_at
        remaining = self.config.minimum_interval_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _retry_delay(self, attempt: int, headers: Message | None) -> float:
        if headers is not None:
            retry_after = headers.get("Retry-After")
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    pass
        exponential = self.config.backoff_base_seconds * (2 ** (attempt - 1))
        return exponential + exponential * 0.25 * self._random_value()

    def _cache_path(self, cik: str) -> Path | None:
        if self.config.cache_directory is None:
            return None
        return Path(self.config.cache_directory) / f"CIK{cik}.json"

    def _cache_is_fresh(self, path: Path) -> bool:
        if not path.is_file():
            return False
        ttl = self.config.cache_ttl_seconds
        if ttl is None:
            return True
        return self._wall_time() - path.stat().st_mtime <= ttl

    def _read_cached(self, path: Path, cik: str) -> SECCompanyFacts:
        try:
            company_facts = SECCompanyFacts.from_json(path.read_text(encoding="utf-8"))
        except (OSError, SECCompanyFactsValidationError) as exc:
            raise SECFinancialResponseError(f"invalid cached Company Facts file: {path}") from exc
        if company_facts.cik != cik:
            raise SECFinancialResponseError(
                f"cached Company Facts CIK mismatch: expected {cik}, received {company_facts.cik}"
            )
        return company_facts


def _decode_body(body: bytes, content_encoding: str | None) -> str:
    encoding = (content_encoding or "").split(",", 1)[0].strip().lower()
    try:
        if encoding == "gzip":
            body = gzip.decompress(body)
        elif encoding == "deflate":
            try:
                body = zlib.decompress(body)
            except zlib.error:
                body = zlib.decompress(body, -zlib.MAX_WBITS)
        return body.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError, zlib.error) as exc:
        raise SECFinancialResponseError("failed to decode SEC response body") from exc
