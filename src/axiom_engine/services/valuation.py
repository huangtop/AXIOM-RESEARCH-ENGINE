from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from ..models.valuation import (
    ExecutionStatus,
    ModelApplicability,
    ValuationBook,
    ValuationBookEntry,
    ValuationExecution,
    ValuationSnapshot,
)
from ..repository import RepositoryBundle

MODEL_VERSIONS = {
    "forward_pe": "forward_pe.v2",
    "forward_pb": "forward_pb.v1",
    "forward_ps": "forward_ps.v1",
    "ev_ebitda": "ev_ebitda.v1",
    "peg": "peg.v1",
    "milestone": "milestone.v1",
}


@dataclass(frozen=True)
class Calculation:
    fair_value: float
    market_price: float
    currency: str
    input_refs: list[str]
    inputs: dict[str, float]
    outputs: dict[str, float]


def _fact(bundle, company_id, security_id, metric, as_of_date):
    matches = [
        x
        for x in bundle.financial_facts
        if x.company_id == company_id
        and x.metric == metric
        and x.period_end <= as_of_date
        and (x.security_id is None or x.security_id == security_id)
    ]
    if not matches:
        raise ValueError(f"missing financial fact: {metric}")
    return sorted(matches, key=lambda x: x.period_end)[-1]


def _estimate(bundle, company_id, security_id, metric, scenario_type):
    matches = [
        x
        for x in bundle.estimates
        if x.company_id == company_id
        and x.metric == metric
        and x.scenario == scenario_type
        and (x.security_id is None or x.security_id == security_id)
    ]
    if not matches:
        raise ValueError(f"missing estimate: {metric}")
    return sorted(matches, key=lambda x: x.as_of_date)[-1]


def _assumption(bundle, scenario_id, key):
    try:
        return next(
            x for x in bundle.valuation_assumptions if x.scenario_id == scenario_id and x.key == key
        )
    except StopIteration as exc:
        raise ValueError(f"missing assumption: {key}") from exc


