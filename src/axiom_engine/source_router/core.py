from __future__ import annotations
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

class SourceRouterError(RuntimeError): pass

def _load(path: Path, label: str) -> Any:
    if not path.exists(): raise SourceRouterError(f"{label} not found: {path}")
    return json.loads(path.read_text(encoding='utf-8'))

def _num(value: Any) -> int|float|None:
    if value is None or value == '': return None
    try: d=Decimal(str(value))
    except (InvalidOperation, ValueError): return None
    if not d.is_finite(): return None
    return int(d) if d == d.to_integral_value() else float(d)

def _metric(value: Any, provider: str, confidence: str, source_state: str, **extra: Any) -> dict[str,Any]:
    return {'value': value, 'provider': provider, 'confidence': confidence, 'source_state': source_state, **extra}

YAHOO_MAP={
 'revenue':'revenue_ttm','net_income':'net_income_ttm','operating_cash_flow':'operating_cash_flow_ttm',
 'cash_and_cash_equivalents':'total_cash','total_debt':'total_debt','diluted_shares_outstanding':'shares_outstanding',
 'trailing_eps':'trailing_eps','forward_eps':'forward_eps','market_cap':'market_cap','enterprise_value':'enterprise_value',
 'free_cash_flow':'free_cash_flow_ttm','gross_profit':'gross_profit_ttm','ebitda':'ebitda_ttm'
}
SEC_ONLY={'capital_expenditures'}

def build_source_router(repository_root: Path, *, timeline_path='data/generated/financial_timeline/financial_timeline.json', yahoo_path='data/generated/company/yahoo_company_snapshot.json') -> dict[str,Any]:
    timeline=_load(repository_root/timeline_path,'financial timeline')
    yahoo=_load(repository_root/yahoo_path,'Yahoo company snapshot') if (repository_root/yahoo_path).exists() else {'symbols':{}}
    if not isinstance(timeline,dict) or not isinstance(timeline.get('companies'),list): raise SourceRouterError('financial timeline must contain companies array')
    symbols=yahoo.get('symbols') if isinstance(yahoo,dict) else {}
    if not isinstance(symbols,dict): symbols={}
    companies=[]; provider_counts={'sec_companyfacts':0,'yahoo_finance':0}; state_counts={}; missing=[]; yahoo_matched=0
    for company in timeline['companies']:
        symbol=str(company.get('primary_symbol') or '').upper(); ys=symbols.get(symbol) if symbol else None
        if isinstance(ys,dict): yahoo_matched+=1
        metrics={}; ttm=(company.get('ttm') or {}).get('metrics') or {}; instant=company.get('instant_metrics') or {}
        for name,row in {**ttm,**instant}.items():
            if not isinstance(row,dict) or row.get('value') is None: continue
            conf='high' if row.get('state')=='four_quarter_sum' or row.get('audited') else 'medium'
            metrics[name]=_metric(row['value'],'sec_companyfacts',conf,'primary',period_end=row.get('period_end'),fallback_reason=None,source_fact_ids=row.get('fact_ids') or ([row.get('financial_fact_id')] if row.get('financial_fact_id') else []))
            provider_counts['sec_companyfacts']+=1
        for metric,yfield in YAHOO_MAP.items():
            yv=_num(ys.get(yfield)) if isinstance(ys,dict) else None
            if metric in metrics: continue
            if yv is not None:
                metrics[metric]=_metric(yv,'yahoo_finance','medium' if ys.get('confidence') in {'high','medium'} else 'low','fallback',period_end=ys.get('last_refresh') or ys.get('fetched_at'),fallback_reason='sec_metric_missing',source_field=yfield)
                provider_counts['yahoo_finance']+=1
            elif metric not in SEC_ONLY:
                missing.append({'company_id':company['company_id'],'symbol':symbol,'metric':metric,'reason':'missing_in_sec_and_yahoo'})
        state='sec_primary_yahoo_fallback' if any(v['provider']=='yahoo_finance' for v in metrics.values()) else 'sec_primary'
        state_counts[state]=state_counts.get(state,0)+1
        companies.append({'company_id':company['company_id'],'cik':company.get('cik'),'primary_symbol':symbol,'display_name':company.get('display_name'),'freshness_state':company.get('freshness_state'),'routing_state':state,'metrics':dict(sorted(metrics.items()))})
    generated=datetime.now(timezone.utc).isoformat()
    return {'schema_version':'financial-source-router.v030.11.2','version':'V030.11.2','generated_at':generated,'sources':{'timeline_path':timeline_path,'timeline_schema_version':timeline.get('schema_version'),'yahoo_path':yahoo_path,'yahoo_schema_version':yahoo.get('schema_version') if isinstance(yahoo,dict) else None},'summary':{'company_count':len(companies),'yahoo_cached_symbol_count':len(symbols),'yahoo_matched_company_count':yahoo_matched,'provider_metric_counts':provider_counts,'routing_state_counts':dict(sorted(state_counts.items())),'missing_metric_count':len(missing)},'companies':companies,'indexes':{'company_id_to_position':{c['company_id']:i for i,c in enumerate(companies)},'symbol_to_company_id':{c['primary_symbol']:c['company_id'] for c in companies if c['primary_symbol']}},'diagnostics':{'missing_metrics':missing}}

def write_source_router(report:dict[str,Any], output_path:Path, diagnostic_path:Path)->None:
    output_path.parent.mkdir(parents=True,exist_ok=True); diagnostic_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    diagnostic_path.write_text(json.dumps({'schema_version':'financial-source-router-diagnostic.v030.11.2','version':report['version'],'generated_at':report['generated_at'],'summary':report['summary'],**report['diagnostics']},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
