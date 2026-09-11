from __future__ import annotations

import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from axiom_engine.coverage_policy import CoveragePolicyNotFound, CoveragePolicyService, CoveragePublicationDenied
from axiom_engine.full_market_coverage.core import build_full_market_coverage


class PublicationGateError(RuntimeError):
    pass


PUBLICATION_SHARD_RETENTION_GENERATIONS = 2
PUBLICATION_SHARD_RETENTION_FILE = "shard_retention.json"


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationGateError(f"cannot read publication source {path}: {exc}") from exc


def _filename(ticker: str) -> str:
    return quote(ticker, safe="._-") + ".json"


def _manifest_shard_files(manifest: Mapping[str, Any]) -> list[str]:
    files: set[str] = set()
    for row in (manifest.get("companies") or {}).values():
        if not isinstance(row, Mapping):
            continue
        path = Path(str(row.get("path") or ""))
        if path.parent == Path("companies") and path.name.endswith(".json"):
            files.add(path.name)
    return sorted(files)


def _card_symbols(card: Mapping[str, Any]) -> set[str]:
    symbols = {
        str((card.get("primary_security") or {}).get("ticker") or "").strip().upper()
    }
    symbols.update(
        str(row.get("ticker") or "").strip().upper()
        for row in (card.get("securities") or [])
        if isinstance(row, Mapping)
    )
    symbols.discard("")
    return symbols


def _valuation_cards(
    root: Path,
    valuation_path: str,
    valuation: Mapping[str, Any],
    *,
    symbols: set[str] | None = None,
):
    cards = valuation.get("cards")
    if isinstance(cards, list):
        for card in cards:
            if not isinstance(card, Mapping):
                continue
            if symbols is not None and not _card_symbols(card).intersection(symbols):
                continue
            yield card
        return

    indexes = valuation.get("indexes") or {}
    base = (root / valuation_path).parent

    if symbols is not None:
        ticker_to_file = indexes.get("ticker_to_file") or {}
        filenames = {
            str(ticker_to_file[symbol])
            for symbol in symbols
            if symbol in ticker_to_file
        }
        for filename in sorted(filenames):
            path = base / filename
            if not path.is_file():
                raise PublicationGateError(
                    f"valuation artifact missing for selected symbol: {path}"
                )
            card = _load(path)
            if isinstance(card, Mapping):
                yield card
        return

    file_index = indexes.get("company_id_to_file") or {}
    for company_id, filename in sorted(file_index.items()):
        path = base / str(filename)
        if not path.is_file():
            raise PublicationGateError(f"valuation artifact missing for {company_id}: {path}")
        card = _load(path)
        if isinstance(card, Mapping):
            yield card


