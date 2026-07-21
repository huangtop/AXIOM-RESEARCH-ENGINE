from __future__ import annotations
from ..repository import RepositoryBundle


def research_summary(bundle: RepositoryBundle, company_id: str) -> dict:
    drivers = [x for x in bundle.research_drivers if x.company_id == company_id]
    catalysts = [x for x in bundle.catalysts if x.company_id == company_id]
    theses = [x for x in bundle.investment_theses if x.company_id == company_id]
    impacts = [x for x in bundle.driver_impacts if x.company_id == company_id]
    return {
        "company_id": company_id,
        "theses": [x.model_dump(mode="json") for x in theses],
        "drivers": [x.model_dump(mode="json") for x in drivers],
        "catalysts": [x.model_dump(mode="json") for x in catalysts],
        "driver_impacts": [x.model_dump(mode="json") for x in impacts],
    }