def _calculate(bundle, company_id, security_id, scenario, model_type):
    price = _fact(bundle, company_id, security_id, "market_price", scenario.as_of_date)
    if model_type == "forward_pe":
        eps = _estimate(
            bundle, company_id, security_id, "diluted_eps", scenario.scenario_type.value
        )
        multiple = _assumption(bundle, scenario.scenario_id, "target_pe")
        return Calculation(
            eps.value * multiple.value,
            price.value,
            price.unit,
            [eps.estimate_id, multiple.assumption_id, price.fact_id],
            {"forward_eps": eps.value, "target_pe": multiple.value, "market_price": price.value},
            {"implied_equity_value_per_share": eps.value * multiple.value},
        )
    if model_type == "forward_pb":
        bvps = _fact(bundle, company_id, security_id, "book_value_per_share", scenario.as_of_date)
        multiple = _assumption(bundle, scenario.scenario_id, "target_pb")
        return Calculation(
            bvps.value * multiple.value,
            price.value,
            price.unit,
            [bvps.fact_id, multiple.assumption_id, price.fact_id],
            {
                "book_value_per_share": bvps.value,
                "target_pb": multiple.value,
                "market_price": price.value,
            },
            {"implied_equity_value_per_share": bvps.value * multiple.value},
        )
    if model_type == "forward_ps":
        revps = _estimate(
            bundle,
            company_id,
            security_id,
            "future_revenue_per_share",
            scenario.scenario_type.value,
        )
        multiple = _assumption(bundle, scenario.scenario_id, "target_ps")
        return Calculation(
            revps.value * multiple.value,
            price.value,
            price.unit,
            [revps.estimate_id, multiple.assumption_id, price.fact_id],
            {
                "future_revenue_per_share": revps.value,
                "target_ps": multiple.value,
                "market_price": price.value,
            },
            {"implied_equity_value_per_share": revps.value * multiple.value},
        )
    if model_type == "peg":
        eps = _estimate(
            bundle, company_id, security_id, "diluted_eps", scenario.scenario_type.value
        )
        growth = _estimate(
            bundle, company_id, security_id, "growth_estimate", scenario.scenario_type.value
        )
        target_peg = _assumption(bundle, scenario.scenario_id, "target_peg")
        if eps.value <= 0:
            raise ValueError("PEG unavailable: diluted_eps must be positive")
        if growth.value <= 0:
            raise ValueError("PEG unavailable: growth_estimate must be positive")
        implied_pe = target_peg.value * growth.value * 100.0
        fair = eps.value * implied_pe
        return Calculation(
            fair,
            price.value,
            price.unit,
            [eps.estimate_id, growth.estimate_id, target_peg.assumption_id, price.fact_id],
            {
                "forward_eps": eps.value,
                "growth_rate": growth.value,
                "target_peg": target_peg.value,
                "implied_pe": implied_pe,
                "market_price": price.value,
            },
            {"implied_equity_value_per_share": fair},
        )
    if model_type == "milestone":
        success_probability = _assumption(
            bundle, scenario.scenario_id, "milestone_success_probability"
        )
        success_multiple = _assumption(
            bundle, scenario.scenario_id, "milestone_success_multiple"
        )
        failure_multiple = _assumption(
            bundle, scenario.scenario_id, "milestone_failure_multiple"
        )
        if not 0.0 <= success_probability.value <= 1.0:
            raise ValueError("milestone_success_probability must be between 0 and 1")
        if success_multiple.value < 0 or failure_multiple.value < 0:
            raise ValueError("milestone multiples cannot be negative")
        failure_probability = 1.0 - success_probability.value
        expected_multiple = (
            success_probability.value * success_multiple.value
            + failure_probability * failure_multiple.value
        )
        fair = price.value * expected_multiple
        return Calculation(
            fair,
            price.value,
            price.unit,
            [
                success_probability.assumption_id,
                success_multiple.assumption_id,
                failure_multiple.assumption_id,
                price.fact_id,
            ],
            {
                "current_price": price.value,
                "success_probability": success_probability.value,
                "failure_probability": failure_probability,
                "success_multiple": success_multiple.value,
                "failure_multiple": failure_multiple.value,
                "market_price": price.value,
            },
            {
                "expected_multiple": expected_multiple,
                "success_value_per_share": price.value * success_multiple.value,
                "failure_value_per_share": price.value * failure_multiple.value,
                "implied_equity_value_per_share": fair,
            },
        )
    if model_type == "ev_ebitda":
        ebitda = _fact(bundle, company_id, security_id, "ebitda", scenario.as_of_date)
        net_debt = _fact(bundle, company_id, security_id, "net_debt", scenario.as_of_date)
        shares = _fact(bundle, company_id, security_id, "shares_outstanding", scenario.as_of_date)
        multiple = _assumption(bundle, scenario.scenario_id, "target_ev_ebitda")
        implied_ev = ebitda.value * multiple.value
        implied_equity = implied_ev - net_debt.value
        fair = implied_equity / shares.value
        return Calculation(
            fair,
            price.value,
            price.unit,
            [
                ebitda.fact_id,
                net_debt.fact_id,
                shares.fact_id,
                multiple.assumption_id,
                price.fact_id,
            ],
            {
                "ebitda": ebitda.value,
                "net_debt": net_debt.value,
                "shares_outstanding": shares.value,
                "target_ev_ebitda": multiple.value,
                "market_price": price.value,
            },
            {
                "implied_enterprise_value": implied_ev,
                "implied_equity_value": implied_equity,
                "implied_equity_value_per_share": fair,
            },
        )
    raise ValueError(f"unsupported model: {model_type}")


def _effective_models(bundle, company_id):
    assignment = next(x for x in bundle.company_valuation_profiles if x.company_id == company_id)
    by_type = {}
    for profile_id in assignment.profile_ids:
        profile = next(x for x in bundle.valuation_profiles if x.profile_id == profile_id)
        for model in profile.models:
            previous = by_type.get(model.model_type)
            if previous is None or model.priority < previous.priority:
                by_type[model.model_type] = model
    for override in assignment.model_overrides:
        by_type[override.model_type] = override
    return assignment, sorted(by_type.values(), key=lambda x: x.priority)


def _blend_weight(config) -> float:
    raw = config.parameters.get("blend_weight")
    if raw is None:
        raw = {
            ModelApplicability.primary: 1.0,
            ModelApplicability.secondary: 0.65,
            ModelApplicability.optional: 0.35,
            ModelApplicability.disabled: 0.0,
        }[config.applicability]
    weight = float(raw)
    if weight < 0:
        raise ValueError(f"blend_weight cannot be negative: {config.model_type}")
    return weight


