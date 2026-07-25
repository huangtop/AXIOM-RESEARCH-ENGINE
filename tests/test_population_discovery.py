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
