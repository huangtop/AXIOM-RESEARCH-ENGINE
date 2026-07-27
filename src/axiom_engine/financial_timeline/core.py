from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


class FinancialTimelineError(RuntimeError):
    """Raised when financial timeline input is missing or structurally invalid."""


def _load(path: Path) -> Any:
    if not path.exists():
        raise FinancialTimelineError(
            f"canonical financial snapshot not found: {path}; run scripts/build_financial_bridge.py --write --strict"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _freshness(period_end: date | None, as_of: date) -> tuple[int | None, str]:
    if period_end is None:
        return None, "unknown"
    age = max(0, (as_of - period_end).days)
    if age <= 180:
        return age, "fresh"
    if age <= 365:
        return age, "current"
    return age, "stale"


def _fact_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return (str(row.get("period_end") or ""), int(row.get("fiscal_year") or 0), str(row.get("financial_fact_id") or ""))


def build_financial_timeline(
    repository_root: Path,
    *,
    financial_snapshot_path: str = "data/generated/financial_bridge/canonical_financial_snapshot.json",
    as_of_date: str | None = None,
) -> dict[str, Any]:
    payload = _load(repository_root / financial_snapshot_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("companies"), list):
        raise FinancialTimelineError("canonical financial snapshot must contain a companies array")
    as_of = _parse_date(as_of_date) if as_of_date else datetime.now(timezone.utc).date()
    if as_of is None:
        raise FinancialTimelineError(f"invalid as_of_date: {as_of_date}")

    companies: list[dict[str, Any]] = []
    invalid_periods: list[dict[str, Any]] = []
    future_periods: list[dict[str, Any]] = []
    freshness_counts: Counter[str] = Counter()
    ttm_state_counts: Counter[str] = Counter()
    annual_period_count = quarterly_period_count = 0

    for company in payload["companies"]:
        if not isinstance(company, dict) or not company.get("company_id"):
            continue
        facts = [row for row in (company.get("facts") or []) if isinstance(row, dict)]
        annual: dict[str, list[dict[str, Any]]] = {}
        quarterly: dict[str, list[dict[str, Any]]] = {}
        instant: dict[str, dict[str, Any]] = {}
        duration_by_metric: dict[str, list[dict[str, Any]]] = {}

        for fact in facts:
            period_end = _parse_date(fact.get("period_end"))
            if period_end is None:
                invalid_periods.append({"company_id": company["company_id"], "financial_fact_id": fact.get("financial_fact_id")})
                continue
            if period_end > as_of:
                future_periods.append({"company_id": company["company_id"], "financial_fact_id": fact.get("financial_fact_id"), "period_end": period_end.isoformat()})
            fiscal_period = str(fact.get("fiscal_period") or "").upper()
            metric = str(fact.get("metric") or "")
            if fact.get("period_type") == "instant":
                prior = instant.get(metric)
                if prior is None or _fact_key(fact) > _fact_key(prior):
                    instant[metric] = fact
            else:
                duration_by_metric.setdefault(metric, []).append(fact)
            if fiscal_period == "FY":
                annual.setdefault(period_end.isoformat(), []).append(fact)
            elif fiscal_period in {"Q1", "Q2", "Q3", "Q4"}:
                quarterly.setdefault(period_end.isoformat(), []).append(fact)

        annual_rows = []
        for end, rows in sorted(annual.items()):
            annual_rows.append({
                "period_end": end,
                "period_start": min((str(r.get("period_start")) for r in rows if r.get("period_start")), default=None),
                "fiscal_year": max((int(r.get("fiscal_year") or 0) for r in rows), default=None),
                "fiscal_period": "FY",
                "form_types": sorted({str(r.get("form_type")) for r in rows if r.get("form_type")}),
                "audited": all(bool(r.get("audited")) for r in rows),
                "metrics": {r["metric"]: r for r in sorted(rows, key=lambda x: str(x.get("metric")))},
            })
        quarterly_rows = []
        for end, rows in sorted(quarterly.items()):
            quarterly_rows.append({
                "period_end": end,
                "fiscal_year": max((int(r.get("fiscal_year") or 0) for r in rows), default=None),
                "fiscal_period": sorted({str(r.get("fiscal_period")) for r in rows})[0],
                "metrics": {r["metric"]: r for r in sorted(rows, key=lambda x: str(x.get("metric")))},
            })

        latest_end = max((_parse_date(r.get("period_end")) for r in facts if _parse_date(r.get("period_end"))), default=None)
        age_days, freshness_state = _freshness(latest_end, as_of)
        freshness_counts[freshness_state] += 1

        ttm_metrics: dict[str, dict[str, Any]] = {}
        for metric, rows in sorted(duration_by_metric.items()):
            qrows = sorted([r for r in rows if str(r.get("fiscal_period") or "").upper() in {"Q1","Q2","Q3","Q4"}], key=_fact_key)
            if len(qrows) >= 4:
                chosen = qrows[-4:]
                ttm_metrics[metric] = {"value": sum(float(r["value"]) for r in chosen), "state": "four_quarter_sum", "fact_ids": [r["financial_fact_id"] for r in chosen], "period_end": chosen[-1]["period_end"]}
            else:
                fy = sorted([r for r in rows if str(r.get("fiscal_period") or "").upper() == "FY"], key=_fact_key)
                if fy:
                    chosen = fy[-1]
                    ttm_metrics[metric] = {"value": chosen["value"], "state": "annual_proxy", "fact_ids": [chosen["financial_fact_id"]], "period_end": chosen["period_end"]}
        company_ttm_state = "four_quarter_sum" if ttm_metrics and all(v["state"] == "four_quarter_sum" for v in ttm_metrics.values()) else ("annual_proxy" if ttm_metrics else "missing")
        ttm_state_counts[company_ttm_state] += 1
        annual_period_count += len(annual_rows)
        quarterly_period_count += len(quarterly_rows)
        companies.append({
            "company_id": company["company_id"],
            "cik": company.get("cik"),
            "primary_symbol": company.get("primary_symbol"),
            "display_name": company.get("display_name"),
            "latest_period_end": latest_end.isoformat() if latest_end else None,
            "age_days": age_days,
            "freshness_state": freshness_state,
            "filing_date_state": "unavailable",
            "annual_periods": annual_rows,
            "quarterly_periods": quarterly_rows,
            "instant_metrics": instant,
            "ttm": {"state": company_ttm_state, "metrics": ttm_metrics},
            "timeline_state": "ready" if annual_rows or quarterly_rows or instant else "missing",
        })

    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "financial-timeline.v030.11.1",
        "version": "V030.11.1",
        "generated_at": generated_at,
        "as_of_date": as_of.isoformat(),
        "source": {"input_path": financial_snapshot_path, "input_schema_version": payload.get("schema_version")},
        "summary": {
            "company_count": len(companies),
            "annual_period_count": annual_period_count,
            "quarterly_period_count": quarterly_period_count,
            "ttm_state_counts": dict(sorted(ttm_state_counts.items())),
            "freshness_counts": dict(sorted(freshness_counts.items())),
            "invalid_period_count": len(invalid_periods),
            "future_period_count": len(future_periods),
        },
        "companies": companies,
        "indexes": {"company_id_to_position": {row["company_id"]: i for i, row in enumerate(companies)}},
        "diagnostics": {"invalid_periods": invalid_periods, "future_periods": future_periods},
    }


def write_financial_timeline(report: dict[str, Any], output_path: Path, diagnostic_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diagnostic_path.write_text(json.dumps({
        "schema_version": "financial-timeline-diagnostic.v030.11.1",
        "version": report["version"],
        "generated_at": report["generated_at"],
        "as_of_date": report["as_of_date"],
        "summary": report["summary"],
        **report["diagnostics"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
