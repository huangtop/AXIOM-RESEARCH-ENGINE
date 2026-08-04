from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol


class YahooCompanySnapshotError(RuntimeError):
    pass


class CompanyInfoFetcher(Protocol):
    def company_info(self, symbol: str) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class YahooCompanySnapshot:
    symbol: str
    provider: str
    fetched_at: str
    last_refresh: str
    confidence: str
    company_name: str | None
    business_summary: str | None
    summary: str | None
    sector: str | None
    industry: str | None
    country: str | None
    website: str | None
    currency: str | None
    exchange: str | None
    quote_type: str | None
    employees: int | None
    market_cap: str | None
    enterprise_value: str | None
    shares_outstanding: str | None
    revenue_ttm: str | None
    gross_profit_ttm: str | None
    ebitda_ttm: str | None
    net_income_ttm: str | None
    operating_cash_flow_ttm: str | None
    free_cash_flow_ttm: str | None
    total_cash: str | None
    total_debt: str | None
    trailing_eps: str | None
    forward_eps: str | None
    forward_eps_growth: str | None
    forward_revenue: str | None
    trailing_pe: str | None
    forward_pe: str | None
    price_to_book: str | None
    enterprise_to_revenue: str | None
    enterprise_to_ebitda: str | None
    beta: str | None
    analyst_target_mean: str | None
    analyst_count: int | None
    previous_close: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class YahooCompanyRefreshReport:
    requested: int
    fetched: int
    succeeded: int
    skipped_cached_before_request: int
    failed: int
    failures: dict[str, str]
    cache_ttl_days: int
    output_path: str
    symbol_cache_root: str
    diagnostic_path: str
    error_log_path: str

    @property
    def success_rate(self) -> float:
        return 1.0 if self.fetched == 0 else self.succeeded / self.fetched

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["success_rate"] = round(self.success_rate, 6)
        return payload


class YFinanceCompanyInfoFetcher:
    """Collect Yahoo endpoints independently so one unavailable endpoint is non-fatal."""

    def company_info(self, symbol: str) -> Mapping[str, object]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise YahooCompanySnapshotError(
                "yfinance is required for live Yahoo company snapshots; install with: pip install yfinance"
            ) from exc

        provider_symbol = symbol.replace(".", "-") if re.fullmatch(r"[A-Z]+\.[A-Z]", symbol) else symbol
        ticker = yf.Ticker(provider_symbol)
        payload: dict[str, object] = {}
        endpoint_errors: dict[str, str] = {}

        info = self._mapping_endpoint(ticker, "info", endpoint_errors)
        if not info:
            info = self._call_mapping_endpoint(ticker, "get_info", endpoint_errors)
        payload.update(info)

        fast_info = self._mapping_endpoint(ticker, "fast_info", endpoint_errors)
        payload["__fast_info__"] = fast_info
        payload["__calendar__"] = {}
        payload["__earnings_estimate__"] = self._dataframe_records(ticker, "earnings_estimate", endpoint_errors)
        payload["__revenue_estimate__"] = self._dataframe_records(ticker, "revenue_estimate", endpoint_errors)
        payload["__financials__"] = {}
        payload["__endpoint_errors__"] = endpoint_errors

        if not payload or not any(key for key in payload if not key.startswith("__")):
            if not fast_info and not payload.get("__financials__"):
                details = "; ".join(f"{key}={value}" for key, value in endpoint_errors.items())
                raise YahooCompanySnapshotError(f"Yahoo returned no usable company information for {symbol}: {details}")
        return payload

    @staticmethod
    def _mapping_endpoint(ticker: object, name: str, errors: dict[str, str]) -> dict[str, object]:
        try:
            value = getattr(ticker, name)
            return _as_mapping(value)
        except Exception as exc:  # yfinance exposes multiple provider/library exceptions
            errors[name] = f"{type(exc).__name__}: {exc}"
            return {}

    @staticmethod
    def _call_mapping_endpoint(ticker: object, name: str, errors: dict[str, str]) -> dict[str, object]:
        try:
            value = getattr(ticker, name)()
            return _as_mapping(value)
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
            return {}

    @staticmethod
    def _dataframe_records(ticker: object, name: str, errors: dict[str, str]) -> object:
        try:
            value = getattr(ticker, name)
            if value is None:
                return []
            if hasattr(value, "to_dict"):
                try:
                    return value.to_dict(orient="index")
                except TypeError:
                    return value.to_dict()
            return json_safe(value)
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
            return []


