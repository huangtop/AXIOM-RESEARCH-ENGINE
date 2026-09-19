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


PUBLICATION_FINANCIAL_FIELDS = (
    "diluted_shares_outstanding",
    "shares_outstanding",
    "cash_and_cash_equivalents",
    "total_debt",
    "free_cash_flow",
    "ebitda",
    "book_value_per_share",
    "diluted_eps_ttm",
    "eps_ttm",
)

PUBLICATION_ESTIMATE_FIELDS = (
    "forward_eps",
    "forward_eps_growth",
    "growth_estimate",
    "forward_revenue",
    "forward_ebitda",
    "ebitda_ttm",
)

PUBLICATION_MODEL_FIELDS = (
    "status",
    "fair_value",
    "applicability",
    "role",
    "reason_code",
    "bear_fair_value",
    "base_fair_value",
    "bull_fair_value",
)


def _pick(source: Mapping[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {
        field: source[field]
        for field in fields
        if field in source
    }


def _publication_metric(metric: Any) -> Any:
    if not isinstance(metric, Mapping):
        return metric
    return _pick(metric, ("status", "value"))


def _publication_model(name: str, model: Any) -> Any:
    if not isinstance(model, Mapping):
        return model

    projected = _pick(model, PUBLICATION_MODEL_FIELDS)

    # The WordPress valuation consumer directly reads these Forward P/E
    # inputs. Other model input/assumption/parameter bags are backend
    # diagnostics and must not leak into the frontend publication payload.
    if name == "forward_pe":
        inputs = model.get("inputs")
        if isinstance(inputs, Mapping):
            projected_inputs = _pick(
                inputs,
                ("fiscal_year", "eps", "observed_trailing_pe"),
            )
            if projected_inputs:
                projected["inputs"] = projected_inputs

    return projected


def _publication_horizon(horizon: Any) -> Any:
    if not isinstance(horizon, Mapping):
        return horizon

    projected = _pick(
        horizon,
        (
            "fiscal_year",
            "eps",
            "revenue",
            "eps_growth",
            "growth_basis",
        ),
    )

    models = horizon.get("models")
    if isinstance(models, Mapping):
        projected["models"] = {
            str(name): _publication_model(str(name), model)
            for name, model in models.items()
        }

    return projected


def _publication_valuation(valuation: Any) -> dict[str, Any]:
    if not isinstance(valuation, Mapping):
        return {}

    projected = _pick(
        valuation,
        (
            "primary_model",
            "selected_model",
            "preferred_model",
            "fair_value",
        ),
    )

    profile = valuation.get("profile")
    if isinstance(profile, Mapping):
        projected_profile = _pick(profile, ("primary_model",))
        if projected_profile:
            projected["profile"] = projected_profile

    # The frontend only uses unified scenarios as a fallback for
    # bear/base/bull fair values. Do not publish the full unified contract.
    unified = valuation.get("unified_contract")
    if isinstance(unified, Mapping):
        scenarios = unified.get("scenarios")
        if isinstance(scenarios, Mapping):
            projected_scenarios: dict[str, Any] = {}
            for name in ("bear", "base", "bull"):
                row = scenarios.get(name)
                if isinstance(row, Mapping) and "fair_value" in row:
                    projected_scenarios[name] = {
                        "fair_value": row["fair_value"]
                    }
            if projected_scenarios:
                projected["unified_contract"] = {
                    "scenarios": projected_scenarios
                }

    return projected


def _publication_valuation_card(card: Mapping[str, Any]) -> dict[str, Any]:
    """Project a rich Full Market card onto the WordPress publication contract.

    This is deliberately a positive allowlist. New Full Market diagnostics,
    provenance, financial history, or backend-only model fields must not
    automatically increase immutable Publication shard size.
    """
    projected: dict[str, Any] = {}

    company = card.get("company")
    if isinstance(company, Mapping):
        projected_company = _pick(
            company,
            ("company_id", "display_name", "legal_name"),
        )
        valuation_profile = company.get("valuation_profile")
        if isinstance(valuation_profile, Mapping):
            projected_profile = _pick(
                valuation_profile,
                ("primary_model",),
            )
            if projected_profile:
                projected_company["valuation_profile"] = projected_profile
        if projected_company:
            projected["company"] = projected_company

    primary_security = card.get("primary_security")
    if isinstance(primary_security, Mapping):
        projected_security = _pick(
            primary_security,
            ("ticker", "currency"),
        )
        if projected_security:
            projected["primary_security"] = projected_security

    market = card.get("market")
    if isinstance(market, Mapping):
        projected_market = _pick(
            market,
            ("current_price", "currency", "as_of_date"),
        )
        if projected_market:
            projected["market"] = projected_market

    financials = card.get("financials")
    if isinstance(financials, Mapping):
        projected["financials"] = {
            field: _publication_metric(financials[field])
            for field in PUBLICATION_FINANCIAL_FIELDS
            if field in financials
        }

    estimates = card.get("estimates")
    if isinstance(estimates, Mapping):
        projected["estimates"] = {
            field: _publication_metric(estimates[field])
            for field in PUBLICATION_ESTIMATE_FIELDS
            if field in estimates
        }

    horizons = card.get("valuation_horizons")
    if isinstance(horizons, Mapping):
        projected["valuation_horizons"] = {
            name: _publication_horizon(horizons[name])
            for name in ("CURRENT_FY", "NEXT_FY")
            if name in horizons
        }

    projected_valuation = _publication_valuation(card.get("valuation"))
    if projected_valuation:
        projected["valuation"] = projected_valuation

    return projected


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
    projection_aliases: dict[str, set[str]] = {}
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
        # Alias discovery belongs to the rich Full Market card. The compact
        # frontend projection intentionally does not publish ``securities``.
        projection_aliases[ticker] = _card_symbols(card)

        projections[ticker] = {
            "schema_version": "company-page-projection.v031f.2.2",
            "version": "V031F.2.2",
            "company_id": company_id,
            "ticker": ticker,
            "product_scope": decision.get("product_scope") or "basic_market",
            "research_scope": decision.get("research_scope") or "contextual",
            "scope_axes": scope_axes,
            "coverage_policy": {
                "reason_codes": list(decision.get("reason_codes") or []),
                "review_status": decision.get("review_status"),
            },
            "valuation_card": _publication_valuation_card(card),
        }

    records.sort(key=lambda row: str(row.get("ticker") or ""))
    index: dict[str, str] = {}
    for ticker in projections:
        filename = _filename(ticker)
        for alias in projection_aliases.get(ticker, set()):
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

    # Retain immutable shard history per company. Incremental publication of
    # one ticker must not age unrelated companies merely because a new
    # repository-wide release was created.
    retention_path = output.parent / PUBLICATION_SHARD_RETENTION_FILE
    histories: dict[str, list[str]] = {}

    if retention_path.is_file():
        retention = _load(retention_path)
        stored_histories = retention.get("company_generations") or {}
        if isinstance(stored_histories, Mapping):
            histories = {
                str(ticker): [
                    str(filename)
                    for filename in filenames
                    if str(filename)
                ][:retention_generations]
                for ticker, filenames in stored_histories.items()
                if isinstance(filenames, list)
            }

    # Migration from the old release-wide retention format. Reconstruct
    # per-company histories from the legacy generations without advancing
    # untouched companies or discarding their previous immutable shards.
    if not histories and previous_manifest:
        legacy_generations = (
            retention.get("generations") or []
            if retention_path.is_file()
            else []
        )

        legacy_files = [
            str(filename)
            for generation in legacy_generations
            if isinstance(generation, Mapping)
            for filename in (generation.get("files") or [])
        ]

        for ticker, row in (previous_manifest.get("companies") or {}).items():
            if not isinstance(row, Mapping):
                continue

            path = Path(str(row.get("path") or ""))
            if path.parent != Path("companies") or not path.name.endswith(".json"):
                continue

            current_name = path.name

            # Hashed shard names have the form <stable-prefix>.<hash>.json.
            # Derive the prefix from the manifest's known current shard rather
            # than from the ticker, so aliases and encoded ticker names do not
            # need separate parsing rules.
            parts = current_name.rsplit(".", 2)
            shard_prefix = parts[0] if len(parts) == 3 else None

            history = []
            for filename in legacy_files:
                candidate = Path(filename).name
                candidate_parts = candidate.rsplit(".", 2)
                candidate_prefix = (
                    candidate_parts[0]
                    if len(candidate_parts) == 3
                    else None
                )

                if (
                    candidate == current_name
                    or (
                        shard_prefix is not None
                        and candidate_prefix == shard_prefix
                    )
                ):
                    if candidate not in history:
                        history.append(candidate)

                if len(history) >= retention_generations:
                    break

            if current_name in history:
                history.remove(current_name)
            history.insert(0, current_name)

            histories[str(ticker)] = history[:retention_generations]

    # A full publication defines the complete current company set. Incremental
    # publication mutates only companies present in this report.
    if not incremental:
        histories = {
            ticker: histories.get(ticker, [])
            for ticker in company_entries
        }

    for ticker in projections:
        row = company_entries.get(str(ticker)) or {}
        path = Path(str(row.get("path") or ""))
        if path.parent != Path("companies") or not path.name.endswith(".json"):
            continue

        history = histories.get(str(ticker), [])
        history = [
            filename
            for filename in history
            if filename != path.name
        ]
        histories[str(ticker)] = (
            [path.name] + history
        )[:retention_generations]

    # Ensure every active manifest shard is protected, including companies
    # untouched by this incremental publication.
    for ticker, row in company_entries.items():
        path = Path(str(row.get("path") or ""))
        if path.parent != Path("companies") or not path.name.endswith(".json"):
            continue
        history = histories.get(str(ticker), [])
        if path.name not in history:
            history.insert(0, path.name)
        histories[str(ticker)] = history[:retention_generations]

    retained_files = {
        filename
        for filenames in histories.values()
        for filename in filenames
    }

    retention_payload = {
        "schema_version": "publication-shard-retention.v2",
        "retention_generations": retention_generations,
        "company_generations": dict(sorted(histories.items())),
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