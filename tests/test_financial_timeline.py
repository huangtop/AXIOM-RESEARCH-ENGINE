from __future__ import annotations
import json
from pathlib import Path
import pytest
from axiom_engine.financial_timeline import FinancialTimelineError, build_financial_timeline, write_financial_timeline

def _write(root,rel,payload):
 p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(payload))
def _fact(fid,metric,value,start,end,fp='FY',ptype='duration'):
 return {'financial_fact_id':fid,'metric':metric,'value':value,'period_type':ptype,'period_start':start,'period_end':end,'fiscal_year':2024,'fiscal_period':fp,'form_type':'10-K','audited':True}
def _snapshot(facts): return {'schema_version':'canonical-financial-snapshot.v030.11.0','companies':[{'company_id':'company:1','cik':'1','primary_symbol':'AAA','display_name':'A','facts':facts}]}
def test_builds_annual_and_freshness(tmp_path):
 _write(tmp_path,'in.json',_snapshot([_fact('f1','revenue',100,'2024-01-01','2024-12-31')]))
 r=build_financial_timeline(tmp_path,financial_snapshot_path='in.json',as_of_date='2025-03-01'); c=r['companies'][0]
 assert len(c['annual_periods'])==1 and c['freshness_state']=='fresh'
def test_annual_fact_becomes_explicit_ttm_proxy(tmp_path):
 _write(tmp_path,'in.json',_snapshot([_fact('f1','revenue',100,'2024-01-01','2024-12-31')]))
 c=build_financial_timeline(tmp_path,financial_snapshot_path='in.json',as_of_date='2025-01-01')['companies'][0]
 assert c['ttm']['metrics']['revenue']['state']=='annual_proxy'
def test_four_quarters_sum_to_ttm(tmp_path):
 dates=['2024-03-31','2024-06-30','2024-09-30','2024-12-31']; fs=[_fact(f'f{i}','revenue',i,None,dates[i-1],f'Q{i}') for i in range(1,5)]
 _write(tmp_path,'in.json',_snapshot(fs)); c=build_financial_timeline(tmp_path,financial_snapshot_path='in.json',as_of_date='2024-12-31')['companies'][0]
 assert c['ttm']['metrics']['revenue']['value']==10 and c['ttm']['state']=='four_quarter_sum'
def test_instant_metrics_are_not_summed(tmp_path):
 fs=[_fact('f1','cash',10,None,'2024-06-30','FY','instant'),_fact('f2','cash',20,None,'2024-12-31','FY','instant')]
 _write(tmp_path,'in.json',_snapshot(fs)); c=build_financial_timeline(tmp_path,financial_snapshot_path='in.json',as_of_date='2025-01-01')['companies'][0]
 assert c['instant_metrics']['cash']['value']==20 and 'cash' not in c['ttm']['metrics']
def test_stale_threshold(tmp_path):
 _write(tmp_path,'in.json',_snapshot([_fact('f1','revenue',1,'2020-01-01','2020-12-31')]))
 assert build_financial_timeline(tmp_path,financial_snapshot_path='in.json',as_of_date='2022-01-02')['companies'][0]['freshness_state']=='stale'
def test_invalid_period_reported_and_strict_signal_available(tmp_path):
 _write(tmp_path,'in.json',_snapshot([_fact('f1','revenue',1,None,'bad')]))
 r=build_financial_timeline(tmp_path,financial_snapshot_path='in.json',as_of_date='2025-01-01'); assert r['summary']['invalid_period_count']==1
def test_missing_snapshot_rejected(tmp_path):
 with pytest.raises(FinancialTimelineError): build_financial_timeline(tmp_path,financial_snapshot_path='missing.json')
def test_write_outputs(tmp_path):
 _write(tmp_path,'in.json',_snapshot([_fact('f1','revenue',1,'2024-01-01','2024-12-31')]))
 r=build_financial_timeline(tmp_path,financial_snapshot_path='in.json',as_of_date='2025-01-01'); write_financial_timeline(r,tmp_path/'out.json',tmp_path/'diag.json')
 assert json.loads((tmp_path/'out.json').read_text())['version']=='V030.11.1'
