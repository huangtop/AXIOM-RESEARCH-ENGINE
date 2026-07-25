from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

LAYER_TERMS = {
    "financial": {
        "path": ("financial", "financials", "fundamental", "xbrl"),
        "keys": ("revenue", "ebitda", "net_income", "equity", "book_value", "assets", "liabilities", "cash_flow", "eps"),
    },
    "market": {
        "path": ("market", "quote", "price", "snapshot", "security_price"),
        "keys": ("price", "market_cap", "shares_outstanding", "enterprise_value", "as_of", "close", "last_price"),
    },
    "estimate": {
        "path": ("estimate", "consensus", "forecast", "forward", "analyst"),
        "keys": ("forward_eps", "forward_revenue", "eps_estimate", "revenue_estimate", "consensus", "growth", "target_price"),
    },
}
EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
NEGATIVE_PATH_TERMS = ("test", "sample", "example", "fixture", "demo", "onboarding", "backup", "archive", "diagnostic")
POSITIVE_PATH_TERMS = ("production", "population", "canonical", "generated", "data")
ID_KEYS = ("company_id", "entity_id", "issuer_id", "security_id", "ticker", "symbol", "cik")

@dataclass(frozen=True)
class UniverseIndex:
    company_ids: frozenset[str]
    security_ids: frozenset[str]
    tickers: frozenset[str]
    cik_tokens: frozenset[str]


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def _flatten_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        preferred = ("records", "rows", "items", "data", "results", "companies", "securities", "facts", "snapshots", "estimates")
        for key in preferred:
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        # Mapping keyed by company/security id.
        if payload and all(isinstance(v, dict) for v in payload.values()):
            rows = []
            for key, value in payload.items():
                row = dict(value)
                row.setdefault("_mapping_key", key)
                rows.append(row)
            return rows
    return []


def _read_rows(path: Path, max_rows: int = 200_000) -> tuple[list[dict[str, Any]], str | None]:
    try:
        suffix = path.suffix.lower()
        if suffix == ".json":
            return _flatten_rows(json.loads(path.read_text(encoding="utf-8")))[:max_rows], None
        if suffix in {".jsonl", ".ndjson"}:
            rows = []
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if len(rows) >= max_rows:
                        break
                    line = line.strip()
                    if line:
                        value = json.loads(line)
                        if isinstance(value, dict):
                            rows.append(value)
            return rows, None
        if suffix == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as fh:
                return [dict(r) for _, r in zip(range(max_rows), csv.DictReader(fh))], None
    except Exception as exc:  # diagnostic only
        return [], f"{type(exc).__name__}: {exc}"
    return [], "unsupported_format"


def load_universe(repository_root: Path, population_dir: Path | None = None) -> UniverseIndex:
    base = population_dir if population_dir and population_dir.is_absolute() else repository_root / (population_dir or Path("data/universe"))
    companies_path = base / "companies.json"
    securities_path = base / "securities.json"
    companies = _flatten_rows(json.loads(companies_path.read_text(encoding="utf-8")))
    securities = _flatten_rows(json.loads(securities_path.read_text(encoding="utf-8")))
    company_ids = {_norm(r.get("company_id") or r.get("entity_id") or r.get("id")) for r in companies}
    security_ids = {_norm(r.get("security_id") or r.get("id")) for r in securities}
    tickers = {_norm(r.get("ticker") or r.get("symbol")) for r in securities}
    cik_tokens = set()
    for row in companies + securities:
        for key in ("cik", "company_id", "entity_id"):
            value = _norm(row.get(key))
            m = re.search(r"CIK0*(\d+)", value)
            if m:
                cik_tokens.add(m.group(1))
    return UniverseIndex(frozenset(x for x in company_ids if x), frozenset(x for x in security_ids if x), frozenset(x for x in tickers if x), frozenset(cik_tokens))


