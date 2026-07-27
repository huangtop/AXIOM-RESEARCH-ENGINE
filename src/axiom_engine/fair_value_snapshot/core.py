from __future__ import annotations
import json, math, statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

class FairValueSnapshotError(RuntimeError): pass

def _load(path: Path) -> Any:
    if not path.exists(): raise FairValueSnapshotError(f"required input not found: {path}")
    try: return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc: raise FairValueSnapshotError(f"invalid JSON: {path}") from exc

def _f(v):
    try: n=float(v)
    except (TypeError,ValueError): return None
    return n if math.isfinite(n) else None

def _value(company, name):
    row=(company.get("financial_metrics") or {}).get(name) or {}
    return _f(row.get("value"))

def _price(company):
    return _f((((company.get("market") or {}).get("previous_close") or {}).get("value")))

def _median(values):
    vals=sorted(v for v in (_f(x) for x in values) if v is not None and v>0)
    return statistics.median(vals) if vals else None

def _model(status="blocked", **kwargs):
    return {"status":status, **kwargs}

def _multiple_fv(method, target, c):
    shares=_value(c,"diluted_shares_outstanding")
    if method=="forward_pe": base=_value(c,"forward_eps"); return target*base if base and base>0 else None
    if method=="trailing_pe": base=_value(c,"trailing_eps"); return target*base if base and base>0 else None
    if method=="price_to_sales":
        rev=_value(c,"revenue"); return target*rev/shares if rev and shares and shares>0 else None
    if method=="ev_to_sales":
        rev=_value(c,"revenue"); debt=_value(c,"total_debt") or 0; cash=_value(c,"cash_and_cash_equivalents") or 0
        return (target*rev-debt+cash)/shares if rev and shares and shares>0 else None
    if method=="ev_to_ebitda":
        e=_value(c,"ebitda"); debt=_value(c,"total_debt") or 0; cash=_value(c,"cash_and_cash_equivalents") or 0
        return (target*e-debt+cash)/shares if e and e>0 and shares and shares>0 else None
    if method=="fcf_yield":
        fcf=_value(c,"free_cash_flow"); return fcf/(shares*(target/100)) if fcf and fcf>0 and shares and shares>0 and target>0 else None
    return None

def _current_multiple(method,c):
    p=_price(c); shares=_value(c,"diluted_shares_outstanding")
    if not p: return None
    if method=="forward_pe": x=_value(c,"forward_eps"); return p/x if x and x>0 else None
    if method=="trailing_pe": x=_value(c,"trailing_eps"); return p/x if x and x>0 else None
    if method=="price_to_sales": x=_value(c,"revenue"); return p*shares/x if shares and x and x>0 else None
    ev=_value(c,"enterprise_value")
    if method=="ev_to_sales": x=_value(c,"revenue"); return ev/x if ev and x and x>0 else None
    if method=="ev_to_ebitda": x=_value(c,"ebitda"); return ev/x if ev and x and x>0 else None
    if method=="fcf_yield": x=_value(c,"free_cash_flow"); return x/(p*shares)*100 if x and shares and shares>0 else None
    return None

def _historical(c, benchmarks):
    cid=c.get("company_id"); candidates=[]
    for method in ("forward_pe","trailing_pe","price_to_sales","ev_to_sales","ev_to_ebitda","fcf_yield"):
        b=benchmarks.get((cid,method))
        if not b or b.get("status")!="ready": continue
        bm=b.get("benchmark") or {}; key="target_yield_percent" if method=="fcf_yield" else "target_multiple"
        fv=_multiple_fv(method,_f(bm.get(key)),c) if _f(bm.get(key)) else None
        lo=_multiple_fv(method,_f(bm.get("lower_bound")),c) if _f(bm.get("lower_bound")) else None
        hi=_multiple_fv(method,_f(bm.get("upper_bound")),c) if _f(bm.get("upper_bound")) else None
        if fv and fv>0: candidates.append((method,fv,lo,hi,b.get("confidence","low")))
    if not candidates: return _model(reason="no_ready_historical_benchmark")
    method,fv,lo,hi,conf=candidates[0]
    return _model("ready",fair_value=fv,range_low=min(x for x in (lo,fv) if x),range_high=max(x for x in (hi,fv) if x),method=method,confidence=conf,weight=0.35)

def _peer(c, peer_medians):
    for method in ("forward_pe","ev_to_ebitda","price_to_sales","ev_to_sales","trailing_pe","fcf_yield"):
        target=peer_medians.get(method); fv=_multiple_fv(method,target,c) if target else None
        if fv and fv>0:
            return _model("ready",fair_value=fv,range_low=fv*.85,range_high=fv*1.15,method=method,target_metric=target,confidence="medium",weight=0.35)
    return _model(reason="no_usable_peer_method")

def _dcf(c, cfg):
    shares=_value(c,"diluted_shares_outstanding"); fcf=_value(c,"free_cash_flow")
    if not shares or shares<=0 or not fcf or fcf<=0: return _model(reason="positive_fcf_and_shares_required")
    te=_value(c,"trailing_eps"); fe=_value(c,"forward_eps")
    growth=(fe/te-1) if te and te>0 and fe and fe>0 else cfg["default_growth"]
    growth=max(cfg["min_growth"],min(cfg["max_growth"],growth))
    r=cfg["discount_rate"]; tg=cfg["terminal_growth"]; years=cfg["forecast_years"]
    pv=0.0; cash=fcf
    for year in range(1,years+1): cash*=1+growth; pv+=cash/((1+r)**year)
    terminal=cash*(1+tg)/(r-tg); ev=pv+terminal/((1+r)**years)
    debt=_value(c,"total_debt") or 0; cashbal=_value(c,"cash_and_cash_equivalents") or 0
    fv=(ev-debt+cashbal)/shares
    if not math.isfinite(fv) or fv<=0: return _model(reason="dcf_non_positive")
    return _model("ready",fair_value=fv,range_low=fv*.8,range_high=fv*1.2,method="fcf_dcf_mvp",growth_rate=growth,discount_rate=r,terminal_growth=tg,confidence="medium",weight=0.30)

