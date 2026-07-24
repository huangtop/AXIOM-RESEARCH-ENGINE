from __future__ import annotations
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from axiom_engine.production_registry import build_production_registry, validate_production_registry
from axiom_engine.production_financial import build_production_financials, validate_production_financials
from axiom_engine.production_market import build_production_market, validate_production_market
from axiom_engine.production_estimate import build_production_estimates, validate_production_estimates

class ProductionBuildError(RuntimeError): pass

def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def _dirs(output_dir: Path) -> dict[str, Path]:
    return {k: output_dir / k for k in ("registry", "financial", "market", "estimate")}

def build_production(*, registry_source_dir: str|Path, financial_source_dir: str|Path, market_source_dir: str|Path, estimate_source_dir: str|Path, output_dir: str|Path="data/production", write: bool=False, strict: bool=False) -> dict[str, Any]:
    out=Path(output_dir); temp_ctx = tempfile.TemporaryDirectory(prefix="axiom-v0284-") if not write else None
    work_out = out if write else Path(temp_ctx.name)
    d=_dirs(work_out); steps=[]
    try:
        steps.append(build_production_registry(source_dir=registry_source_dir, output_dir=d["registry"], write=True, strict=strict))
        steps.append(build_production_financials(source_dir=financial_source_dir, output_dir=d["financial"], registry_dir=d["registry"], write=True, strict=strict))
        steps.append(build_production_market(source_dir=market_source_dir, output_dir=d["market"], registry_dir=d["registry"], write=True, strict=strict))
        steps.append(build_production_estimates(source_dir=estimate_source_dir, output_dir=d["estimate"], registry_dir=d["registry"], write=True, strict=strict))
    except Exception as exc:
        raise ProductionBuildError(str(exc)) from exc
    errors=sum(int(x.get("errors",0)) for x in steps); warnings=sum(int(x.get("warnings",0)) for x in steps)
    manifest={"schema_version":"1.0.0","production_version":"V028.4","generated_at":datetime.now(timezone.utc).isoformat(),"valid":errors==0,"errors":errors,"warnings":warnings,"dry_run":not write,"output_dir":str(out),"layers":{"registry":steps[0],"financial":steps[1],"market":steps[2],"estimate":steps[3]},"counts":{"companies":steps[0].get("company_count",0),"securities":steps[0].get("security_count",0),"financial_facts":steps[1].get("fact_count",0),"market_snapshots":steps[2].get("snapshot_count",0),"estimates":steps[3].get("estimate_count",0)}}
    if strict and not manifest["valid"]: raise ProductionBuildError(f"production build failed with {errors} errors")
    if write: _write(out/"production_build_manifest.json",manifest)
    if temp_ctx is not None: temp_ctx.cleanup()
    return manifest

def validate_production(*, output_dir: str|Path="data/production") -> dict[str, Any]:
    out=Path(output_dir); d=_dirs(out); errors=[]; layers={}
    validators={"registry":lambda:validate_production_registry(output_dir=d["registry"]),"financial":lambda:validate_production_financials(output_dir=d["financial"],registry_dir=d["registry"]),"market":lambda:validate_production_market(output_dir=d["market"],registry_dir=d["registry"]),"estimate":lambda:validate_production_estimates(output_dir=d["estimate"],registry_dir=d["registry"])}
    for name,fn in validators.items():
        try: layers[name]=fn()
        except Exception as exc: layers[name]={"valid":False,"errors":[str(exc)]}
        if not layers[name].get("valid",False): errors.extend(f"{name}: {e}" for e in layers[name].get("errors",["invalid layer"]))
    manifest_path=out/"production_build_manifest.json"
    if not manifest_path.exists(): errors.append("production_build_manifest.json not found")
    return {"valid":not errors,"errors":errors,"layers":layers,"output_dir":str(out)}
