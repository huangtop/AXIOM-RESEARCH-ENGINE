from __future__ import annotations

from collections import defaultdict
from datetime import date
from ..io import read_json
from ..config import GENERATED_DIR
from ..models import ETFThemeExposure, ETFValuationSnapshot
from ..repository import RepositoryBundle


def derive_theme_exposures(bundle: RepositoryBundle, etf_id: str) -> list[ETFThemeExposure]:
    holdings = [x for x in bundle.etf_holdings if x.etf_id == etf_id]
    company_exposures = defaultdict(list)
    for exposure in bundle.industry_exposures:
        company_exposures[exposure.company_id].append(exposure)
    totals: dict[str, float] = defaultdict(float)
    confidence_numerators: dict[str, float] = defaultdict(float)
    source_holding_ids: dict[str, list[str]] = defaultdict(list)
    as_of = max((x.as_of_date for x in holdings), default=date.today())
    for holding in holdings:
        for exposure in company_exposures[holding.company_id]:
            company_weight = exposure.weight if exposure.weight is not None else 1.0
            contribution = holding.weight * company_weight
            totals[exposure.entity_id] += contribution
            confidence_numerators[exposure.entity_id] += contribution * exposure.confidence
            source_holding_ids[exposure.entity_id].append(holding.holding_id)
    results = []
    for entity_id, weight in sorted(totals.items()):
        confidence = confidence_numerators[entity_id] / weight if weight else 0.0
        results.append(
            ETFThemeExposure(
                exposure_id=f"etf_theme_exposure:{etf_id}:{entity_id}",
                etf_id=etf_id,
                entity_id=entity_id,
                exposure_type="derived_industry_exposure",
                derived_weight=round(min(weight, 1.0), 6),
                confidence=round(confidence, 6),
                as_of_date=as_of,
                source_holding_ids=sorted(set(source_holding_ids[entity_id])),
            )
        )
    return results


def _latest_company_upside() -> dict[str, float]:
    path = GENERATED_DIR / "valuation_books.json"
    if not path.exists():
        return {}
    books = read_json(path)
    return {
        item["company_id"]: item["blended_upside"]
        for item in books
        if item.get("blended_upside") is not None
    }


def derive_valuation_snapshot(bundle: RepositoryBundle, etf_id: str) -> ETFValuationSnapshot:
    holdings = [x for x in bundle.etf_holdings if x.etf_id == etf_id]
    upside_by_company = _latest_company_upside()
    weighted_sum = 0.0
    coverage = 0.0
    covered = []
    missing = []
    for holding in holdings:
        if holding.company_id in upside_by_company:
            coverage += holding.weight
            weighted_sum += holding.weight * upside_by_company[holding.company_id]
            covered.append(holding.holding_id)
        else:
            missing.append(holding.company_id)
    weighted_upside = weighted_sum / coverage if coverage else None
    as_of = max((x.as_of_date for x in holdings), default=date.today())
    return ETFValuationSnapshot(
        snapshot_id=f"etf_valuation_snapshot:{etf_id}:{as_of.isoformat()}",
        etf_id=etf_id,
        as_of_date=as_of,
        weighted_upside=round(weighted_upside, 6) if weighted_upside is not None else None,
        valuation_coverage=round(coverage, 6),
        covered_holding_ids=covered,
        missing_company_ids=sorted(set(missing)),
    )


def etf_summary(bundle: RepositoryBundle, etf_id: str) -> dict:
    profile = next((x for x in bundle.etf_profiles if x.etf_id == etf_id), None)
    if profile is None:
        raise ValueError(f"Unknown ETF: {etf_id}")
    entities = {x.entity_id: x for x in bundle.entities}
    holdings = [x for x in bundle.etf_holdings if x.etf_id == etf_id]
    themes = derive_theme_exposures(bundle, etf_id)
    valuation = derive_valuation_snapshot(bundle, etf_id)
    return {
        "profile": profile.model_dump(mode="json", exclude_none=True),
        "holdings": [
            {
                **x.model_dump(mode="json", exclude_none=True),
                "company": entities[x.company_id].model_dump(mode="json", exclude_none=True),
            }
            for x in holdings
        ],
        "theme_exposures": [
            {
                **x.model_dump(mode="json", exclude_none=True),
                "entity": entities[x.entity_id].model_dump(mode="json", exclude_none=True),
            }
            for x in themes
        ],
        "valuation": valuation.model_dump(mode="json", exclude_none=True),
    }