def _candidate_tokens(row: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ID_KEYS + ("_mapping_key",):
        value = row.get(key)
        if value is None:
            continue
        token = _norm(value)
        if token:
            out.add(token)
            if token.startswith("COMPANY:"):
                out.add(token)
            if token.startswith("SECURITY:"):
                out.add(token)
            m = re.search(r"CIK0*(\d+)", token)
            if m:
                out.add(m.group(1))
    return out


def _linked(row: dict[str, Any], universe: UniverseIndex) -> bool:
    tokens = _candidate_tokens(row)
    return bool(tokens & universe.company_ids or tokens & universe.security_ids or tokens & universe.tickers or tokens & universe.cik_tokens)


def _key_evidence(rows: list[dict[str, Any]], layer: str) -> tuple[list[str], float]:
    keys: set[str] = set()
    for row in rows[:100]:
        keys.update(str(k).lower() for k in row.keys())
    matches = sorted(k for term in LAYER_TERMS[layer]["keys"] for k in keys if term in k)
    unique = sorted(set(matches))
    return unique, min(1.0, len(unique) / 3.0)


def classify_candidate(path: Path, rows: list[dict[str, Any]], universe: UniverseIndex, repository_root: Path) -> list[dict[str, Any]]:
    rel = path.relative_to(repository_root).as_posix()
    low = rel.lower()
    row_count = len(rows)
    linked = sum(1 for row in rows if _linked(row, universe))
    coverage = linked / max(1, len(universe.company_ids))
    link_ratio = linked / max(1, row_count)
    results = []
    for layer in LAYER_TERMS:
        path_hits = sorted({term for term in LAYER_TERMS[layer]["path"] if term in low})
        key_hits, key_strength = _key_evidence(rows, layer)
        if not path_hits and not key_hits:
            continue
        score = 0.0
        score += min(25.0, 8.0 * len(path_hits))
        score += 25.0 * key_strength
        score += min(25.0, 25.0 * math.sqrt(min(1.0, coverage)))
        score += min(15.0, 15.0 * link_ratio)
        if any(term in low for term in POSITIVE_PATH_TERMS):
            score += 5.0
        penalties = [term for term in NEGATIVE_PATH_TERMS if term in low]
        score -= 12.0 * len(penalties)
        if row_count < 20:
            score -= 8.0
        if linked == 0:
            score -= 18.0
        score = round(max(0.0, min(100.0, score)), 2)
        results.append({
            "layer": layer,
            "path": rel,
            "format": path.suffix.lower().lstrip("."),
            "row_count": row_count,
            "linked_company_count": linked,
            "coverage_pct": round(coverage * 100, 4),
            "link_ratio_pct": round(link_ratio * 100, 4),
            "score": score,
            "path_evidence": path_hits,
            "key_evidence": key_hits,
            "penalties": penalties,
            "selection_eligible": linked > 0 and score >= 20.0,
        })
    return results


def discover(repository_root: Path, population_dir: Path | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    universe = load_universe(repository_root, population_dir)
    roots = config.get("scan_roots", ["data"])
    max_bytes = int(config.get("max_file_bytes", 250_000_000))
    candidates: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    seen: set[Path] = set()
    for root_name in roots:
        root = repository_root / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            if any(part in EXCLUDED_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in {".json", ".jsonl", ".ndjson", ".csv"}:
                continue
            if path.stat().st_size > max_bytes:
                unreadable.append({"path": path.relative_to(repository_root).as_posix(), "error": "file_too_large"})
                continue
            rows, error = _read_rows(path)
            if error:
                unreadable.append({"path": path.relative_to(repository_root).as_posix(), "error": error})
                continue
            if not rows:
                continue
            candidates.extend(classify_candidate(path, rows, universe, repository_root))
    candidates.sort(key=lambda x: (x["layer"], -x["score"], -x["linked_company_count"], x["path"]))
    selections: dict[str, Any] = {}
    for layer in LAYER_TERMS:
        layer_candidates = [x for x in candidates if x["layer"] == layer]
        eligible = [x for x in layer_candidates if x["selection_eligible"]]
        selections[layer] = dict(eligible[0]) if eligible else None
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "population-manifest.v030.35",
        "version": "V030.35",
        "generated_at": now,
        "repository_root": ".",
        "universe": {
            "company_count": len(universe.company_ids),
            "security_count": len(universe.security_ids),
            "ticker_count": len(universe.tickers),
        },
        "selections": selections,
        "selection_status": {layer: ("selected" if selections[layer] else "missing") for layer in LAYER_TERMS},
        "candidate_count": len(candidates),
        "candidates": candidates,
        "unreadable_files": unreadable,
    }


def validate_manifest(manifest: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if manifest.get("schema_version") != "population-manifest.v030.35":
        errors.append("invalid_schema_version")
    selections = manifest.get("selections")
    if not isinstance(selections, dict):
        errors.append("missing_selections")
        selections = {}
    for layer in LAYER_TERMS:
        selected = selections.get(layer)
        if selected is None:
            warnings.append(f"{layer}_source_missing")
            continue
        path = selected.get("path")
        if not path or not (repository_root / path).is_file():
            errors.append(f"{layer}_selected_path_missing")
        if selected.get("layer") != layer:
            errors.append(f"{layer}_selection_layer_mismatch")
        if int(selected.get("linked_company_count", 0)) <= 0:
            errors.append(f"{layer}_selection_has_zero_linkage")
        if not bool(selected.get("selection_eligible")):
            errors.append(f"{layer}_selection_not_eligible")
    paths = [v.get("path") for v in selections.values() if isinstance(v, dict)]
    if len(paths) != len(set(paths)):
        warnings.append("same_source_selected_for_multiple_layers")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "selected_layer_count": sum(1 for v in selections.values() if isinstance(v, dict)),
        "missing_layers": [k for k in LAYER_TERMS if not isinstance(selections.get(k), dict)],
        "candidate_count": manifest.get("candidate_count", 0),
    }


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = dict(payload)
    candidates = manifest.pop("candidates", [])
    unreadable = manifest.pop("unreadable_files", [])
    (output_dir / "population_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "population_source_inventory.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": payload["schema_version"],
        "version": payload["version"],
        "generated_at": payload["generated_at"],
        "selection_status": payload["selection_status"],
        "selections": payload["selections"],
        "candidate_count": len(candidates),
        "unreadable_files": unreadable,
    }
    (output_dir / "population_discovery_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
