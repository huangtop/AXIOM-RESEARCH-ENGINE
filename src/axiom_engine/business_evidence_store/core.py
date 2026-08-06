from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_business_evidence(path: Path) -> list[dict[str, Any]]:
    """Load legacy monolith plus sharded evidence without duplicating accessions."""
    root = path if path.is_dir() else path.parent
    records: dict[str, dict[str, Any]] = {}
    legacy = root / "business_evidence.json"
    if legacy.is_file():
        for position, row in enumerate(_load(legacy)):
            key = str(row.get("business_evidence_id") or f"legacy:{row.get('company_id')}:{position}")
            records[key] = row
    index = root / "index.json"
    if index.is_file():
        payload = _load(index)
        for filename in sorted(set((payload.get("company_id_to_file") or {}).values())):
            shard = root / str(filename)
            if not shard.is_file():
                continue
            for row in _load(shard):
                records[str(row["business_evidence_id"])] = row
    return sorted(records.values(), key=lambda row: (str(row.get("company_id") or ""), str(row.get("accession_number") or "")))


def write_business_evidence_shards(records: Iterable[Mapping[str, Any]], root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    shard_root = root / "per-company"
    shard_root.mkdir(parents=True, exist_ok=True)
    by_company: dict[str, list[Mapping[str, Any]]] = {}
    for row in records:
        by_company.setdefault(str(row["company_id"]), []).append(row)
    files: dict[str, str] = {}
    for company_id, rows in sorted(by_company.items()):
        filename = quote(company_id, safe="._-") + ".json"
        relative = f"per-company/{filename}"
        files[company_id] = relative
        target = root / relative
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(sorted(rows, key=lambda row: str(row.get("accession_number") or "")), ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    index = {
        "schema_version": "business-evidence-index.v031.2c",
        "company_count": len(files),
        "evidence_count": sum(len(rows) for rows in by_company.values()),
        "company_id_to_file": files,
    }
    temporary = root / "index.json.tmp"
    temporary.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, root / "index.json")
    return index
