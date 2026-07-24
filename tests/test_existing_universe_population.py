import json
from pathlib import Path
import pytest
from axiom_engine.existing_universe_population import ExistingUniversePopulationError, build_existing_universe_population, validate_existing_universe_population


def fixture(tmp_path: Path):
    u=tmp_path/'universe'; u.mkdir()
    (u/'companies.json').write_text(json.dumps([{"company_id":"company:US-CIK0001","legal_name":"Alpha Inc","display_name":"Alpha","country":"US","status":"active","metadata":{"cik":1}}]))
    (u/'securities.json').write_text(json.dumps([{"security_id":"security:NASDAQ-ALPH","company_id":"company:US-CIK0001","exchange":"NASDAQ","ticker":"ALPH","currency":"USD","security_type":"common_stock","primary_listing":True,"status":"active"}]))
    return u

def test_build_and_validate(tmp_path):
    u=fixture(tmp_path); out=tmp_path/'out'
    result=build_existing_universe_population(universe_dir=u, output_dir=out, write=True, strict=True)
    assert result['valid'] and result['company_count']==1 and result['security_count']==1
    assert validate_existing_universe_population(output_dir=out)['valid']

def test_preserves_ids_and_adds_provenance(tmp_path):
    u=fixture(tmp_path); out=tmp_path/'out'; build_existing_universe_population(universe_dir=u, output_dir=out, write=True)
    c=json.loads((out/'registry_source/companies.json').read_text())[0]
    s=json.loads((out/'registry_source/securities.json').read_text())[0]
    assert c['company_id']=='company:US-CIK0001' and s['security_id']=='security:NASDAQ-ALPH'
    assert c['provenance_ids']==['provenance:V030.0-existing-universe']

def test_missing_source(tmp_path):
    with pytest.raises(ExistingUniversePopulationError): build_existing_universe_population(universe_dir=tmp_path/'missing')

def test_invalid_link_strict(tmp_path):
    u=fixture(tmp_path); rows=json.loads((u/'securities.json').read_text()); rows[0]['company_id']='missing'; (u/'securities.json').write_text(json.dumps(rows))
    with pytest.raises(ExistingUniversePopulationError): build_existing_universe_population(universe_dir=u, output_dir=tmp_path/'out', strict=True)

def test_validation_missing_files(tmp_path):
    result=validate_existing_universe_population(output_dir=tmp_path/'empty')
    assert not result['valid'] and result['errors']
