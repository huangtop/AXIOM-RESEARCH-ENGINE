import json
from pathlib import Path
from axiom_engine.source_router import build_source_router,write_source_router

def setup(tmp_path:Path,yahoo=True):
 t={'schema_version':'financial-timeline.v030.11.1','companies':[{'company_id':'company:1','cik':'1','primary_symbol':'AAA','display_name':'AAA','freshness_state':'current','ttm':{'metrics':{'revenue':{'value':100,'state':'annual_proxy','period_end':'2025-12-31','fact_ids':['f1']}}},'instant_metrics':{}}]}
 yp={'schema_version':'yahoo-company-snapshot.v030.10.3','symbols':{'AAA':{'symbol':'AAA','confidence':'high','revenue_ttm':'999','forward_eps':'5.5','shares_outstanding':'20','last_refresh':'2026-07-27'}} if yahoo else {}}
 (tmp_path/'t.json').write_text(json.dumps(t)); (tmp_path/'y.json').write_text(json.dumps(yp)); return t,yp

def test_sec_wins_over_yahoo(tmp_path):
 setup(tmp_path); r=build_source_router(tmp_path,timeline_path='t.json',yahoo_path='y.json'); assert r['companies'][0]['metrics']['revenue']['value']==100; assert r['companies'][0]['metrics']['revenue']['provider']=='sec_companyfacts'
def test_yahoo_fills_missing(tmp_path):
 setup(tmp_path); r=build_source_router(tmp_path,timeline_path='t.json',yahoo_path='y.json'); assert r['companies'][0]['metrics']['forward_eps']['value']==5.5; assert r['companies'][0]['metrics']['forward_eps']['source_state']=='fallback'
def test_summary_counts(tmp_path):
 setup(tmp_path); r=build_source_router(tmp_path,timeline_path='t.json',yahoo_path='y.json'); assert r['summary']['yahoo_matched_company_count']==1; assert r['summary']['provider_metric_counts']['sec_companyfacts']==1
def test_missing_yahoo_is_allowed(tmp_path):
 setup(tmp_path,False); r=build_source_router(tmp_path,timeline_path='t.json',yahoo_path='y.json'); assert r['summary']['company_count']==1; assert r['summary']['provider_metric_counts']['yahoo_finance']==0
def test_invalid_yahoo_numbers_ignored(tmp_path):
 setup(tmp_path); p=json.loads((tmp_path/'y.json').read_text()); p['symbols']['AAA']['forward_eps']='NaN'; (tmp_path/'y.json').write_text(json.dumps(p)); r=build_source_router(tmp_path,timeline_path='t.json',yahoo_path='y.json'); assert 'forward_eps' not in r['companies'][0]['metrics']
def test_indexes(tmp_path):
 setup(tmp_path); r=build_source_router(tmp_path,timeline_path='t.json',yahoo_path='y.json'); assert r['indexes']['symbol_to_company_id']['AAA']=='company:1'
def test_write(tmp_path):
 setup(tmp_path); r=build_source_router(tmp_path,timeline_path='t.json',yahoo_path='y.json'); write_source_router(r,tmp_path/'o.json',tmp_path/'d.json'); assert json.loads((tmp_path/'o.json').read_text())['version']=='V030.11.2'; assert (tmp_path/'d.json').exists()