def _composite(models, price):
    ready=[m for m in models.values() if m.get("status")=="ready" and _f(m.get("fair_value"))]
    if not ready: return _model(reason="no_ready_models")
    total=sum(_f(m.get("weight")) or 0 for m in ready)
    if total<=0: total=len(ready); weights=[1/len(ready)]*len(ready)
    else: weights=[(_f(m.get("weight")) or 0)/total for m in ready]
    fv=sum(m["fair_value"]*w for m,w in zip(ready,weights)); lo=sum((m.get("range_low") or m["fair_value"])*w for m,w in zip(ready,weights)); hi=sum((m.get("range_high") or m["fair_value"])*w for m,w in zip(ready,weights))
    upside=(fv/price-1) if price and price>0 else None
    if upside is None: rating="Unavailable"
    elif upside>=.20: rating="Significantly Undervalued"
    elif upside>=.10: rating="Undervalued"
    elif upside<=-.20: rating="Significantly Overvalued"
    elif upside<=-.10: rating="Overvalued"
    else: rating="Fairly Valued"
    conf="high" if len(ready)>=3 else "medium" if len(ready)==2 else "low"
    return _model("ready",fair_value=fv,range_low=lo,range_high=hi,upside=upside,rating=rating,confidence=conf,ready_model_count=len(ready),normalized_weights={name: ((_f(m.get("weight")) or 0)/total if total else 0) for name,m in models.items() if m in ready})

def build_fair_value_snapshot(root: Path, *, valuation_input_path: str, historical_benchmark_path: str, target_company_count: int=100, dcf_policy: Mapping[str,Any]|None=None):
    vin=_load(root/valuation_input_path); hist=_load(root/historical_benchmark_path)
    if vin.get("schema_version")!="valuation-input-snapshot.v030.12.0": raise FairValueSnapshotError("unsupported valuation input schema")
    companies=vin.get("companies") or []; benchmarks={(x.get("company_id"),x.get("method")):x for x in (hist.get("benchmarks") or []) if isinstance(x,Mapping)}
    peer_medians={m:_median(_current_multiple(m,c) for c in companies) for m in ("forward_pe","trailing_pe","price_to_sales","ev_to_sales","ev_to_ebitda","fcf_yield")}
    cfg={"forecast_years":5,"discount_rate":.10,"terminal_growth":.03,"default_growth":.08,"min_growth":0.0,"max_growth":.25}; cfg.update(dcf_policy or {})
    rows=[]; issues=[]
    for c in companies:
        p=_price(c); models={"historical":_historical(c,benchmarks),"peer":_peer(c,peer_medians),"dcf":_dcf(c,cfg)}; comp=_composite(models,p)
        state="ready" if comp.get("status")=="ready" and p else "partial" if comp.get("status")=="ready" else "blocked"
        row={"company_id":c.get("company_id"),"symbol":c.get("primary_symbol"),"company_name":c.get("display_name"),"currency":((((c.get("market") or {}).get("previous_close") or {}).get("currency")) or "USD"),"as_of_date":vin.get("as_of_date"),"current_price":p,"snapshot_state":state,"models":models,"composite":comp,"valuation_card":{"current_price":p,"fair_value":comp.get("fair_value"),"range_low":comp.get("range_low"),"range_high":comp.get("range_high"),"upside":comp.get("upside"),"rating":comp.get("rating"),"confidence":comp.get("confidence")}}
        rows.append(row)
        if state!="ready": issues.append({"symbol":row["symbol"],"state":state,"reason":"missing_market_price" if not p else comp.get("reason")})
    counts={s:sum(r["snapshot_state"]==s for r in rows) for s in ("ready","partial","blocked")}
    model_counts={name:sum(r["models"][name]["status"]=="ready" for r in rows) for name in ("historical","peer","dcf")}
    report={"schema_version":"fair-value-snapshot.v030.14.0","version":"V030.14.0","generated_at":datetime.now(timezone.utc).isoformat(),"as_of_date":vin.get("as_of_date"),"sources":{"valuation_input_path":valuation_input_path,"historical_benchmark_path":historical_benchmark_path},"policy":{"target_company_count":target_company_count,"composite_base_weights":{"historical":.35,"peer":.35,"dcf":.30},"blocked_model_policy":"exclude_and_renormalize_ready_weights","dcf":cfg},"summary":{"target_company_count":target_company_count,"company_count":len(rows),"target_count_met":len(rows)>=target_company_count,"snapshot_state_counts":counts,"model_ready_counts":model_counts,"composite_ready_count":sum(r["composite"]["status"]=="ready" for r in rows),"valuation_card_ready_count":counts["ready"],"diagnostic_count":len(issues)},"peer_benchmarks":peer_medians,"companies":rows,"indexes":{"symbol_to_position":{r["symbol"]:i for i,r in enumerate(rows)}}}
    diagnostic={"schema_version":"fair-value-diagnostic.v030.14.0","version":"V030.14.0","generated_at":report["generated_at"],"summary":report["summary"],"issues":issues}
    return report,diagnostic

def write_fair_value_snapshot(report,diagnostic,output:Path,diagnostic_output:Path):
    output.parent.mkdir(parents=True,exist_ok=True); diagnostic_output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8"); diagnostic_output.write_text(json.dumps(diagnostic,indent=2,sort_keys=True)+"\n",encoding="utf-8")
