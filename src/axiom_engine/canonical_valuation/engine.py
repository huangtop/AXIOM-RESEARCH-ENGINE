from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .models import BatchValuationReport, CompanyValuationResult, ModelResult, ReadinessItem, ReadinessReport

DCF_FACTS = ("free_cash_flow", "cash_and_cash_equivalents", "total_debt", "diluted_shares_outstanding")
DCF_ASSUMPTIONS = ("fcf_growth_rate", "discount_rate", "terminal_growth_rate")
MULTIPLE_FACTS = ("diluted_shares_outstanding",)
MULTIPLE_ESTIMATES = ("eps_diluted",)
MULTIPLE_ASSUMPTIONS = ("forward_pe",)


class CanonicalValuationError(RuntimeError):
    pass


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalValuationError(f"cannot read canonical input: {path}") from exc


def _decimal(value: Any, label: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CanonicalValuationError(f"invalid decimal for {label}: {value}") from exc


def _latest(records: Iterable[dict[str, Any]], date_key: str) -> dict[str, Any] | None:
    values = list(records)
    if not values:
        return None
    return sorted(values, key=lambda row: (str(row.get(date_key, "")), str(row.get("financial_fact_id", row.get("estimate_id", row.get("assumption_id", ""))))))[-1]


def load_canonical_inputs(financial_dir: str | Path, estimate_dir: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    financial_root = Path(financial_dir)
    estimate_root = Path(estimate_dir)
    facts = _read(financial_root / "financial_facts.json")
    estimates = _read(estimate_root / "estimates.json")
    assumptions = _read(estimate_root / "forward_assumptions.json")
    if not all(isinstance(value, list) for value in (facts, estimates, assumptions)):
        raise CanonicalValuationError("canonical inputs must be JSON arrays")
    return facts, estimates, assumptions


def _index(records: list[dict[str, Any]], id_key: str) -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        result[str(record["company_id"])][str(record[id_key])].append(record)
    return result


def valuation_readiness(
    *,
    financial_dir: str | Path = "data/financial_data",
    estimate_dir: str | Path = "data/estimate_data",
    company_ids: list[str] | None = None,
    required_company_count: int = 100,
) -> ReadinessReport:
    facts, estimates, assumptions = load_canonical_inputs(financial_dir, estimate_dir)
    fact_index = _index(facts, "metric")
    estimate_index = _index(estimates, "metric")
    approved = [row for row in assumptions if row.get("status") == "approved"]
    assumption_index = _index(approved, "metric")
    companies = sorted(set(company_ids or []) or (set(fact_index) | set(estimate_index) | set(assumption_index)))
    items: list[ReadinessItem] = []
    ready_count = partial_count = unavailable_count = 0
    for company_id in companies:
        missing_dcf = [f"fact:{name}" for name in DCF_FACTS if name not in fact_index[company_id]]
        missing_dcf += [f"assumption:{name}" for name in DCF_ASSUMPTIONS if name not in assumption_index[company_id]]
        missing_multiple = [f"fact:{name}" for name in MULTIPLE_FACTS if name not in fact_index[company_id]]
        missing_multiple += [f"estimate:{name}" for name in MULTIPLE_ESTIMATES if name not in estimate_index[company_id]]
        missing_multiple += [f"assumption:{name}" for name in MULTIPLE_ASSUMPTIONS if name not in assumption_index[company_id]]
        ready_models = []
        if not missing_dcf:
            ready_models.append("discounted_cash_flow")
        if not missing_multiple:
            ready_models.append("forward_earnings_multiple")
        if len(ready_models) == 2:
            ready_count += 1
        elif ready_models:
            partial_count += 1
        else:
            unavailable_count += 1
        items.append(ReadinessItem(company_id=company_id, ready_models=ready_models, missing_inputs={"discounted_cash_flow": missing_dcf, "forward_earnings_multiple": missing_multiple}, ready=len(ready_models) == 2))
    return ReadinessReport(
        companies_checked=len(companies),
        companies_ready=ready_count,
        companies_partial=partial_count,
        companies_unavailable=unavailable_count,
        required_company_count=required_company_count,
        acceptance_passed=len(companies) >= required_company_count and ready_count >= required_company_count,
        items=items,
    )


def _dcf(company_id: str, facts: dict[str, list[dict[str, Any]]], assumptions: dict[str, list[dict[str, Any]]], horizon: int = 5) -> ModelResult:
    missing = [name for name in DCF_FACTS if name not in facts] + [name for name in DCF_ASSUMPTIONS if name not in assumptions]
    if missing:
        return ModelResult(model_name="discounted_cash_flow", status="unavailable", warnings=["missing: " + ", ".join(missing)])
    chosen_facts = {name: _latest(facts[name], "period_end") for name in DCF_FACTS}
    chosen_assumptions = {name: _latest(assumptions[name], "effective_date") for name in DCF_ASSUMPTIONS}
    fcf = _decimal(chosen_facts["free_cash_flow"]["value"], "free_cash_flow")
    cash = _decimal(chosen_facts["cash_and_cash_equivalents"]["value"], "cash")
    debt = _decimal(chosen_facts["total_debt"]["value"], "debt")
    shares = _decimal(chosen_facts["diluted_shares_outstanding"]["value"], "shares")
    growth = _decimal(chosen_assumptions["fcf_growth_rate"]["value"], "fcf_growth_rate")
    discount = _decimal(chosen_assumptions["discount_rate"]["value"], "discount_rate")
    terminal_growth = _decimal(chosen_assumptions["terminal_growth_rate"]["value"], "terminal_growth_rate")
    if shares <= 0 or discount <= terminal_growth or discount <= 0:
        return ModelResult(model_name="discounted_cash_flow", status="unavailable", warnings=["invalid DCF denominator or share count"])
    pv = Decimal("0")
    projected = fcf
    for year in range(1, horizon + 1):
        projected *= Decimal("1") + growth
        pv += projected / ((Decimal("1") + discount) ** year)
    terminal = projected * (Decimal("1") + terminal_growth) / (discount - terminal_growth)
    enterprise_value = pv + terminal / ((Decimal("1") + discount) ** horizon)
    equity_value = enterprise_value + cash - debt
    fair_value = equity_value / shares
    source_ids = [chosen_facts[name]["financial_fact_id"] for name in DCF_FACTS] + [chosen_assumptions[name]["assumption_id"] for name in DCF_ASSUMPTIONS]
    return ModelResult(model_name="discounted_cash_flow", status="completed", fair_value_per_share=fair_value, currency=chosen_facts["free_cash_flow"].get("currency"), inputs={"free_cash_flow": fcf, "cash": cash, "debt": debt, "shares": shares, "fcf_growth_rate": growth, "discount_rate": discount, "terminal_growth_rate": terminal_growth, "forecast_years": horizon}, source_record_ids=source_ids)


def _multiple(company_id: str, facts: dict[str, list[dict[str, Any]]], estimates: dict[str, list[dict[str, Any]]], assumptions: dict[str, list[dict[str, Any]]]) -> ModelResult:
    missing = [name for name in MULTIPLE_FACTS if name not in facts] + [name for name in MULTIPLE_ESTIMATES if name not in estimates] + [name for name in MULTIPLE_ASSUMPTIONS if name not in assumptions]
    if missing:
        return ModelResult(model_name="forward_earnings_multiple", status="unavailable", warnings=["missing: " + ", ".join(missing)])
    eps_record = _latest(estimates["eps_diluted"], "period_end")
    pe_record = _latest(assumptions["forward_pe"], "effective_date")
    eps = _decimal(eps_record["value"], "eps_diluted")
    forward_pe = _decimal(pe_record["value"], "forward_pe")
    if eps <= 0 or forward_pe <= 0:
        return ModelResult(model_name="forward_earnings_multiple", status="unavailable", warnings=["EPS and forward P/E must be positive"])
    fair_value = eps * forward_pe
    return ModelResult(model_name="forward_earnings_multiple", status="completed", fair_value_per_share=fair_value, currency=eps_record.get("currency"), inputs={"forward_eps": eps, "forward_pe": forward_pe, "fiscal_year": eps_record["fiscal_year"]}, source_record_ids=[eps_record["estimate_id"], pe_record["assumption_id"]])


def value_company(company_id: str, *, facts: list[dict[str, Any]], estimates: list[dict[str, Any]], assumptions: list[dict[str, Any]], as_of_date: date) -> CompanyValuationResult:
    fact_index = _index(facts, "metric")[company_id]
    estimate_index = _index(estimates, "metric")[company_id]
    assumption_index = _index([row for row in assumptions if row.get("status") == "approved"], "metric")[company_id]
    dcf = _dcf(company_id, fact_index, assumption_index)
    multiple = _multiple(company_id, fact_index, estimate_index, assumption_index)
    models = [dcf, multiple]
    completed = [item for item in models if item.status == "completed"]
    status = "completed" if len(completed) == len(models) else "partial" if completed else "unavailable"
    blended = sum((item.fair_value_per_share for item in completed if item.fair_value_per_share is not None), Decimal("0")) / Decimal(len(completed)) if completed else None
    currency = next((item.currency for item in completed if item.currency), "USD")
    return CompanyValuationResult(valuation_result_id=f"canonical_valuation_result:{company_id.split(':', 1)[1]}:{as_of_date.isoformat()}", company_id=company_id, as_of_date=as_of_date, currency=currency, status=status, models=models, blended_fair_value_per_share=blended)


def run_batch_valuation(*, financial_dir: str | Path = "data/financial_data", estimate_dir: str | Path = "data/estimate_data", output_dir: str | Path = "data/canonical_valuation", company_ids: list[str] | None = None, as_of_date: date | None = None, dry_run: bool = True) -> BatchValuationReport:
    facts, estimates, assumptions = load_canonical_inputs(financial_dir, estimate_dir)
    companies = sorted(set(company_ids or []) or ({row["company_id"] for row in facts} | {row["company_id"] for row in estimates} | {row["company_id"] for row in assumptions}))
    valuation_date = as_of_date or date.today()
    results = [value_company(company_id, facts=facts, estimates=estimates, assumptions=assumptions, as_of_date=valuation_date) for company_id in companies]
    results.sort(key=lambda row: row.company_id)
    manifest = {"schema_version": "1.0.0", "engine": "canonical_valuation", "as_of_date": valuation_date.isoformat(), "company_count": len(results), "completed": sum(x.status == "completed" for x in results), "partial": sum(x.status == "partial" for x in results), "unavailable": sum(x.status == "unavailable" for x in results), "uses_current_price": False, "uses_legacy_valuation": False}
    target = Path(output_dir)
    written: list[str] = []
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        for name, payload in (("valuation_results.json", [x.model_dump(mode="json", exclude_none=True) for x in results]), ("manifest.json", manifest)):
            _atomic_write(target / name, payload)
            written.append(str(target / name))
    return BatchValuationReport(as_of_date=valuation_date, companies_requested=len(companies), completed=manifest["completed"], partial=manifest["partial"], unavailable=manifest["unavailable"], output_directory=str(target), written_files=written)


def _atomic_write(path: Path, payload: Any) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
