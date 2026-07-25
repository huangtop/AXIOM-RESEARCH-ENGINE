from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LAYERS = ("financial", "market", "estimate")
ID_KEYS = ("company_id", "entity_id", "issuer_id")
SECURITY_KEYS = ("security_id",)
TICKER_KEYS = ("ticker", "symbol")


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
            "source_row_count": len(source_rows),
            "linked_row_count": sum(len(v) for v in groups.values()),
            "linked_company_count": len(groups),
            "unresolved_row_count": unresolved,
            "coverage_pct": round(len(groups) / max(1, len(companies)) * 100, 4),
            "linkage_methods": dict(sorted(linkage_methods.items())),
        }

    populations: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYERS}
    combined: list[dict[str, Any]] = []
    for company in companies:
        cid = str(company.get("company_id"))
        sec = primary_security.get(cid, {})
        presence = {}
        counts = {}
        for layer in LAYERS:
            records = layer_groups[layer].get(cid, [])
            presence[layer] = bool(records)
            counts[layer] = len(records)
            populations[layer].append({
                "schema_version": f"production-{layer}-population.v030.4",
                "company_id": cid,
                "security_id": sec.get("security_id") or company.get("primary_security_id"),
                "ticker": sec.get("ticker") or sec.get("symbol"),
                "display_name": company.get("display_name") or company.get("legal_name"),
                "data_present": bool(records),
                "source_record_count": len(records),
                "source_records": records,
            })
        combined.append({
            "schema_version": "production-population-index.v030.4",
            "company_id": cid,
            "security_id": sec.get("security_id") or company.get("primary_security_id"),
            "ticker": sec.get("ticker") or sec.get("symbol"),
            "display_name": company.get("display_name") or company.get("legal_name"),
            "data_presence": presence,
            "source_record_counts": counts,
            "complete": all(presence.values()),
            "partial": any(presence.values()) and not all(presence.values()),
            "empty": not any(presence.values()),
        })

    complete = sum(1 for row in combined if row["complete"])
    partial = sum(1 for row in combined if row["partial"])
    empty = sum(1 for row in combined if row["empty"])
    summary = {
        "schema_version": "production-population-summary.v030.4",
        "version": "V030.4",
        "generated_at": now,
        "universe_company_count": len(companies),
        "universe_security_count": len(securities),
        "population_record_counts": {layer: len(populations[layer]) for layer in LAYERS},
        "data_present_company_counts": {layer: sum(1 for row in populations[layer] if row["data_present"]) for layer in LAYERS},
        "coverage_pct": {layer: round(sum(1 for row in populations[layer] if row["data_present"]) / max(1, len(companies)) * 100, 4) for layer in LAYERS},
        "company_status_counts": {"complete": complete, "partial": partial, "empty": empty},
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
        if len(rows) != len(companies): errors.append(f"{layer}_record_count_mismatch")
        if duplicate_count: errors.append(f"{layer}_duplicates")
        if missing: errors.append(f"{layer}_missing_companies")
        if unknown: errors.append(f"{layer}_unknown_companies")
        if invalid_presence: errors.append(f"{layer}_invalid_presence")
        stats[layer] = {"record_count": len(rows), "duplicate_count": duplicate_count, "missing_company_count": len(missing), "unknown_company_count": len(unknown), "data_present_company_count": sum(1 for row in rows if row.get("data_present"))}
    index_path = output_dir / "population_index.json"
    if not index_path.exists():
        errors.append("missing_population_index")
    else:
        index_rows = _rows(json.loads(index_path.read_text(encoding="utf-8")))
        if len(index_rows) != len(companies): errors.append("population_index_count_mismatch")
    return {"valid": not errors, "errors": errors, "universe_company_count": len(companies), "layers": stats, "output_dir": str(output_dir)}