class YahooCompanySnapshotCache:
    def __init__(
        self,
        symbol_cache_root: Path,
        *,
        canonical_output_path: Path,
        ttl_days: int = 30,
        diagnostic_path: Path | None = None,
        error_log_path: Path | None = None,
    ) -> None:
        if ttl_days < 1:
            raise ValueError("ttl_days must be positive")
        self.symbol_cache_root = Path(symbol_cache_root)
        self.canonical_output_path = Path(canonical_output_path)
        self.ttl_days = ttl_days
        provider_root = self.symbol_cache_root.parent
        self.diagnostic_path = Path(diagnostic_path or provider_root / "provider_diagnostic.json")
        self.error_log_path = Path(error_log_path or provider_root / "provider_errors.log")

    def is_fresh(self, symbol: str, *, now: datetime) -> bool:
        payload = self.read_symbol(symbol)
        if not payload:
            return False
        fetched_at = payload.get("fetched_at") or payload.get("last_refresh")
        if not isinstance(fetched_at, str):
            return False
        try:
            fetched = datetime.fromisoformat(fetched_at)
        except ValueError:
            return False
        if fetched.tzinfo is None or fetched.utcoffset() is None:
            return False
        return now - fetched <= timedelta(days=self.ttl_days)

    def read_symbol(self, symbol: str) -> dict[str, object]:
        path = self.symbol_path(symbol)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

    def write_symbol(self, snapshot: YahooCompanySnapshot) -> None:
        self._atomic_json_write(self.symbol_path(snapshot.symbol), snapshot.to_dict())

    def write_diagnostics(self, diagnostics: Mapping[str, object]) -> None:
        existing: dict[str, object] = {}
        try:
            loaded = json.loads(self.diagnostic_path.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping):
                existing.update(loaded)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        existing.update(diagnostics)
        self._atomic_json_write(self.diagnostic_path, dict(sorted(existing.items())))

    def append_error(self, symbol: str, exc: BaseException, *, occurred_at: datetime) -> None:
        self.error_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.error_log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{occurred_at.isoformat()}] {symbol}\n{type(exc).__name__}: {exc}\n\n")

    def rebuild_canonical_output(self, *, generated_at: datetime) -> int:
        symbols: dict[str, dict[str, object]] = {}
        try:
            existing = json.loads(self.canonical_output_path.read_text(encoding="utf-8"))
            if isinstance(existing, Mapping) and isinstance(existing.get("symbols"), Mapping):
                symbols.update({str(key): dict(value) for key, value in existing["symbols"].items() if isinstance(value, Mapping)})
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        if self.symbol_cache_root.exists():
            for path in sorted(self.symbol_cache_root.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(payload, Mapping) and payload.get("symbol"):
                    symbols[str(payload["symbol"])] = dict(payload)
        self._atomic_json_write(
            self.canonical_output_path,
            {
                "schema_version": "yahoo-company-snapshot.v030.10.3",
                "version": "V030.10.3",
                "provider": "yahoo_finance",
                "generated_at": generated_at.isoformat(),
                "cache_ttl_days": self.ttl_days,
                "symbols": dict(sorted(symbols.items())),
            },
        )
        return len(symbols)

    def symbol_path(self, symbol: str) -> Path:
        safe = symbol.strip().upper().replace("/", "_")
        return self.symbol_cache_root / f"{safe}.json"

    @staticmethod
    def _atomic_json_write(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)


def refresh_yahoo_company_snapshots(
    symbols: Iterable[str],
    *,
    fetcher: CompanyInfoFetcher,
    cache: YahooCompanySnapshotCache,
    now: datetime | None = None,
    request_delay_seconds: float = 0.0,
    force: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    rate_limit_retries: int = 0,
    rate_limit_backoff_seconds: float = 30.0,
    rate_limit_circuit_breaker: int = 5,
    max_fetch: int | None = None,
) -> YahooCompanyRefreshReport:
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds cannot be negative")
    current = now or datetime.now(tz=timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    normalized = sorted({str(item).strip().upper() for item in symbols if str(item).strip()})
    pending: list[str] = []
    skipped = 0
    for symbol in normalized:
        if not force and cache.is_fresh(symbol, now=current):
            skipped += 1
        else:
            pending.append(symbol)
    if max_fetch is not None:
        if max_fetch < 1:
            raise ValueError("max_fetch must be positive")
        pending = pending[:max_fetch]

    successes = 0
    failures: dict[str, str] = {}
    diagnostics: dict[str, object] = {}
    consecutive_rate_limits = 0
    for index, symbol in enumerate(pending):
        for attempt in range(rate_limit_retries + 1):
            try:
                info = fetcher.company_info(symbol)
                snapshot, diagnostic = snapshot_and_diagnostic_from_info(symbol, info, fetched_at=current)
                cache.write_symbol(snapshot)
                diagnostics[symbol] = diagnostic
                successes += 1
                consecutive_rate_limits = 0
                break
            except Exception as exc:  # preserve batch progress and record the real exception type
                rate_limited = "rate limit" in str(exc).lower() or "too many requests" in str(exc).lower()
                if rate_limited and attempt < rate_limit_retries:
                    sleep(rate_limit_backoff_seconds * (attempt + 1))
                    continue
                failures[symbol] = f"{type(exc).__name__}: {exc}"
                diagnostics[symbol] = {"company": "failed", "error": failures[symbol]}
                cache.append_error(symbol, exc, occurred_at=current)
                consecutive_rate_limits = consecutive_rate_limits + 1 if rate_limited else 0
                break
        if rate_limit_circuit_breaker and consecutive_rate_limits >= rate_limit_circuit_breaker:
            diagnostics["__batch__"] = {"state": "rate_limit_circuit_open", "consecutive_rate_limits": consecutive_rate_limits, "resume_policy": "rerun_cache_first_after_cooldown"}
            break
        if request_delay_seconds and index < len(pending) - 1:
            sleep(request_delay_seconds)

    cache.write_diagnostics(diagnostics)
    cache.rebuild_canonical_output(generated_at=current)
    return YahooCompanyRefreshReport(
        requested=skipped + len(pending),
        fetched=len(pending),
        succeeded=successes,
        skipped_cached_before_request=skipped,
        failed=len(failures),
        failures=failures,
        cache_ttl_days=cache.ttl_days,
        output_path=str(cache.canonical_output_path),
        symbol_cache_root=str(cache.symbol_cache_root),
        diagnostic_path=str(cache.diagnostic_path),
        error_log_path=str(cache.error_log_path),
    )


def snapshot_from_info(symbol: str, info: Mapping[str, object], *, fetched_at: datetime) -> YahooCompanySnapshot:
    snapshot, _ = snapshot_and_diagnostic_from_info(symbol, info, fetched_at=fetched_at)
    return snapshot


def snapshot_and_diagnostic_from_info(
    symbol: str, info: Mapping[str, object], *, fetched_at: datetime
) -> tuple[YahooCompanySnapshot, dict[str, object]]:
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("fetched_at must be timezone-aware")
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol cannot be empty")

    fast = _as_mapping(info.get("__fast_info__"))
    calendar = _as_mapping(info.get("__calendar__"))
    earnings = info.get("__earnings_estimate__")
    revenue_estimate = info.get("__revenue_estimate__")
    financials = info.get("__financials__")

    values: dict[str, object] = {}
    sources: dict[str, str] = {}

    def resolve(field: str, candidates: list[tuple[str, object]], converter: Callable[[object], object | None]) -> object | None:
        for index, (source, candidate) in enumerate(candidates):
            value = converter(candidate)
            if value is not None:
                values[field] = value
                sources[field] = "ok" if index == 0 else "fallback"
                return value
        values[field] = None
        sources[field] = "missing"
        return None

    company_name = resolve("company_name", [("info.longName", info.get("longName")), ("info.shortName", info.get("shortName")), ("fast_info.longName", fast.get("longName"))], _text)
    summary = resolve("summary", [("info.longBusinessSummary", info.get("longBusinessSummary")), ("info.description", info.get("description"))], _text)
    market_cap = resolve("market_cap", [("info.marketCap", info.get("marketCap")), ("fast_info.marketCap", fast.get("marketCap") or fast.get("market_cap"))], _decimal_text)
    previous_close = _first_decimal(info.get("previousClose"), fast.get("previousClose"), fast.get("previous_close"))
    implied_shares = _divide_decimal(market_cap, previous_close)
    shares = resolve("shares", [("info.sharesOutstanding", info.get("sharesOutstanding")), ("info.impliedSharesOutstanding", info.get("impliedSharesOutstanding")), ("market_cap/previous_close", implied_shares)], _decimal_text)
    forward_eps = resolve("forward_eps", [("earnings_estimate.avg", _estimate_value(earnings, ("avg", "Average"))), ("info.forwardEps", info.get("forwardEps"))], _decimal_text)
    revenue_ttm = resolve("revenue_ttm", [("info.totalRevenue", info.get("totalRevenue")), ("financials.Total Revenue", _financial_value(financials, ("Total Revenue", "TotalRevenue")))], _decimal_text)
    forward_revenue = resolve("forward_revenue", [("revenue_estimate.avg", _estimate_value(revenue_estimate, ("avg", "Average"))), ("calendar.revenueAverage", calendar.get("revenueAverage")), ("financials.Total Revenue", _financial_value(financials, ("Total Revenue", "TotalRevenue")))], _decimal_text)

    essential = (company_name, market_cap, shares, revenue_ttm, forward_eps)
    present = sum(value is not None for value in essential)
    confidence = "high" if present >= 4 else "medium" if present >= 2 else "low"

    snapshot = YahooCompanySnapshot(
        symbol=normalized,
        provider="yahoo_finance",
        fetched_at=fetched_at.isoformat(),
        last_refresh=fetched_at.isoformat(),
        confidence=confidence,
        company_name=company_name,
        business_summary=summary,
        summary=summary,
        sector=_text(info.get("sector")),
        industry=_text(info.get("industry")),
        country=_text(info.get("country")),
        website=_text(info.get("website")),
        currency=_text(info.get("financialCurrency") or info.get("currency") or fast.get("currency")),
        exchange=_text(info.get("fullExchangeName") or info.get("exchange") or fast.get("exchange")),
        quote_type=_text(info.get("quoteType") or fast.get("quoteType")),
        employees=_integer(info.get("fullTimeEmployees")),
        market_cap=market_cap,
        enterprise_value=_decimal_text(info.get("enterpriseValue")),
        shares_outstanding=shares,
        revenue_ttm=revenue_ttm,
        gross_profit_ttm=_decimal_text(info.get("grossProfits")),
        ebitda_ttm=_decimal_text(info.get("ebitda")),
        net_income_ttm=_decimal_text(info.get("netIncomeToCommon")),
        operating_cash_flow_ttm=_decimal_text(info.get("operatingCashflow")),
        free_cash_flow_ttm=_decimal_text(info.get("freeCashflow")),
        total_cash=_decimal_text(info.get("totalCash")),
        total_debt=_decimal_text(info.get("totalDebt")),
        trailing_eps=_decimal_text(info.get("trailingEps")),
        forward_eps=forward_eps,
        forward_eps_growth=_decimal_text(info.get("earningsGrowth")),
        forward_revenue=forward_revenue,
        trailing_pe=_decimal_text(info.get("trailingPE")),
        forward_pe=_decimal_text(info.get("forwardPE")),
        price_to_book=_decimal_text(info.get("priceToBook")),
        enterprise_to_revenue=_decimal_text(info.get("enterpriseToRevenue")),
        enterprise_to_ebitda=_decimal_text(info.get("enterpriseToEbitda")),
        beta=_decimal_text(info.get("beta")),
        analyst_target_mean=_decimal_text(info.get("targetMeanPrice")),
        analyst_count=_integer(info.get("numberOfAnalystOpinions")),
        previous_close=_decimal_text(previous_close),
    )
    diagnostic: dict[str, object] = {
        "company_name": sources["company_name"],
        "market_cap": sources["market_cap"],
        "shares": sources["shares"],
        "forward_eps": sources["forward_eps"],
        "forward_revenue": sources["forward_revenue"],
        "revenue_ttm": sources["revenue_ttm"],
        "summary": sources["summary"],
        "confidence": confidence,
    }
    endpoint_errors = info.get("__endpoint_errors__")
    if isinstance(endpoint_errors, Mapping) and endpoint_errors:
        diagnostic["endpoint_errors"] = json_safe(endpoint_errors)
    return snapshot, diagnostic


def json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().isoformat()
        except (TypeError, ValueError, AttributeError):
            pass
    return str(value)


def _as_mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "items"):
        try:
            return {str(key): item for key, item in value.items()}
        except Exception:
            return {}
    return {}


def _estimate_value(payload: object, keys: tuple[str, ...]) -> object:
    if not isinstance(payload, Mapping):
        return None
    preferred_rows = ("0y", "+1y", "current", "Current Year", "nextYear", "Next Year")
    for row_name in preferred_rows:
        row = payload.get(row_name)
        if isinstance(row, Mapping):
            for key in keys:
                if row.get(key) is not None:
                    return row[key]
    for row in payload.values():
        if isinstance(row, Mapping):
            for key in keys:
                if row.get(key) is not None:
                    return row[key]
    return None


def _financial_value(payload: object, names: tuple[str, ...]) -> object:
    if not isinstance(payload, Mapping):
        return None
    for name in names:
        row = payload.get(name)
        if isinstance(row, Mapping):
            for value in row.values():
                if value is not None:
                    return value
        elif row is not None:
            return row
    return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _decimal_text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal = Decimal(str(value))
        if not decimal.is_finite():
            return None
        return format(decimal, "f")
    except (InvalidOperation, ValueError, TypeError):
        return None


def _integer(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_decimal(*values: object) -> Decimal | None:
    for value in values:
        text = _decimal_text(value)
        if text is not None:
            return Decimal(text)
    return None


def _divide_decimal(numerator: object, denominator: object) -> Decimal | None:
    numerator_text = _decimal_text(numerator)
    denominator_text = _decimal_text(denominator)
    if numerator_text is None or denominator_text is None:
        return None
    denominator_decimal = Decimal(denominator_text)
    if denominator_decimal == 0:
        return None
    return Decimal(numerator_text) / denominator_decimal
