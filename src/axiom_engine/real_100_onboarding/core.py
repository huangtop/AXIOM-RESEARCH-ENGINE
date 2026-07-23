from __future__ import annotations
import json, urllib.request
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Model(BaseModel): model_config=ConfigDict(extra='forbid')
class Member(Model): rank:int=Field(ge=1); ticker:str; exchange_hint:str|None=None
class Cohort(Model):
    schema_version:str='1.0.0'; cohort_id:str=Field(pattern=r'^cohort:'); name:str; selection_policy:str; company_count:int; symbols:list[Member]
    @model_validator(mode='after')
    def valid(self):
        if self.company_count != len(self.symbols): raise ValueError('company_count mismatch')
        if len({x.ticker for x in self.symbols}) != len(self.symbols): raise ValueError('duplicate ticker')
        return self

def load_cohort(path='data/onboarding/us_real_100_cohort.json'):
    return Cohort.model_validate(json.loads(Path(path).read_text()))

def _rows(path):
    p=Path(path); return json.loads(p.read_text()) if p.exists() else []

def onboarding_status(cohort_path='data/onboarding/us_real_100_cohort.json',registry_dir='data/company_registry',financial_dir='data/financial_data',estimate_dir='data/estimate_data'):
    c=load_cohort(cohort_path); secs=_rows(Path(registry_dir)/'securities.json')
    map_={str(x.get('ticker','')).upper():x.get('company_id') for x in secs}
    facts=_rows(Path(financial_dir)/'financial_facts.json'); est=_rows(Path(estimate_dir)/'estimates.json'); ass=_rows(Path(estimate_dir)/'forward_assumptions.json')
    fi={}; ei={}; ai={}
    for x in facts: fi.setdefault(x['company_id'],set()).add(x['metric'])
    for x in est: ei.setdefault(x['company_id'],set()).add(x['metric'])
    for x in ass:
        if x.get('status')=='approved': ai.setdefault(x['company_id'],set()).add(x['metric'])
    reqf={'free_cash_flow','cash_and_cash_equivalents','total_debt','diluted_shares_outstanding'}; reqe={'eps_diluted'}; reqa={'fcf_growth_rate','discount_rate','terminal_growth_rate','forward_pe'}
    gaps={}; resolved=ready=0
    for m in c.symbols:
        cid=map_.get(m.ticker.upper())
        if not cid: gaps[m.ticker]=['company_registry']; continue
        resolved+=1; g=[f'fact:{x}' for x in sorted(reqf-fi.get(cid,set()))]+[f'estimate:{x}' for x in sorted(reqe-ei.get(cid,set()))]+[f'assumption:{x}' for x in sorted(reqa-ai.get(cid,set()))]
        gaps[m.ticker]=g; ready += not g
    return {'cohort_id':c.cohort_id,'companies_requested':100,'companies_resolved':resolved,'valuation_ready':ready,'acceptance_passed':resolved==100 and ready==100,'missing_by_company':gaps}

def build_sec_registry_source(user_agent,cohort_path='data/onboarding/us_real_100_cohort.json',output='data/onboarding/generated/company_universe_source.json',write=False):
    if '@' not in user_agent: raise ValueError('SEC user agent must include contact email')
    req=urllib.request.Request('https://www.sec.gov/files/company_tickers.json',headers={'User-Agent':user_agent})
    with urllib.request.urlopen(req,timeout=45) as r: table=json.loads(r.read())
    by={v['ticker'].upper():v for v in table.values()}; c=load_cohort(cohort_path); companies=[]; securities=[]; provenance=[]; unresolved=[]
    from datetime import datetime,timezone,date
    now=datetime.now(timezone.utc).isoformat()
    for m in c.symbols:
        key=m.ticker.replace('.','-').upper(); row=by.get(key)
        if not row: unresolved.append(m.ticker); continue
        cik=str(row['cik_str']).zfill(10); cid=f'company:US-CIK{cik}'; pid=f'provenance:sec-registry:{cik}'
        companies.append({'company_id':cid,'legal_name':row['title'],'display_name':row['title'],'country':'US','provenance_ids':[pid],'metadata':{'cik':cik,'cohort_ticker':m.ticker}})
        securities.append({'security_id':f'security:SEC-{key}','company_id':cid,'exchange':'US','ticker':m.ticker,'currency':'USD','security_type':'common_stock','primary_listing':True,'provenance_ids':[pid]})
        provenance.append({'provenance_id':pid,'source_type':'regulator','source_name':'SEC company_tickers.json','source_record_id':cik,'retrieved_at':now,'source_url':'https://www.sec.gov/files/company_tickers.json'})
    payload={'schema_version':'1.0.0','as_of_date':date.today().isoformat(),'source_name':'SEC Real 100 Registry','provenance':provenance,'companies':companies,'securities':securities}
    if write:
        p=Path(output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(payload,indent=2)+'\n')
    return {'companies_requested':100,'companies_resolved':len(companies),'unresolved_tickers':unresolved,'written_file':output if write else None,'note':'SEC identity only. Financial facts, analyst estimates and approved assumptions remain separate canonical inputs.'}
