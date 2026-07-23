from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import FinancialFact, FinancialProvenance


class FinancialDataValidationError(RuntimeError):
    pass


def validate_financial_data(root: str | Path = "data/financial_data") -> dict[str, Any]:
    root = Path(root)
    try:
        facts_raw = json.loads((root / "financial_facts.json").read_text(encoding="utf-8"))
        provenance_raw = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinancialDataValidationError(f"cannot read financial data bundle: {root}") from exc
    facts = [FinancialFact.model_validate(x) for x in facts_raw]
    provenance = [FinancialProvenance.model_validate(x) for x in provenance_raw]
    fact_ids = [x.financial_fact_id for x in facts]
    provenance_ids = [x.provenance_id for x in provenance]
    if len(fact_ids) != len(set(fact_ids)):
        raise FinancialDataValidationError("duplicate financial_fact_id")
    if len(provenance_ids) != len(set(provenance_ids)):
        raise FinancialDataValidationError("duplicate provenance_id")
    known = set(provenance_ids)
    for fact in facts:
        missing = set(fact.provenance_ids) - known
        if missing:
            raise FinancialDataValidationError(f"fact {fact.financial_fact_id} missing provenance")
    expected = {
        "fact_count": len(facts),
        "company_count": len({x.company_id for x in facts}),
        "metric_count": len({x.metric for x in facts}),
        "provenance_count": len(provenance),
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise FinancialDataValidationError(f"manifest {key} mismatch")
    return expected
