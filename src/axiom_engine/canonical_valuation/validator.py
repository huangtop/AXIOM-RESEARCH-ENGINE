from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .models import CompanyValuationResult


class CanonicalValuationValidationError(RuntimeError):
    pass


def validate_canonical_valuation(root: str | Path = "data/canonical_valuation") -> dict[str, Any]:
    base = Path(root)
    try:
        results_raw = json.loads((base / "valuation_results.json").read_text(encoding="utf-8"))
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        results = TypeAdapter(list[CompanyValuationResult]).validate_python(results_raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise CanonicalValuationValidationError(f"invalid canonical valuation bundle: {exc}") from exc
    ids = [row.valuation_result_id for row in results]
    companies = [row.company_id for row in results]
    if len(ids) != len(set(ids)):
        raise CanonicalValuationValidationError("duplicate valuation_result_id")
    if len(companies) != len(set(companies)):
        raise CanonicalValuationValidationError("duplicate company valuation result")
    if manifest.get("uses_current_price") is not False or manifest.get("uses_legacy_valuation") is not False:
        raise CanonicalValuationValidationError("manifest violates independent valuation boundary")
    if manifest.get("company_count") != len(results):
        raise CanonicalValuationValidationError("manifest company_count mismatch")
    return {"company_count": len(results), "completed": sum(x.status == "completed" for x in results), "partial": sum(x.status == "partial" for x in results), "unavailable": sum(x.status == "unavailable" for x in results)}