def build_publication_catalog(
    root: Path,
    *,
    coverage_path: str = "data/generated/coverage_policy/coverage_policy.json",
    valuation_path: str = "data/generated/full_market_coverage/full_market_coverage.json",
    now: datetime | None = None,
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    selected_symbols = (
        {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
        if symbols is not None
        else None
    )
    coverage = _load(root / coverage_path)
    valuation_file = root / valuation_path
    valuation = _load(valuation_file) if valuation_file.is_file() else build_full_market_coverage(root)
    if coverage.get("schema_version") != "coverage-policy-projection.v031f.2.1":
        raise PublicationGateError("V031F.2.1 Coverage Policy is required")
    if valuation.get("schema_version") not in {
        "full-market-coverage.v031.0",
        "full-market-valuation-index.v031g.1",
    }:
        raise PublicationGateError("V031 full-market valuation or V031G shard index is required")

    coverage_service = CoveragePolicyService(root=root, projection_path=root / coverage_path)
    records: list[dict[str, Any]] = []
    projections: dict[str, dict[str, Any]] = {}
    for card in _valuation_cards(
        root,
        valuation_path,
        valuation,
        symbols=selected_symbols,
    ):
        ticker = str((card.get("primary_security") or {}).get("ticker") or "").upper()
        if not ticker:
            continue
        try:
            decision = coverage_service.require_public(ticker, capability="valuation_card")
        except (CoveragePublicationDenied, CoveragePolicyNotFound):
            continue
        company_id = str((card.get("company") or {}).get("company_id") or decision["company_id"])
        valuation_summary = card.get("valuation") or {}
        market = card.get("market") or {}
        scope_axes = dict(decision.get("scope_axes") or {})
        records.append({
            "company_id": company_id,
            "ticker": ticker,
            "display_name": (card.get("company") or {}).get("display_name"),
            "product_scope": decision.get("product_scope") or "basic_market",
            "research_scope": decision.get("research_scope") or "contextual",
            "scope_axes": scope_axes,
            "valuation_status": valuation_summary.get("status"),
            "calculated_model_count": int(valuation_summary.get("calculated_model_count") or 0),
            "current_price": market.get("current_price"),
            "fair_value": valuation_summary.get("fair_value"),
        })
        projections[ticker] = {
            "schema_version": "company-page-projection.v031f.2.1",
            "version": "V031F.2.1",
            "company_id": company_id,
            "ticker": ticker,
            "product_scope": decision.get("product_scope") or "basic_market",
            "research_scope": decision.get("research_scope") or "contextual",
            "scope_axes": scope_axes,
            "coverage_policy": {
                "reason_codes": list(decision.get("reason_codes") or []),
                "review_status": decision.get("review_status"),
            },
            "valuation_card": card,
        }

    records.sort(key=lambda row: str(row.get("ticker") or ""))
    index: dict[str, str] = {}
    for ticker, projection in projections.items():
        filename = _filename(ticker)
        card = projection.get("valuation_card") or {}
        for security in card.get("securities") or []:
            alias = str(security.get("ticker") or "").upper()
            if alias:
                index[alias] = filename
        index[ticker] = filename
    axis_counts = {
        axis: sum(bool((row.get("scope_axes") or {}).get(axis)) for row in records)
        for axis in (
            "research_page",
            "news_ai",
            "etf_exposure",
            "etf_change_analysis",
            "supply_chain_analysis",
            "supply_chain_context",
            "deep_research",
        )
    }
    return {
        "schema_version": "publication-gate-catalog.v031f.2.1",
        "version": "V031F.2.1",
        "generated_at": current.isoformat(),
        "summary": {
            "public_company_count": len(records),
            "incremental": selected_symbols is not None,
            "selected_symbol_count": (
                len(selected_symbols) if selected_symbols is not None else None
            ),
            "basic_market_count": sum(row["product_scope"] == "basic_market" for row in records),
            "frontier_research_count": sum(row["product_scope"] == "frontier_research" for row in records),
            "scope_axis_counts": axis_counts,
            "per_company_projection_count": len(projections),
        },
        "contract": {
            "operating_company_pages_are_market_wide": True,
            "research_actions_determine_basic_publication": False,
            "non_company_instruments_emitted": False,
            "single_company_lookup_requires_full_market_snapshot": False,
        },
        "companies": records,
        "indexes": {"ticker_to_file": index},
        "_company_projections": projections,
    }


def _merge_ticker_file_index(
    previous: Mapping[str, Any],
    updates: Mapping[str, Any],
    projections: Mapping[str, Any],
) -> dict[str, str]:
    merged = {str(alias): str(filename) for alias, filename in previous.items()}
    for ticker in projections:
        old_filename = _filename(str(ticker))
        for alias, filename in list(merged.items()):
            if filename == old_filename:
                merged.pop(alias, None)
    for alias, filename in updates.items():
        merged[str(alias)] = str(filename)
    return dict(sorted(merged.items()))


def write_publication_catalog(
    report: Mapping[str, Any],
    output: Path,
    *,
    retention_generations: int = PUBLICATION_SHARD_RETENTION_GENERATIONS,
    incremental: bool = False,
) -> None:
    if retention_generations < 2:
        raise ValueError("retention_generations must be at least 2")
    output.parent.mkdir(parents=True, exist_ok=True)

    if incremental and not output.is_file():
        raise PublicationGateError(
            "incremental publication write requires an existing company catalog"
        )

    projections = report.get("_company_projections") or {}
    previous_manifest = (
        _load(output.parent / "manifest.json")
        if (output.parent / "manifest.json").is_file()
        else {}
    )
    if incremental and not previous_manifest:
        raise PublicationGateError(
            "incremental publication write requires an existing manifest"
        )

    previous_catalog = _load(output) if incremental else {}
    previous_by_company = {
        str(row.get("company_id")): str(row.get("sha256"))
        for row in (previous_manifest.get("companies") or {}).values()
        if isinstance(row, Mapping) and row.get("company_id")
    }

    company_root = output.parent / "companies"
    company_root.mkdir(parents=True, exist_ok=True)

    company_entries: dict[str, dict[str, Any]] = (
        {
            str(ticker): dict(row)
            for ticker, row in (previous_manifest.get("companies") or {}).items()
            if isinstance(row, Mapping)
        }
        if incremental
        else {}
    )

    for ticker, projection in sorted(projections.items()):
        body = (
            json.dumps(projection, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode()
        digest = hashlib.sha256(body).hexdigest()
        filename = f"{quote(str(ticker), safe='._-')}.{digest[:16]}.json"
        path = company_root / filename
        if not path.is_file() or path.read_bytes() != body:
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(body)
            os.replace(temporary, path)

        company_id = str(projection.get("company_id") or "")
        company_entries[str(ticker)] = {
            "company_id": company_id,
            "path": f"companies/{filename}",
            "url": f"/v1/publication/companies/{filename}",
            "sha256": digest,
            "size_bytes": len(body),
        }

    current_by_company = {
        str(row.get("company_id")): str(row.get("sha256"))
        for row in company_entries.values()
        if isinstance(row, Mapping) and row.get("company_id")
    }
    changed_company_ids = sorted(
        {
            str(projection.get("company_id") or "")
            for projection in projections.values()
            if str(projection.get("company_id") or "")
            and previous_by_company.get(str(projection.get("company_id") or ""))
            != current_by_company.get(str(projection.get("company_id") or ""))
        }
    )
    removed_company_ids = (
        []
        if incremental
        else sorted(set(previous_by_company) - set(current_by_company))
    )

    previous_manifest_indexes = previous_manifest.get("indexes") or {}
    report_indexes = report.get("indexes") or {}
    manifest_ticker_index = _merge_ticker_file_index(
        (previous_manifest_indexes.get("ticker_to_file") or {})
        if incremental
        else {},
        report_indexes.get("ticker_to_file") or {},
        projections,
    )

    release_material = "\n".join(
        f"{ticker}:{row['sha256']}"
        for ticker, row in sorted(company_entries.items())
    )
    release_id = hashlib.sha256(release_material.encode()).hexdigest()

    manifest = {
        "schema_version": "incremental-publication-manifest.v1",
        "release_id": release_id,
        "generated_at": report.get("generated_at"),
        "company_count": len(company_entries),
        "changed_company_ids": changed_company_ids,
        "removed_company_ids": removed_company_ids,
        "companies": dict(sorted(company_entries.items())),
        "indexes": {"ticker_to_file": manifest_ticker_index},
        "cache_policy": {
            "manifest": "public, max-age=60, must-revalidate",
            "company_shards": "public, max-age=31536000, immutable",
        },
        "retention_policy": {
            "company_shard_generations": retention_generations,
        },
    }

    manifest_path = output.parent / "manifest.json"
    manifest_tmp = manifest_path.with_suffix(".json.tmp")
    manifest_tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(manifest_tmp, manifest_path)

    current_files = set(_manifest_shard_files(manifest))
    retention_path = output.parent / PUBLICATION_SHARD_RETENTION_FILE
    if retention_path.is_file():
        retention = _load(retention_path)
        previous_generations = retention.get("generations") or []
    elif previous_manifest:
        previous_generations = [{
            "release_id": previous_manifest.get("release_id"),
            "files": _manifest_shard_files(previous_manifest),
        }]
    else:
        previous_generations = []

    generations = [{"release_id": release_id, "files": sorted(current_files)}]
    generations.extend(
        generation
        for generation in previous_generations
        if isinstance(generation, Mapping)
        and generation.get("release_id") != release_id
    )
    generations = generations[:retention_generations]

    retained_files = {
        str(filename)
        for generation in generations
        for filename in (generation.get("files") or [])
    }
    retention_payload = {
        "schema_version": "publication-shard-retention.v1",
        "retention_generations": retention_generations,
        "generations": generations,
    }
    retention_tmp = retention_path.with_suffix(".json.tmp")
    retention_tmp.write_text(
        json.dumps(retention_payload, ensure_ascii=False, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    os.replace(retention_tmp, retention_path)

    for stale in company_root.glob("*.json"):
        if stale.name not in retained_files:
            stale.unlink()

    if not incremental:
        archive = output.parent / "company_projections.zip"
        temporary_archive = archive.with_suffix(".zip.tmp")
        with ZipFile(
            temporary_archive,
            "w",
            compression=ZIP_DEFLATED,
            compresslevel=9,
        ) as bundle:
            for ticker, projection in sorted(projections.items()):
                bundle.writestr(
                    _filename(str(ticker)),
                    json.dumps(projection, ensure_ascii=False, separators=(",", ":"))
                    + "\n",
                )
        temporary_archive.replace(archive)

    if incremental:
        previous_companies = {
            str(row.get("ticker") or ""): dict(row)
            for row in (previous_catalog.get("companies") or [])
            if isinstance(row, Mapping) and row.get("ticker")
        }
        for row in report.get("companies") or []:
            if isinstance(row, Mapping) and row.get("ticker"):
                previous_companies[str(row["ticker"])] = dict(row)

        previous_catalog_indexes = previous_catalog.get("indexes") or {}
        catalog_ticker_index = _merge_ticker_file_index(
            previous_catalog_indexes.get("ticker_to_file") or {},
            report_indexes.get("ticker_to_file") or {},
            projections,
        )
        serializable = {
            key: value
            for key, value in previous_catalog.items()
            if key not in {"generated_at", "companies", "indexes", "summary"}
        }
        serializable["generated_at"] = report.get("generated_at")
        serializable["summary"] = dict(previous_catalog.get("summary") or {})
        serializable["companies"] = [
            previous_companies[ticker]
            for ticker in sorted(previous_companies)
        ]
        serializable["indexes"] = {"ticker_to_file": catalog_ticker_index}
    else:
        serializable = {
            key: value
            for key, value in report.items()
            if key != "_company_projections"
        }

    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(serializable, ensure_ascii=False, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)