from __future__ import annotations

from datetime import datetime, timezone

from ..config import GENERATED_DIR, PUBLIC_DIR
from ..io import read_json, write_json
from ..repository import RepositoryBundle


def build_public(bundle: RepositoryBundle) -> dict[str, int]:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    securities_by_company: dict[str, list] = {}
    for security in bundle.securities:
        securities_by_company.setdefault(security.company_id, []).append(security)

    facts_by_company: dict[str, list] = {}
    for fact in bundle.financial_facts:
        facts_by_company.setdefault(fact.company_id, []).append(fact)

    estimates_by_company: dict[str, list] = {}
    for estimate in bundle.estimates:
        estimates_by_company.setdefault(estimate.company_id, []).append(estimate)

    scenarios_by_company: dict[str, list] = {}
    for scenario in bundle.valuation_scenarios:
        scenarios_by_company.setdefault(scenario.company_id, []).append(scenario)

    company_profiles = {x.company_id: x for x in bundle.company_valuation_profiles}
    profile_by_id = {x.profile_id: x for x in bundle.valuation_profiles}

    results = []
    result_path = GENERATED_DIR / "valuation_snapshots.json"
    if result_path.exists():
        results = read_json(result_path)

    results_by_company: dict[str, list] = {}
    for result in results:
        results_by_company.setdefault(result["company_id"], []).append(result)

    drivers_by_company: dict[str, list] = {}
    for item in bundle.research_drivers:
        drivers_by_company.setdefault(item.company_id, []).append(item)
    catalysts_by_company: dict[str, list] = {}
    for item in bundle.catalysts:
        catalysts_by_company.setdefault(item.company_id, []).append(item)

    search = []
    for entity in bundle.entities:
        payload = entity.model_dump(mode="json", exclude_none=True)
        if entity.entity_type.value == "company":
            cp = company_profiles.get(entity.entity_id)
            payload["securities"] = [
                x.model_dump(mode="json", exclude_none=True)
                for x in securities_by_company.get(entity.entity_id, [])
            ]
            payload["financial_facts"] = [
                x.model_dump(mode="json", exclude_none=True)
                for x in facts_by_company.get(entity.entity_id, [])
            ]
            payload["estimates"] = [
                x.model_dump(mode="json", exclude_none=True)
                for x in estimates_by_company.get(entity.entity_id, [])
            ]
            payload["valuation_scenarios"] = [
                x.model_dump(mode="json", exclude_none=True)
                for x in scenarios_by_company.get(entity.entity_id, [])
            ]
            payload["valuation_results"] = results_by_company.get(entity.entity_id, [])
            payload["research_drivers"] = [
                x.model_dump(mode="json", exclude_none=True)
                for x in drivers_by_company.get(entity.entity_id, [])
            ]
            payload["catalysts"] = [
                x.model_dump(mode="json", exclude_none=True)
                for x in catalysts_by_company.get(entity.entity_id, [])
            ]
            payload["valuation_profiles"] = []
            if cp:
                payload["company_valuation_profile"] = cp.model_dump(mode="json", exclude_none=True)
                payload["valuation_profiles"] = [
                    profile_by_id[profile_id].model_dump(mode="json", exclude_none=True)
                    for profile_id in cp.profile_ids
                ]
        write_json(PUBLIC_DIR / "entities" / f"{entity.entity_id}.json", payload)
        search.append(
            {
                "entity_id": entity.entity_id,
                "entity_type": entity.entity_type.value,
                "name": entity.name,
                "name_zh_tw": entity.name_zh_tw,
                "aliases": entity.aliases,
            }
        )

    manifest = {
        "schema_version": "0.4.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "entities": len(bundle.entities),
            "securities": len(bundle.securities),
            "relations": len(bundle.relations),
            "evidence": len(bundle.evidence),
            "sources": len(bundle.sources),
            "financial_facts": len(bundle.financial_facts),
            "estimates": len(bundle.estimates),
            "valuation_profiles": len(bundle.valuation_profiles),
            "valuation_scenarios": len(bundle.valuation_scenarios),
            "valuation_snapshots": len(results),
            "research_drivers": len(bundle.research_drivers),
            "catalysts": len(bundle.catalysts),
            "investment_theses": len(bundle.investment_theses),
        },
    }
    write_json(PUBLIC_DIR / "manifest.json", manifest)
    write_json(PUBLIC_DIR / "search.json", search)
    return manifest["counts"]