def run_valuation_book(
    bundle: RepositoryBundle,
    *,
    company_id: str,
    security_id: str,
    scenario_id: str,
    existing_snapshot_ids: set[str] | None = None,
):
    existing_snapshot_ids = existing_snapshot_ids or set()
    scenario = next(x for x in bundle.valuation_scenarios if x.scenario_id == scenario_id)
    assignment, configs = _effective_models(bundle, company_id)
    executions, snapshots, entries = [], [], []
    for config in configs:
        if not config.enabled or config.applicability == ModelApplicability.disabled:
            entries.append(
                ValuationBookEntry(
                    model_type=config.model_type,
                    applicability=config.applicability,
                    priority=config.priority,
                    blend_weight=_blend_weight(config),
                    status="disabled",
                    reason_zh_tw=config.reason_zh_tw,
                )
            )
            continue
        started = datetime.now(timezone.utc)
        try:
            calc = _calculate(bundle, company_id, security_id, scenario, config.model_type)
            model_version = MODEL_VERSIONS[config.model_type]
            canonical = {
                "company_id": company_id,
                "security_id": security_id,
                "scenario_id": scenario_id,
                "model_type": config.model_type,
                "model_version": model_version,
                "inputs": calc.inputs,
                "input_refs": calc.input_refs,
            }
            input_hash = hashlib.sha256(
                json.dumps(
                    canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                ).encode()
            ).hexdigest()
            snapshot_id = f"valuation_snapshot:{company_id}:{scenario_id}:{config.model_type}:{input_hash[:16]}"
            created = snapshot_id not in existing_snapshot_ids
            fair = round(calc.fair_value, 6)
            upside = round(fair / calc.market_price - 1, 6)
            snapshot = ValuationSnapshot(
                valuation_snapshot_id=snapshot_id,
                company_id=company_id,
                security_id=security_id,
                scenario_id=scenario_id,
                research_period=scenario.research_period,
                revision=scenario.revision,
                model_type=config.model_type,
                model_version=model_version,
                input_hash=input_hash,
                input_refs=calc.input_refs,
                as_of_date=scenario.as_of_date,
                currency=calc.currency,
                fair_value_per_share=fair,
                market_price=calc.market_price,
                upside=upside,
                model_inputs=calc.inputs,
                model_outputs=calc.outputs,
                confidence={"primary": 0.85, "secondary": 0.7, "optional": 0.55}.get(
                    config.applicability.value, 0.5
                ),
            )
            if created:
                snapshots.append(snapshot)
            entries.append(
                ValuationBookEntry(
                    model_type=config.model_type,
                    applicability=config.applicability,
                    priority=config.priority,
                    blend_weight=_blend_weight(config),
                    snapshot_id=snapshot_id,
                    status="completed",
                    fair_value_per_share=fair,
                    upside=upside,
                    confidence=snapshot.confidence,
                    reason_zh_tw=config.reason_zh_tw,
                )
            )
            status = ExecutionStatus.completed
            warnings = []
        except ValueError as exc:
            input_hash = hashlib.sha256(str(exc).encode()).hexdigest()
            snapshot_id = f"valuation_snapshot:unavailable:{config.model_type}:{input_hash[:16]}"
            created = False
            status = ExecutionStatus.skipped
            warnings = [str(exc)]
            entries.append(
                ValuationBookEntry(
                    model_type=config.model_type,
                    applicability=config.applicability,
                    priority=config.priority,
                    blend_weight=_blend_weight(config),
                    status="skipped",
                    reason_zh_tw=config.reason_zh_tw,
                    warnings=warnings,
                )
            )
        completed = datetime.now(timezone.utc)
        executions.append(
            ValuationExecution(
                execution_id=f"execution:{uuid4().hex}",
                valuation_snapshot_id=snapshot_id,
                company_id=company_id,
                security_id=security_id,
                scenario_id=scenario_id,
                model_type=config.model_type,
                model_version=MODEL_VERSIONS.get(config.model_type, "unknown"),
                input_refs=(calc.input_refs if status == ExecutionStatus.completed else []),
                input_hash=input_hash,
                started_at=started,
                completed_at=completed,
                status=status,
                created_snapshot=created,
                warnings=warnings,
            )
        )
    completed_entries = [
        x for x in entries if x.status == "completed" and x.fair_value_per_share is not None
    ]
    blended = None
    if completed_entries:
        total = sum(float(x.blend_weight or 0.0) for x in completed_entries)
        if total <= 0:
            raise ValueError("completed valuation models require a positive total blend weight")
        blended = (
            sum(
                float(x.fair_value_per_share) * float(x.blend_weight or 0.0)
                for x in completed_entries
            )
            / total
        )
    market = _fact(bundle, company_id, security_id, "market_price", scenario.as_of_date).value
    book = ValuationBook(
        valuation_book_id=f"valuation_book:{company_id}:{scenario_id}:{security_id}",
        company_id=company_id,
        security_id=security_id,
        scenario_id=scenario_id,
        as_of_date=scenario.as_of_date,
        profile_ids=assignment.profile_ids,
        entries=entries,
        blended_fair_value=round(blended, 6) if blended is not None else None,
        blended_upside=round(blended / market - 1, 6) if blended is not None else None,
    )
    return executions, snapshots, book
