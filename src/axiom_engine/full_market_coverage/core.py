from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile

from axiom_engine.seven_model_valuation import calculate_seven_models
from axiom_engine.coverage_policy import CoveragePolicyService


MODELS = ("dcf", "forward_pe", "peg", "forward_ps", "ev_ebitda", "forward_pb", "milestone")


class FullMarketCoverageError(RuntimeError):
    pass


class FullMarketCoverageNotFound(FullMarketCoverageError):
    pass


def _load(path: Path, *, default: Any = None) -> Any:
    if not path.is_file() and default is not None:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FullMarketCoverageError(f"cannot read {path}: {exc}") from exc


def _number(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _latest(rows: list[Mapping[str, Any]], metric_field: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        metric = str(row.get(metric_field) or "").strip().lower()
        if not metric:
            continue
        current = result.get(metric)
        key = str(row.get("period_end") or row.get("as_of_date") or row.get("observed_at") or "")
        old = str((current or {}).get("period_end") or (current or {}).get("as_of_date") or (current or {}).get("observed_at") or "")
        if key >= old:
            result[metric] = row
    return result


def _metric(row: Mapping[str, Any] | None, *, source_id_field: str) -> dict[str, Any]:
    if not row:
        return {"status": "unavailable", "value": None, "reason_code": "canonical_metric_not_populated", "source_record_ids": []}
    return {
        "status": "ready",
        "value": str(row.get("value")),
        "unit": row.get("unit"),
        "currency": row.get("currency"),
        "as_of_date": row.get("period_end") or row.get("as_of_date"),
        "reason_code": None,
        "source_record_ids": [row.get(source_id_field)] if row.get(source_id_field) else [],
    }


def _derived(value: Decimal | None, formula: str, source_ids: list[str], reason: str) -> dict[str, Any]:
    return {
        "status": "ready" if value is not None else "unavailable",
        "value": format(value, "f") if value is not None else None,
        "reason_code": None if value is not None else reason,
        "formula_version": formula,
        "source_record_ids": source_ids,
    }


def _quarterly_history(rows: list[Mapping[str, Any]], limit: int = 8) -> dict[str, Any]:
    by_period: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        fiscal_period = str(row.get("fiscal_period") or "").upper()
        if fiscal_period not in {"Q1", "Q2", "Q3", "Q4"}:
            continue
        period_end = str(row.get("period_end") or "")
        fiscal_year = int(period_end[:4] or 0)
        metric = str(row.get("metric") or "")
        if not fiscal_year or not period_end or not metric:
            continue
        period = by_period.setdefault(
            (fiscal_period, period_end),
            {
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period,
                "period_end": period_end,
                "filed_at": row.get("filed_at"),
                "form_type": row.get("form_type"),
                "accession_number": row.get("accession_number"),
                "metrics": {},
            },
        )
        period["metrics"][metric] = _metric(row, source_id_field="financial_fact_id")
    periods = sorted(by_period.values(), key=lambda row: str(row["period_end"]))[-limit:]
    return {
        "status": "ready" if periods else "unavailable",
        "quarter_count": len(periods),
        "requested_quarter_count": limit,
        "periods": periods,
        "reason_code": None if periods else "QUARTERLY_FINANCIAL_HISTORY_NOT_POPULATED",
    }


def build_full_market_coverage(
    root: Path,
    *,
    companies_path: str = "data/universe/companies.json",
    securities_path: str = "data/universe/securities.json",
    financial_path: str = "data/generated/canonical_financial_population/financial_facts.json",
    quarterly_financial_path: str = "data/generated/canonical_financial_population/quarterly_index.json",
    market_path: str = "data/generated/market/previous_close_cache.json",
    estimate_path: str = "data/estimate_data/consensus_estimates.json",
    security_identity_path: str = "data/generated/security_identity/security_identity_normalization.json",
    valuation_assumptions_path: str = "data/knowledge/valuation_assumptions.json",
    dcf_policy_path: str = "config/fair_value_snapshot.v030.14.0.json",
) -> dict[str, Any]:
    companies = _load(root / companies_path)
    securities = _load(root / securities_path)
    financials = _load(root / financial_path, default=[])
    quarterly_payload = _load(root / quarterly_financial_path, default={})
    market_payload = _load(root / market_path, default={"symbols": {}})
    estimates = _load(root / estimate_path, default=[])
    identity = _load(root / security_identity_path, default={"companies": [], "securities": []})
    assumption_rows = _load(root / valuation_assumptions_path, default=[])
    dcf_policy_payload = _load(root / dcf_policy_path)
    dcf_policy = dcf_policy_payload.get("dcf", {})
    if not all(isinstance(rows, list) for rows in (companies, securities, financials, estimates, assumption_rows)):
        raise FullMarketCoverageError("population and canonical layers must contain arrays")

    scoped_company_ids = {
        str(row.get("company_id"))
        for row in identity.get("companies", [])
        if row.get("valuation_scope_status") == "included"
    }
    eligible_security_ids = {
        str(row.get("security_id"))
        for row in identity.get("securities", [])
        if row.get("valuation_eligible") is True
    }
    if not scoped_company_ids:
        scoped_company_ids = {str(row.get("company_id")) for row in companies}
    if not eligible_security_ids:
        eligible_security_ids = {str(row.get("security_id")) for row in securities}
    securities_by_company: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in securities:
        if row.get("status") in (None, "active") and str(row.get("security_id")) in eligible_security_ids:
            securities_by_company[str(row.get("company_id") or "")].append(row)
    financial_by_company: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in financials:
        financial_by_company[str(row.get("company_id") or "")].append(row)
    quarterly_files = quarterly_payload.get("company_id_to_file") if isinstance(quarterly_payload, Mapping) else {}
    quarterly_files = quarterly_files if isinstance(quarterly_files, Mapping) else {}
    estimates_by_company: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in estimates:
        estimates_by_company[str(row.get("company_id") or "")].append(row)
    assumptions_by_company = {
        str(row.get("company_id")): row.get("assumptions") or {}
        for row in assumption_rows
        if row.get("company_id") and row.get("evidence_ids")
    }
    market_symbols = market_payload.get("symbols") if isinstance(market_payload, Mapping) else {}
    market_symbols = market_symbols if isinstance(market_symbols, Mapping) else {}

    cards: list[dict[str, Any]] = []
    ticker_index: dict[str, int] = {}
    model_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    for company in sorted(companies, key=lambda row: str(row.get("company_id") or "")):
        company_id = str(company.get("company_id") or "")
        if company_id not in scoped_company_ids:
            continue
        company_securities = securities_by_company.get(company_id, [])
        primary = next((row for row in company_securities if row.get("security_id") == company.get("primary_security_id")), None)
        primary = primary or next((row for row in company_securities if row.get("primary_listing") is True), None)
        primary = primary or (company_securities[0] if company_securities else {})
        ticker = str(primary.get("ticker") or "").upper()

        latest_fin = _latest(financial_by_company.get(company_id, []), "metric")
        fin = {name: _metric(latest_fin.get(name), source_id_field="financial_fact_id") for name in (
            "revenue", "net_income", "operating_cash_flow", "capital_expenditures", "cash_and_cash_equivalents", "total_debt", "diluted_shares_outstanding", "ebitda", "book_value_per_share",
        )}
        net_income = _number((latest_fin.get("net_income") or {}).get("value"))
        shares = _number((latest_fin.get("diluted_shares_outstanding") or {}).get("value"))
        eps_ids = [str((latest_fin.get(name) or {}).get("financial_fact_id")) for name in ("net_income", "diluted_shares_outstanding") if (latest_fin.get(name) or {}).get("financial_fact_id")]
        fin["trailing_eps"] = _derived(net_income / shares if net_income is not None and shares and shares > 0 else None, "trailing_eps.v031.0", eps_ids, "EPS_INPUTS_UNAVAILABLE")
        ocf = latest_fin.get("operating_cash_flow") or {}
        capex = latest_fin.get("capital_expenditures") or {}
        same_period = bool(ocf and capex and ocf.get("fiscal_year") == capex.get("fiscal_year") and ocf.get("fiscal_period") == capex.get("fiscal_period"))
        ocf_value, capex_value = _number(ocf.get("value")), _number(capex.get("value"))
        fcf_ids = [str(row.get("financial_fact_id")) for row in (ocf, capex) if row.get("financial_fact_id")]
        fin["free_cash_flow"] = _derived(ocf_value - abs(capex_value) if same_period and ocf_value is not None and capex_value is not None else None, "free_cash_flow.v031.0", fcf_ids, "FCF_PERIOD_MISMATCH" if ocf and capex else "FCF_INPUTS_UNAVAILABLE")

        latest_est = _latest(estimates_by_company.get(company_id, []), "metric")
        est = {name: _metric(latest_est.get(name), source_id_field="estimate_id") for name in (
            "forward_eps", "forward_eps_growth", "forward_revenue", "forward_ebitda", "ebitda_ttm", "milestone_probability", "milestone_value",
        )}
        market_row = market_symbols.get(ticker) if ticker else None
        market = {
            "status": "ready" if isinstance(market_row, Mapping) and _number(market_row.get("close")) is not None else "unavailable",
            "current_price": str(market_row.get("close")) if isinstance(market_row, Mapping) and market_row.get("close") is not None else None,
            "currency": market_row.get("currency") if isinstance(market_row, Mapping) else primary.get("currency"),
            "as_of_date": market_row.get("session_date") if isinstance(market_row, Mapping) else None,
            "reason_code": None if isinstance(market_row, Mapping) else "CANONICAL_MARKET_NOT_POPULATED",
        }
        models = calculate_seven_models(
            fin,
            est,
            assumptions_by_company.get(company_id, {}),
            dcf_policy=dcf_policy,
        )
        calculated_values = [Decimal(row["fair_value"]) for row in models.values() if row["status"] == "calculated"]
        calculated_count = len(calculated_values)
        model_counts.update(name for name, row in models.items() if row["status"] == "calculated")
        status = "ready" if calculated_count >= 2 else "partial" if calculated_count == 1 else "unavailable"
        status_counts[status] += 1
        card = {
            "schema_version": "full-market-valuation-card.v031.0",
            "company": {"company_id": company_id, "display_name": company.get("display_name"), "legal_name": company.get("legal_name"), "country": company.get("country"), "business_summary": None, "business_summary_reason_code": "CANONICAL_BUSINESS_SUMMARY_NOT_POPULATED"},
            "primary_security": {"security_id": primary.get("security_id"), "ticker": ticker or None, "exchange": primary.get("exchange"), "currency": primary.get("currency")},
            "securities": [{"security_id": row.get("security_id"), "ticker": row.get("ticker"), "exchange": row.get("exchange"), "primary_listing": row.get("primary_listing")} for row in company_securities],
            "status": status,
            "market": market,
            "financials": fin,
            "financial_history": _quarterly_history(
                _load((root / quarterly_financial_path).parent / str(quarterly_files[company_id]), default=[])
                if company_id in quarterly_files
                else []
            ),
            "estimates": est,
            "valuation": {"status": status, "calculated_model_count": calculated_count, "total_model_count": 7, "fair_value": format(sum(calculated_values) / len(calculated_values), "f") if calculated_values else None, "aggregation_version": "equal-weight-calculated-models.v031v.5", "reason_code": None if calculated_values else "NO_CALCULATED_MODELS", "models": models},
        }
        position = len(cards)
        cards.append(card)
        for row in company_securities:
            symbol = str(row.get("ticker") or "").upper()
            if symbol:
                ticker_index.setdefault(symbol, position)

    return {
        "schema_version": "full-market-coverage.v031.0",
        "version": "V031.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"company_count": len(cards), "registry_company_count": len(companies), "excluded_non_company_instrument_count": len(companies) - len(cards), "security_count": len(securities), "valuation_security_count": len(eligible_security_ids), "status_counts": {name: status_counts[name] for name in ("ready", "partial", "unavailable")}, "model_calculated_counts": {name: model_counts[name] for name in MODELS}, "market_ready_company_count": sum(card["market"]["status"] == "ready" for card in cards), "financial_present_company_count": sum(bool(financial_by_company.get(card["company"]["company_id"])) for card in cards), "estimate_present_company_count": sum(bool(estimates_by_company.get(card["company"]["company_id"])) for card in cards)},
        "cards": cards,
        "indexes": {"ticker_to_position": ticker_index, "company_id_to_position": {card["company"]["company_id"]: index for index, card in enumerate(cards)}},
    }


def write_full_market_coverage(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    company_root = output.parent / "per-company"
    company_root.mkdir(parents=True, exist_ok=True)
    ticker_to_file: dict[str, str] = {}
    company_id_to_file: dict[str, str] = {}
    for card in report.get("cards") or []:
        company_id = str((card.get("company") or {}).get("company_id") or "")
        ticker = str((card.get("primary_security") or {}).get("ticker") or "").upper()
        if not company_id:
            continue
        filename = quote(company_id, safe="._-") + ".json"
        path = company_root / filename
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(card, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        company_id_to_file[company_id] = f"per-company/{filename}"
        if ticker:
            ticker_to_file[ticker] = f"per-company/{filename}"

    index = {
        "schema_version": "full-market-valuation-index.v031g.1",
        "version": "V031G.1",
        "generated_at": report.get("generated_at"),
        "summary": dict(report.get("summary") or {}),
        "indexes": {
            "ticker_to_file": dict(sorted(ticker_to_file.items())),
            "company_id_to_file": dict(sorted(company_id_to_file.items())),
        },
    }
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


class FullMarketCoverageService:
    def __init__(self, *, root: Path | None = None, snapshot_path: Path | None = None, coverage_service: CoveragePolicyService | None = None, publication_root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.snapshot_path = snapshot_path or self.root / "data/generated/full_market_coverage/full_market_coverage.json"
        self.coverage_service = coverage_service or CoveragePolicyService(root=self.root)
        self.publication_root = publication_root or self.root / "data/generated/publication_gate"
        self._payload: Mapping[str, Any] | None = None
        self._catalog: Mapping[str, Any] | None = None

    def _get_payload(self) -> Mapping[str, Any]:
        if self._payload is None:
            self._payload = _load(self.snapshot_path) if self.snapshot_path.is_file() else build_full_market_coverage(self.root)
        return self._payload

    def list(self) -> dict[str, Any]:
        catalog_path = self.publication_root / "company_catalog.json"
        if catalog_path.is_file():
            if self._catalog is None:
                self._catalog = _load(catalog_path)
            if self._catalog.get("schema_version") == "publication-gate-catalog.v031f.2.1":
                companies = [
                    {"company_id": row["company_id"], "ticker": row["ticker"], "display_name": row.get("display_name"), "status": row.get("valuation_status")}
                    for row in self._catalog.get("companies") or []
                ]
                return {"schema_version": "published-company-list.v031f.2.1", "version": "V031F.2.1", "summary": {"company_count": len(companies), "publication_gate": "coverage-policy.v031f.2.1", "source": "compact_publication_catalog"}, "companies": companies}
        payload = self._get_payload()
        public_ids = self.coverage_service.public_company_ids()
        companies = [
            {"company_id": card["company"]["company_id"], "ticker": card["primary_security"]["ticker"], "display_name": card["company"]["display_name"], "status": card["status"]}
            for card in payload["cards"] if card["company"]["company_id"] in public_ids
        ]
        summary = {
            "company_count": len(companies),
            "source_company_count": payload["summary"].get("company_count"),
            "registry_company_count": payload["summary"].get("registry_company_count"),
            "publication_gate": "coverage-policy.v031f.1",
        }
        return {"schema_version": "published-company-list.v031f.2", "version": "V031F.2", "summary": summary, "companies": companies}

    def get(self, ticker: str) -> Mapping[str, Any]:
        symbol = str(ticker or "").strip().upper()
        coverage = self.coverage_service.require_public(symbol, capability="valuation_card")
        catalog_path = self.publication_root / "company_catalog.json"
        if catalog_path.is_file():
            if self._catalog is None:
                self._catalog = _load(catalog_path)
            filename = (self._catalog.get("indexes") or {}).get("ticker_to_file", {}).get(symbol)
            if filename:
                loose_projection = self.publication_root / "companies" / filename
                if loose_projection.is_file():
                    projection = _load(loose_projection)
                else:
                    archive = self.publication_root / "company_projections.zip"
                    try:
                        with ZipFile(archive) as bundle:
                            projection = json.loads(bundle.read(filename))
                    except (OSError, KeyError, BadZipFile, json.JSONDecodeError) as exc:
                        raise FullMarketCoverageError(f"cannot read company projection for {symbol}: {exc}") from exc
                card = projection.get("valuation_card")
                if isinstance(card, Mapping):
                    return {**card, "coverage_policy": {"product_scope": projection.get("product_scope"), "research_scope": projection.get("research_scope"), "scope_axes": projection.get("scope_axes") or {}, "reason_codes": (projection.get("coverage_policy") or {}).get("reason_codes") or []}}
        payload = self._get_payload()
        filename = payload.get("indexes", {}).get("ticker_to_file", {}).get(symbol)
        if filename:
            card_path = self.snapshot_path.parent / str(filename)
            if not card_path.is_file():
                raise FullMarketCoverageNotFound(
                    f"valuation artifact missing for ticker {symbol}: {card_path}"
                )
            card = _load(card_path)
            return {**card, "coverage_policy": {
                "publication_tier": coverage.get("publication_tier"),
                "reason_codes": coverage.get("reason_codes") or [],
            }}
        position = payload.get("indexes", {}).get("ticker_to_position", {}).get(symbol)
        if position is None:
            raise FullMarketCoverageNotFound(f"ticker not found in full-market population: {symbol}")
        return {**payload["cards"][position], "coverage_policy": {
            "publication_tier": coverage.get("publication_tier"),
            "reason_codes": coverage.get("reason_codes") or [],
        }}
