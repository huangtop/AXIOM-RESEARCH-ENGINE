from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Any
from pydantic import ValidationError
from .models import EstimateDataSource, EstimateImportReport

FORBIDDEN_SOURCE_KEYS=frozenset({"current_price","fair_value","intrinsic_value","valuation","valuation_result","logic_type","default_params","research_report","theme_ids","classification_ids","exposure"})
class EstimateDataImportError(RuntimeError): pass

def _walk_keys(v: Any)->set[str]:
    out=set()
    if isinstance(v,dict):
        for k,c in v.items(): out.add(str(k).lower()); out.update(_walk_keys(c))
    elif isinstance(v,list):
        for c in v: out.update(_walk_keys(c))
    return out

def load_estimate_data_source(source: str|Path)->EstimateDataSource:
    path=Path(source)
    try: raw=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise EstimateDataImportError(f"cannot read estimate data source: {path}") from exc
    forbidden=sorted(FORBIDDEN_SOURCE_KEYS & _walk_keys(raw))
    if forbidden: raise EstimateDataImportError("source contains forbidden fields: "+", ".join(forbidden))
    try: return EstimateDataSource.model_validate(raw)
    except ValidationError as exc: raise EstimateDataImportError(f"invalid estimate data source: {exc}") from exc

def _load_company_ids(registry_dir: str|Path|None)->set[str]|None:
    if registry_dir is None: return None
    path=Path(registry_dir)/"companies.json"
    if not path.exists(): raise EstimateDataImportError(f"company registry not found: {path}")
    try: payload=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise EstimateDataImportError(f"cannot read company registry: {path}") from exc
    return {str(x["company_id"]) for x in payload}

def _atomic_write_json(path:Path,payload:Any)->None:
    fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as h: json.dump(payload,h,ensure_ascii=False,indent=2); h.write("\n")
        os.replace(tmp,path)
    except BaseException:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise

def import_estimate_data(source:str|Path,*,output_dir:str|Path="data/estimate_data",company_registry_dir:str|Path|None="data/company_registry",dry_run:bool=True)->EstimateImportReport:
    payload=load_estimate_data_source(source)
    known=_load_company_ids(company_registry_dir) if company_registry_dir else None
    companies={x.company_id for x in [*payload.estimates,*payload.forward_assumptions]}
    if known is not None:
        missing=sorted(companies-known)
        if missing: raise EstimateDataImportError("estimate data references companies missing from registry: "+", ".join(missing))
    estimates=sorted((x.model_dump(mode="json",exclude_none=True) for x in payload.estimates),key=lambda x:(x["company_id"],x["metric"],x["period_end"],x["estimate_id"]))
    assumptions=sorted((x.model_dump(mode="json",exclude_none=True) for x in payload.forward_assumptions),key=lambda x:(x["company_id"],x["metric"],x["effective_date"],x["assumption_id"]))
    provenance=sorted((x.model_dump(mode="json",exclude_none=True) for x in payload.provenance),key=lambda x:x["provenance_id"])
    manifest={"schema_version":payload.schema_version,"provider_id":payload.provider_id,"provider_name":payload.provider_name,"as_of_date":payload.as_of_date.isoformat(),"estimate_count":len(estimates),"forward_assumption_count":len(assumptions),"company_count":len(companies),"provenance_count":len(provenance),"data_scope":"analyst_estimates_and_forward_assumptions_only","reported_financials_included":False,"market_prices_included":False,"valuation_outputs_included":False}
    outputs={"estimates.json":estimates,"forward_assumptions.json":assumptions,"provenance.json":provenance,"manifest.json":manifest}
    target=Path(output_dir); written=[]
    if not dry_run:
        target.mkdir(parents=True,exist_ok=True)
        for name,val in outputs.items(): _atomic_write_json(target/name,val); written.append(str(target/name))
    return EstimateImportReport(provider_id=payload.provider_id,as_of_date=payload.as_of_date,dry_run=dry_run,estimates_found=len(estimates),assumptions_found=len(assumptions),companies_found=len(companies),provenance_records=len(provenance),output_directory=str(target),written_files=written)
