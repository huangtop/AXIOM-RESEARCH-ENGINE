from __future__ import annotations
import json, os, tempfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

METRICS={"current_price","previous_close","market_cap","enterprise_value","shares_outstanding","beta"}
ALIASES={"price":"current_price","regularMarketPrice":"current_price","previousClose":"previous_close","marketCap":"market_cap","enterpriseValue":"enterprise_value","sharesOutstanding":"shares_outstanding"}
FORBIDDEN={"fair_value","intrinsic_value","analyst_target","price_target","upside","downside","valuation_result"}
class MarketDataError(RuntimeError): pass

def _read(path:Path)->Any:
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError) as e: raise MarketDataError(f"cannot read JSON: {path}") from e

def _write(path:Path,payload:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as h: json.dump(payload,h,ensure_ascii=False,indent=2); h.write('\n')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def _dec(v:Any,label:str)->str:
    try:return str(Decimal(str(v)).normalize())
    except (InvalidOperation,ValueError,TypeError) as e: raise MarketDataError(f"invalid numeric value for {label}: {v}") from e

def _walk(v:Any)->set[str]:
    out=set()
    if isinstance(v,dict):
        for k,c in v.items(): out.add(str(k)); out|=_walk(c)
    elif isinstance(v,list):
        for c in v: out|=_walk(c)
    return out

def _registry(root:Path)->tuple[dict[str,str],set[str]]:
    companies=_read(root/'companies.json'); securities=_read(root/'securities.json')
    ticker_to_company={}; security_ids=set()
    for s in securities:
        security_ids.add(str(s.get('security_id','')))
        t=str(s.get('ticker','')).upper()
        if t: ticker_to_company[t]=str(s.get('company_id',''))
    for c in companies:
        t=str(c.get('ticker','')).upper()
        if t: ticker_to_company[t]=str(c.get('company_id',''))
    return ticker_to_company,security_ids

def _normalize_rows(raw:Any,adapter:str)->list[dict[str,Any]]:
    adapter=adapter.lower()
    if adapter=='auto':
        adapter='canonical' if isinstance(raw,dict) and 'observations' in raw else 'generic'
    if adapter=='canonical':
        return list(raw.get('observations',[])) if isinstance(raw,dict) else []
    if isinstance(raw,dict):
        rows=raw.get('data') or raw.get('results') or raw.get('quotes') or raw.get('observations')
        if rows is None: rows=[raw]
    else: rows=raw
    if not isinstance(rows,list): raise MarketDataError('provider payload must resolve to a list of records')
    return rows

def build_market_data(*,source:str|Path,registry_dir:str|Path='data/company_registry',output_dir:str|Path='data/market_data',adapter:str='auto',provider_id:str='provider:manual',provider_name:str='Manual Provider',as_of_date:str|None=None,write:bool=False,compact:bool=False)->dict[str,Any]:
    raw=_read(Path(source)); forbidden=sorted(FORBIDDEN & _walk(raw))
    if forbidden: raise MarketDataError('source contains forbidden valuation fields: '+', '.join(forbidden))
    rows=_normalize_rows(raw,adapter); ticker_map,security_ids=_registry(Path(registry_dir))
    day=as_of_date or date.today().isoformat(); now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    observations=[]; diagnostics=[]; provenance=[]
    for i,row in enumerate(rows,1):
        if not isinstance(row,dict): diagnostics.append({'severity':'error','code':'invalid_row','row':i}); continue
        ticker=str(row.get('ticker') or row.get('symbol') or '').upper(); company_id=str(row.get('company_id') or ticker_map.get(ticker,'')).strip(); security_id=str(row.get('security_id') or '')
        if not security_id and ticker:
            security_id=next((x for x in security_ids if x.upper().endswith(':'+ticker) or x.upper().endswith('-'+ticker)),f'security:{ticker}')
        if not company_id: diagnostics.append({'severity':'error','code':'company_unresolved','row':i,'ticker':ticker}); continue
        prov_id=f"provenance:market:{provider_id.split(':')[-1]}:{i}"
        provenance.append({'provenance_id':prov_id,'provider_id':provider_id,'provider_name':provider_name,'source_record_id':str(row.get('id') or i),'retrieved_at':str(row.get('retrieved_at') or now),'source_url':row.get('source_url')})
        metrics={}
        if 'metric' in row and 'value' in row: metrics[str(row['metric'])]=row['value']
        else:
            for k,v in row.items():
                metric=ALIASES.get(k,k)
                if metric in METRICS and v not in (None,''): metrics[metric]=v
        for metric,value in metrics.items():
            metric=ALIASES.get(metric,metric)
            if metric not in METRICS: diagnostics.append({'severity':'warning','code':'unsupported_metric','row':i,'metric':metric}); continue
            unit='shares' if metric=='shares_outstanding' else ('ratio' if metric=='beta' else 'currency')
            currency=None if unit in {'shares','ratio'} else str(row.get('currency') or 'USD').upper()
            observed=str(row.get('observed_at') or row.get('timestamp') or now); trading=str(row.get('trading_date') or observed[:10] or day)
            observations.append({'market_observation_id':f'market_observation:{company_id.split(":")[-1]}:{metric}:{trading}:{i}','company_id':company_id,'security_id':security_id,'ticker':ticker or None,'metric':metric,'value':_dec(value,metric),'unit':unit,'currency':currency,'observed_at':observed,'trading_date':trading,'session':str(row.get('session') or 'completed_session'),'provenance_ids':[prov_id]})
    observations.sort(key=lambda x:(x['company_id'],x['metric'],x['trading_date'],x['market_observation_id']))
    manifest={'schema_version':'1.1.0','provider_id':provider_id,'provider_name':provider_name,'as_of_date':day,'observation_count':len(observations),'company_count':len({x['company_id'] for x in observations}),'security_count':len({x['security_id'] for x in observations}),'metric_count':len({x['metric'] for x in observations}),'provenance_count':len(provenance),'valuation_outputs_included':False}
    acceptance=bool(observations) and not any(x['severity']=='error' for x in diagnostics)
    report={'rows_received':len(rows),'observations_built':len(observations),'companies_found':manifest['company_count'],'metrics_found':manifest['metric_count'],'provider_adapter':adapter,'output_directory':str(output_dir),'dry_run':not write,'acceptance_passed':acceptance,'diagnostic_summary':{'errors':sum(x['severity']=='error' for x in diagnostics),'warnings':sum(x['severity']=='warning' for x in diagnostics)}}
    if write:
        root=Path(output_dir); _write(root/'observations.json',observations); _write(root/'provenance.json',provenance); _write(root/'manifest.json',manifest); _write(root/'diagnostics.json',diagnostics)
    return report

def validate_market_data(output_dir:str|Path='data/market_data')->dict[str,Any]:
    root=Path(output_dir); errors=[]
    for name in ('observations.json','provenance.json','manifest.json','diagnostics.json'):
        if not (root/name).exists(): errors.append(f'missing {name}')
    obs=_read(root/'observations.json') if not errors else []
    if not isinstance(obs,list): errors.append('observations.json must be a list'); obs=[]
    for i,row in enumerate(obs):
        for key in ('market_observation_id','company_id','security_id','metric','value','observed_at','trading_date','provenance_ids'):
            if key not in row: errors.append(f'observation {i} missing {key}')
        if row.get('metric') not in METRICS: errors.append(f'observation {i} unsupported metric')
    return {'output_directory':str(root),'observations':len(obs),'valid':not errors,'errors':errors}

def write_template(path:str|Path,*,fiscal_date:str|None=None)->dict[str,Any]:
    payload=[{'ticker':'AAPL','current_price':'','previous_close':'','market_cap':'','enterprise_value':'','shares_outstanding':'','beta':'','currency':'USD','trading_date':fiscal_date or date.today().isoformat(),'observed_at':''}]
    _write(Path(path),payload); return {'template':str(path),'rows':len(payload)}
