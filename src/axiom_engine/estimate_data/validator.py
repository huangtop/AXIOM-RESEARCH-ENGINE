from __future__ import annotations
import json
from pathlib import Path
from .models import AnalystEstimate, ForwardAssumption, EstimateProvenance

def validate_estimate_data(root:str|Path="data/estimate_data")->dict[str,int]:
    root=Path(root)
    estimates=json.loads((root/"estimates.json").read_text(encoding="utf-8"))
    assumptions=json.loads((root/"forward_assumptions.json").read_text(encoding="utf-8"))
    provenance=json.loads((root/"provenance.json").read_text(encoding="utf-8"))
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    es=[AnalystEstimate.model_validate(x) for x in estimates]
    fs=[ForwardAssumption.model_validate(x) for x in assumptions]
    ps=[EstimateProvenance.model_validate(x) for x in provenance]
    pids={x.provenance_id for x in ps}
    for item in [*es,*fs]:
        missing=set(item.provenance_ids)-pids
        if missing: raise ValueError(f"missing provenance: {sorted(missing)}")
    if manifest["estimate_count"]!=len(es) or manifest["forward_assumption_count"]!=len(fs): raise ValueError("manifest counts do not match files")
    return {"estimate_count":len(es),"forward_assumption_count":len(fs),"company_count":len({x.company_id for x in [*es,*fs]}),"provenance_count":len(ps)}
