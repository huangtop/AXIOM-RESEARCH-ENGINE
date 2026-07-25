from __future__ import annotations
import json
from pathlib import Path
from axiom_engine.population_discovery import discover, validate_manifest, write_outputs

def _repo(tmp_path: Path) -> Path:
    (tmp_path/'data/universe').mkdir(parents=True)
    companies=[{"company_id":"company:1"},{"company_id":"company:2"}]
    securities=[{"security_id":"security:1","company_id":"company:1","ticker":"AAA"},{"security_id":"security:2","company_id":"company:2","ticker":"BBB"}]
    (tmp_path/'data/universe/companies.json').write_text(json.dumps(companies))
    (tmp_path/'data/universe/securities.json').write_text(json.dumps(securities))
    return tmp_path

def test_selects_linked_sources(tmp_path):
    root=_repo(tmp_path); (root/'data/production').mkdir()
    (root/'data/production/financial_population.json').write_text(json.dumps([{"company_id":"company:1","revenue":10},{"company_id":"company:2","revenue":20}]))
    payload=discover(root)
    assert payload['selections']['financial']['linked_company_count']==2

def test_rejects_unlinked_sample(tmp_path):
    root=_repo(tmp_path); (root/'data/sample').mkdir()
    (root/'data/sample/financial_sample.json').write_text(json.dumps([{"company_id":"unknown","revenue":10}]))
    payload=discover(root)
    assert payload['selections']['financial'] is None

def test_write_and_validate(tmp_path):
    root=_repo(tmp_path); (root/'data/production').mkdir()
    (root/'data/production/market_prices.json').write_text(json.dumps([{"ticker":"AAA","price":10}]))
    payload=discover(root); out=root/'data/generated/population_manifest'; write_outputs(payload,out)
    manifest=json.loads((out/'population_manifest.json').read_text())
    assert validate_manifest(manifest,root)['valid'] is True

def test_missing_layers_are_warnings(tmp_path):
    root=_repo(tmp_path); payload=discover(root); write_outputs(payload,root/'out')
    result=validate_manifest(json.loads((root/'out/population_manifest.json').read_text()),root)
    assert result['valid'] is True and len(result['missing_layers'])==3


def test_semantic_gate_excludes_valuation_snapshot_from_market(tmp_path):
    root=_repo(tmp_path); (root/'data/generated').mkdir()
    (root/'data/generated/valuation_snapshots.json').write_text(json.dumps([{
        "company_id":"company:1", "security_id":"security:1", "ticker":"AAA",
        "market_price":10, "fair_value":12, "valuation_method":"dcf", "implied_upside":0.2
    }]))
    payload=discover(root)
    assert payload['selections']['market'] is None
    assert all(x['path'] != 'data/generated/valuation_snapshots.json' for x in payload['candidates'])

def test_selected_candidate_contains_semantic_metadata(tmp_path):
    root=_repo(tmp_path); (root/'data/production').mkdir()
    (root/'data/production/market_prices.json').write_text(json.dumps([{
        "ticker":"AAA", "last_price":10, "quote_time":"2026-07-25T00:00:00Z"
    }]))
    payload=discover(root)
    selected=payload['selections']['market']
    assert selected['semantic_type']=='market_fact'
    assert selected['eligible_layers']==['market']
    assert selected['semantic_confidence'] >= 0.5

def test_inventory_keeps_semantically_rejected_sources(tmp_path):
    root=_repo(tmp_path); (root/'data/generated').mkdir()
    (root/'data/generated/valuation_snapshots.json').write_text(json.dumps([{
        "company_id":"company:1", "ticker":"AAA", "market_price":10,
        "fair_value":12, "valuation_method":"dcf", "implied_upside":0.2
    }]))
    payload=discover(root)
    item=next(x for x in payload['source_inventory'] if x['path']=='data/generated/valuation_snapshots.json')
    assert item['semantic_type']=='valuation_result'
    assert item['ranking_candidate'] is False
    assert 'semantic_type_not_population_eligible:valuation_result' in item['rejection_reasons']
    assert payload['semantic_summary']['valuation_result']==1


def test_write_outputs_separates_inventory_and_ranked_candidates(tmp_path):
    root=_repo(tmp_path); (root/'data/production').mkdir()
    (root/'data/production/market_prices.json').write_text(json.dumps([{"ticker":"AAA","last_price":10,"quote_time":"2026-07-25"}]))
    (root/'data/production/blank_template.json').write_text(json.dumps([{"ticker":"AAA","target_price":None}]))
    payload=discover(root); out=root/'out'; write_outputs(payload,out)
    inventory=json.loads((out/'population_source_inventory.json').read_text())
    ranked=json.loads((out/'population_ranked_candidates.json').read_text())
    assert len(inventory) >= len(ranked)
    assert any(x['semantic_type']=='template' for x in inventory)
    assert all('layer' in x for x in ranked)
