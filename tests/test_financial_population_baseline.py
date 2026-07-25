import json
from pathlib import Path
import pytest
from axiom_engine.financial_population_baseline import *

def dump(p,x): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(x),encoding='utf-8')
def setup(tmp):
 p=tmp/'pop'/'registry'; dump(p/'companies.json',[{'company_id':'company:A'},{'company_id':'company:B'}]);
 s=tmp/'src'; dump(s/'facts.json',[{'company_id':'company:A','concept':'revenue','value':10,'unit':'USD','fiscal_year':2025,'period_end':'2025-12-31'}]); return tmp/'pop',s

def test_build_and_validate(tmp_path):
 p,s=setup(tmp_path); o=tmp_path/'out'; r=build_financial_population_baseline(population_dir=p,source_dir=s,output_dir=o,write=True,strict=True); assert r['covered_company_count']==1 and r['missing_company_count']==1; assert validate_financial_population_baseline(output_dir=o,population_dir=p)['valid']
def test_preserves_fact(tmp_path):
 p,s=setup(tmp_path); o=tmp_path/'out'; build_financial_population_baseline(population_dir=p,source_dir=s,output_dir=o,write=True); x=json.loads((o/'financial_source/financial_facts.json').read_text()); assert x[0]['company_id']=='company:A'
def test_missing_queue(tmp_path):
 p,s=setup(tmp_path); o=tmp_path/'out'; build_financial_population_baseline(population_dir=p,source_dir=s,output_dir=o,write=True); x=json.loads((o/'missing_companies.json').read_text()); assert x==[{'company_id':'company:B'}]
def test_invalid_link_strict(tmp_path):
 p,s=setup(tmp_path); dump(s/'bad.json',[{'company_id':'company:X','concept':'revenue','value':1}]);
 r=build_financial_population_baseline(population_dir=p,source_dir=s,output_dir=tmp_path/'o',strict=True)
 assert r['valid'] is True
 assert r['errors']==0
 assert r['rejected_fact_count']==1
 assert r['warnings']==1
 assert r['production_financial_compatible'] is True
def test_validator_detects_missing_file(tmp_path):
 assert not validate_financial_population_baseline(output_dir=tmp_path/'none',population_dir=None)['valid']
