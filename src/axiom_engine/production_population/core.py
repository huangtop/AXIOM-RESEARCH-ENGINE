from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LAYERS = ("financial", "market", "estimate")
ID_KEYS = ("company_id", "entity_id", "issuer_id")
SECURITY_KEYS = ("security_id",)
TICKER_KEYS = ("ticker", "symbol")

FINANCIAL_VALUE_KEYS = {
    "revenue", "revenues", "sales", "net_income", "operating_income", "ebit", "ebitda",
    "eps", "assets", "liabilities", "equity", "cash", "free_cash_flow", "operating_cash_flow",
}
MARKET_VALUE_KEYS = {
    "price", "market_price", "last_price", "close", "previous_close", "volume", "market_cap",
    "shares_outstanding", "beta",
}
ESTIMATE_VALUE_KEYS = {
    "forward_eps", "eps_estimate", "eps_fy1", "revenue_estimate", "revenue_fy1", "ebit_estimate",
    "ebit_fy1", "ebitda_estimate", "target_price", "analyst_count", "consensus_eps",
}
BLANK_TOKENS = {"", "-", "--", "N/A", "NA", "NULL", "NONE", "PENDING", "TBD"}
USABLE_STATES = {
    "financial": {"official", "partial"},
    "market": {"realtime", "snapshot", "historical"},
    "estimate": {"complete"},
}


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("records", "rows", "items", "data", "results", "facts", "snapshots", "estimates", "companies", "securities"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        if payload and all(isinstance(v, dict) for v in payload.values()):
            return [dict(v, _mapping_key=k) for k, v in payload.items()]
    return []


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        return _rows(json.loads(path.read_text(encoding="utf-8")))
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                value = json.loads(line)
                if isinstance(value, dict):
                    out.append(value)
        return out
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    raise ValueError(f"unsupported source format: {path}")


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def _cik(value: Any) -> str | None:
    m = re.search(r"CIK0*(\d+)", _norm(value))
    return m.group(1) if m else None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().upper() not in BLANK_TOKENS
    return True


def _record_has_any_value(records: list[dict[str, Any]], keys: set[str]) -> bool:
    return any(_has_value(row.get(key)) for row in records for key in keys if key in row)


def _record_state(layer: str, records: list[dict[str, Any]], selected: dict[str, Any] | None) -> str:
    if not records:
        return "missing"
    if layer == "financial":
        return "official" if _record_has_any_value(records, FINANCIAL_VALUE_KEYS) else "partial"
    if layer == "estimate":
        statuses = {_norm(row.get("status") or row.get("record_state")) for row in records}
        if statuses & {"PENDING", "QUEUED", "REQUESTED"}:
            return "pending"
        return "complete" if _record_has_any_value(records, ESTIMATE_VALUE_KEYS) else "placeholder"
    # Market source freshness/type is source-level metadata. Prefer explicit fields, then path hints.
    source_path = _norm((selected or {}).get("path"))
    source_kind = _norm((selected or {}).get("market_state") or (selected or {}).get("record_state"))
    if source_kind in {"REALTIME", "SNAPSHOT", "HISTORICAL"}:
        return source_kind.lower()
    if any(token in source_path for token in ("REALTIME", "INTRADAY", "LIVE")):
        return "realtime"
    if any(token in source_path for token in ("HISTORICAL", "HISTORY", "EOD", "DAILY")):
        return "historical"
    return "snapshot"


def load_registry(repository_root: Path, population_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base = population_dir if population_dir.is_absolute() else repository_root / population_dir
    companies = _rows(json.loads((base / "companies.json").read_text(encoding="utf-8")))
    securities = _rows(json.loads((base / "securities.json").read_text(encoding="utf-8")))
    return companies, securities


def build_indexes(companies: list[dict[str, Any]], securities: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    company_by_id: dict[str, str] = {}
    company_by_security: dict[str, str] = {}
    company_by_ticker: dict[str, str] = {}
    company_by_cik: dict[str, str] = {}
    for company in companies:
        cid = str(company.get("company_id") or company.get("entity_id") or "")
        if not cid:
            continue
        company_by_id[_norm(cid)] = cid
        cik = _cik(cid) or _cik(company.get("cik")) or _cik((company.get("metadata") or {}).get("cik"))
        if cik:
            company_by_cik[cik] = cid
    for sec in securities:
        cid = str(sec.get("company_id") or "")
        if not cid:
            continue
        sid = _norm(sec.get("security_id"))
        ticker = _norm(sec.get("ticker") or sec.get("symbol"))
        if sid:
            company_by_security[sid] = cid
        if ticker:
            company_by_ticker[ticker] = cid
        cik = _cik(sec.get("company_id")) or _cik((sec.get("metadata") or {}).get("cik"))
        if cik:
            company_by_cik[cik] = cid
    return {"company": company_by_id, "security": company_by_security, "ticker": company_by_ticker, "cik": company_by_cik}


def resolve_company_id(row: dict[str, Any], indexes: dict[str, dict[str, str]]) -> tuple[str | None, str | None]:
    for key in ID_KEYS + ("_mapping_key",):
        value = row.get(key)
        token = _norm(value)
        if token in indexes["company"]:
            return indexes["company"][token], f"{key}:company_id"
        cik = _cik(value)
        if cik and cik in indexes["cik"]:
            return indexes["cik"][cik], f"{key}:cik"
    for key in SECURITY_KEYS:
        token = _norm(row.get(key))
        if token in indexes["security"]:
            return indexes["security"][token], f"{key}:security_id"
    for key in TICKER_KEYS:
        token = _norm(row.get(key))
        if token in indexes["ticker"]:
            return indexes["ticker"][token], f"{key}:ticker"
    cik = _cik(row.get("cik"))
    if cik and cik in indexes["cik"]:
        return indexes["cik"][cik], "cik"
    return None, None


def _primary_security_map(companies: list[dict[str, Any]], securities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    by_id = {str(s.get("security_id")): s for s in securities if s.get("security_id")}
    for company in companies:
        cid = str(company.get("company_id"))
        sid = company.get("primary_security_id")
        if sid and str(sid) in by_id:
            result[cid] = by_id[str(sid)]
    for sec in securities:
        cid = str(sec.get("company_id") or "")
        if cid and cid not in result and sec.get("primary_listing"):
            result[cid] = sec
    return result


def build_population(repository_root: Path, population_dir: Path, manifest_path: Path, *, strict: bool = False) -> dict[str, Any]:
    companies, securities = load_registry(repository_root, population_dir)
    indexes = build_indexes(companies, securities)
    primary_security = _primary_security_map(companies, securities)
    manifest_file = manifest_path if manifest_path.is_absolute() else repository_root / manifest_path
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    selections = manifest.get("selections") or {}
    now = datetime.now(timezone.utc).isoformat()
    layer_groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    layer_diagnostics: dict[str, Any] = {}

    for layer in LAYERS:
        selected = selections.get(layer)
        source_rows: list[dict[str, Any]] = []
        source_path: str | None = None
        if isinstance(selected, dict) and selected.get("path"):
            source_path = str(selected["path"])
            source_rows = read_rows(repository_root / source_path)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        unresolved = 0
        linkage_methods: dict[str, int] = defaultdict(int)
        for row in source_rows:
            cid, method = resolve_company_id(row, indexes)
            if cid:
                groups[cid].append(row)
                linkage_methods[str(method)] += 1
            else:
                unresolved += 1
        layer_groups[layer] = groups
        layer_diagnostics[layer] = {
            "source_path": source_path,
            "source_semantic_type": selected.get("semantic_type") if isinstance(selected, dict) else None,
            "source_row_count": len(source_rows),
            "linked_row_count": sum(len(v) for v in groups.values()),
            "linked_company_count": len(groups),
            "unresolved_row_count": unresolved,
            "linked_coverage_pct": round(len(groups) / max(1, len(companies)) * 100, 4),
            "coverage_pct": round(len(groups) / max(1, len(companies)) * 100, 4),
            "linkage_methods": dict(sorted(linkage_methods.items())),
        }

    populations: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYERS}
    combined: list[dict[str, Any]] = []
    state_counts: dict[str, Counter[str]] = {layer: Counter() for layer in LAYERS}
    for company in companies:
        cid = str(company.get("company_id"))
        sec = primary_security.get(cid, {})
        presence: dict[str, bool] = {}
        usability: dict[str, bool] = {}
        states: dict[str, str] = {}
        counts: dict[str, int] = {}
        for layer in LAYERS:
            records = layer_groups[layer].get(cid, [])
            selected = selections.get(layer) if isinstance(selections.get(layer), dict) else None
            state = _record_state(layer, records, selected)
            usable = state in USABLE_STATES[layer]
            presence[layer] = bool(records)
            usability[layer] = usable
            states[layer] = state
            counts[layer] = len(records)
            state_counts[layer][state] += 1
            populations[layer].append({
                "schema_version": f"production-{layer}-population.v030.5",
                "company_id": cid,
                "security_id": sec.get("security_id") or company.get("primary_security_id"),
                "ticker": sec.get("ticker") or sec.get("symbol"),
                "display_name": company.get("display_name") or company.get("legal_name"),
                "record_state": state,
                "linked": bool(records),
                "usable": usable,
                "data_present": bool(records),  # compatibility alias
                "source_record_count": len(records),
                "source_records": records,
            })
        usable_count = sum(usability.values())
        linked_count = sum(presence.values())
        if usable_count == len(LAYERS):
            readiness = "production_ready"
        elif usable_count > 0:
            readiness = "partial_ready"
        elif linked_count > 0:
            readiness = "linked_unusable"
        else:
            readiness = "empty"
        combined.append({
            "schema_version": "production-population-index.v030.5",
            "company_id": cid,
            "security_id": sec.get("security_id") or company.get("primary_security_id"),
            "ticker": sec.get("ticker") or sec.get("symbol"),
            "display_name": company.get("display_name") or company.get("legal_name"),
            "record_states": states,
            "data_presence": presence,
            "data_usability": usability,
            "source_record_counts": counts,
            "readiness_state": readiness,
            "production_ready": readiness == "production_ready",
            "complete": all(presence.values()),  # compatibility aliases
            "partial": any(presence.values()) and not all(presence.values()),
            "empty": not any(presence.values()),
        })

    company_status_counts = dict(sorted(Counter(row["readiness_state"] for row in combined).items()))
    coverage: dict[str, Any] = {}
    for layer in LAYERS:
        linked = sum(1 for row in populations[layer] if row["linked"])
        usable = sum(1 for row in populations[layer] if row["usable"])
        coverage[layer] = {
            "linked": linked,
            "linked_pct": round(linked / max(1, len(companies)) * 100, 4),
            "usable": usable,
            "usable_pct": round(usable / max(1, len(companies)) * 100, 4),
            "states": dict(sorted(state_counts[layer].items())),
        }
        layer_diagnostics[layer]["usable_company_count"] = usable
        layer_diagnostics[layer]["usable_coverage_pct"] = coverage[layer]["usable_pct"]
        layer_diagnostics[layer]["record_state_counts"] = coverage[layer]["states"]

    readiness = {
        "production_ready_company_count": sum(1 for row in combined if row["production_ready"]),
        "financial_ready_company_count": coverage["financial"]["usable"],
        "market_ready_company_count": coverage["market"]["usable"],
        "estimate_ready_company_count": coverage["estimate"]["usable"],
    }
    summary = {
        "schema_version": "production-population-summary.v030.5",
        "version": "V030.5",
        "generated_at": now,
        "universe_company_count": len(companies),
        "universe_security_count": len(securities),
        "population_record_counts": {layer: len(populations[layer]) for layer in LAYERS},
        "coverage": coverage,
        "record_state_summary": {layer: dict(sorted(state_counts[layer].items())) for layer in LAYERS},
        "readiness": readiness,
        "company_status_counts": company_status_counts,
        # Compatibility fields remain linked-based and are explicitly deprecated.
        "data_present_company_counts": {layer: coverage[layer]["linked"] for layer in LAYERS},
        "coverage_pct": {layer: coverage[layer]["linked_pct"] for layer in LAYERS},
        "source_diagnostics": layer_diagnostics,
        "manifest_path": manifest_path.as_posix(),
    }
    errors = []
    if any(len(populations[layer]) != len(companies) for layer in LAYERS):
        errors.append("population_count_mismatch")
    if strict and errors:
        raise ValueError(", ".join(errors))
    return {"summary": summary, "populations": populations, "index": combined, "diagnostics": {"errors": errors, "layers": layer_diagnostics}}


def write_population(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "financial_population.json": result["populations"]["financial"],
        "market_population.json": result["populations"]["market"],
        "estimate_population.json": result["populations"]["estimate"],
        "population_index.json": result["index"],
        "population_summary.json": result["summary"],
        "population_diagnostics.json": result["diagnostics"],
    }
    for name, payload in mapping.items():
        (output_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_population(repository_root: Path, population_dir: Path, output_dir: Path) -> dict[str, Any]:
    companies, _ = load_registry(repository_root, population_dir)
    expected_ids = {str(x.get("company_id")) for x in companies}
    errors: list[str] = []
    stats: dict[str, Any] = {}
    valid_states = {
        "financial": {"official", "partial", "missing"},
        "market": {"realtime", "snapshot", "historical", "missing"},
        "estimate": {"complete", "placeholder", "pending", "missing"},
    }
    for layer in LAYERS:
        path = output_dir / f"{layer}_population.json"
        if not path.exists():
            errors.append(f"missing_{layer}_population")
            continue
        rows = _rows(json.loads(path.read_text(encoding="utf-8")))
        ids = [str(row.get("company_id")) for row in rows]
        duplicate_count = len(ids) - len(set(ids))
        missing = expected_ids - set(ids)
        unknown = set(ids) - expected_ids
        invalid_presence = sum(1 for row in rows if not isinstance(row.get("data_present"), bool))
        invalid_linked = sum(1 for row in rows if not isinstance(row.get("linked"), bool))
        invalid_usable = sum(1 for row in rows if not isinstance(row.get("usable"), bool))
        invalid_state = sum(1 for row in rows if row.get("record_state") not in valid_states[layer])
        inconsistent = sum(1 for row in rows if row.get("linked") != row.get("data_present"))
        if len(rows) != len(companies): errors.append(f"{layer}_record_count_mismatch")
        if duplicate_count: errors.append(f"{layer}_duplicates")
        if missing: errors.append(f"{layer}_missing_companies")
        if unknown: errors.append(f"{layer}_unknown_companies")
        if invalid_presence: errors.append(f"{layer}_invalid_presence")
        if invalid_linked: errors.append(f"{layer}_invalid_linked")
        if invalid_usable: errors.append(f"{layer}_invalid_usable")
        if invalid_state: errors.append(f"{layer}_invalid_record_state")
        if inconsistent: errors.append(f"{layer}_inconsistent_linked_presence")
        stats[layer] = {
            "record_count": len(rows),
            "duplicate_count": duplicate_count,
            "missing_company_count": len(missing),
            "unknown_company_count": len(unknown),
            "linked_company_count": sum(1 for row in rows if row.get("linked")),
            "usable_company_count": sum(1 for row in rows if row.get("usable")),
            "record_state_counts": dict(sorted(Counter(str(row.get("record_state")) for row in rows).items())),
            "data_present_company_count": sum(1 for row in rows if row.get("data_present")),
        }
    index_path = output_dir / "population_index.json"
    if not index_path.exists():
        errors.append("missing_population_index")
    else:
        index_rows = _rows(json.loads(index_path.read_text(encoding="utf-8")))
        if len(index_rows) != len(companies): errors.append("population_index_count_mismatch")
    summary_path = output_dir / "population_summary.json"
    if not summary_path.exists():
        errors.append("missing_population_summary")
    else:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("schema_version") != "production-population-summary.v030.5":
            errors.append("invalid_population_summary_schema_version")
        if not isinstance(summary.get("coverage"), dict):
            errors.append("missing_coverage_v2")
    return {"valid": not errors, "errors": errors, "universe_company_count": len(companies), "layers": stats, "output_dir": str(output_dir)}
