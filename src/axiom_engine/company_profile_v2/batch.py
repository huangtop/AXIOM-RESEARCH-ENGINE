from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

from .core import build_company_profile_v2
from .display_zh_tw import build_company_profile_display_zh_tw
from .enrichment import enrich_company_profile_display


class CompanyProfileBatchError(RuntimeError):
    pass


CANONICAL_OUTPUT = Path("data/generated/company_profile_v2")
DISPLAY_OUTPUT = Path("data/generated/company_profile_display_zh_tw")
LEGACY_PUBLISHED_INDEX = Path("data/generated/company_analysis/index.json")
BUSINESS_EVIDENCE_INDEX = Path(
    "data/generated/canonical_business_evidence/index.json"
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyProfileBatchError(
            f"cannot read {path}: {exc}"
        ) from exc


def _write_json(
    path: Path,
    payload: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary,
        path,
    )


def _filename(
    company_id: str,
) -> str:
    return (
        quote(
            company_id,
            safe="",
        )
        + ".json"
    )


def _primary_symbol_by_company(
    root: Path,
) -> dict[str, str]:
    securities = _load_json(
        root / "data/universe/securities.json"
    )

    output: dict[str, str] = {}

    for row in securities:
        company_id = str(
            row.get("company_id")
            or ""
        )

        symbol = str(
            row.get("ticker")
            or ""
        ).strip().upper()

        if not company_id or not symbol:
            continue

        if (
            row.get("primary_listing") is True
            or company_id not in output
        ):
            output[company_id] = symbol

    return output


def _published_symbols(
    root: Path,
) -> list[str]:
    payload = _load_json(
        root
        / LEGACY_PUBLISHED_INDEX
    )

    symbols = (
        payload.get("symbol_to_file")
        or {}
    )

    if not isinstance(symbols, dict):
        raise CompanyProfileBatchError(
            "legacy company_analysis index "
            "has no symbol_to_file mapping"
        )

    return sorted(
        str(symbol).upper()
        for symbol in symbols
        if str(symbol).strip()
    )


def _evidence_symbols(
    root: Path,
) -> list[str]:
    index = _load_json(
        root
        / BUSINESS_EVIDENCE_INDEX
    )

    company_ids = set(
        str(value)
        for value in (
            index.get(
                "company_id_to_file"
            )
            or {}
        )
        if str(value)
    )

    primary = (
        _primary_symbol_by_company(
            root
        )
    )

    return sorted(
        primary[company_id]
        for company_id in company_ids
        if company_id in primary
    )


def resolve_batch_symbols(
    root: Path,
    *,
    scope: str = "published",
    symbols: Iterable[str] | None = None,
) -> list[str]:
    explicit = sorted(
        {
            str(symbol).strip().upper()
            for symbol in (
                symbols
                or []
            )
            if str(symbol).strip()
        }
    )

    if explicit:
        return explicit

    if scope == "published":
        return _published_symbols(root)

    if scope == "evidence":
        return _evidence_symbols(root)

    raise CompanyProfileBatchError(
        f"unsupported batch scope: {scope}"
    )


def _has_text(
    value: Any,
) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
    )


def _profile_coverage(
    profile: Mapping[str, Any],
) -> dict[str, bool]:
    summary = (
        profile.get(
            "company_summary"
        )
        or {}
    )

    financial = (
        profile.get(
            "financial_snapshot"
        )
        or {}
    )

    manufacturing = (
        profile.get(
            "manufacturing"
        )
        or {}
    )

    return {
        "company_summary":
            _has_text(
                summary.get(
                    "one_line_business"
                )
            ),

        "markets":
            bool(
                profile.get(
                    "markets"
                )
            ),

        "product_stack":
            bool(
                profile.get(
                    "product_stack"
                )
            ),

        "market_products":
            bool(
                profile.get(
                    "market_products"
                )
            ),

        "core_technologies":
            bool(
                profile.get(
                    "core_technologies"
                )
            ),

        "manufacturing":
            bool(
                manufacturing.get(
                    "model"
                )
                or manufacturing.get(
                    "locations"
                )
                or manufacturing.get(
                    "critical_assets"
                )
            ),

        "customer_types":
            bool(
                profile.get(
                    "customer_types"
                )
            ),

        "ai_exposure":
            bool(
                profile.get(
                    "ai_exposure"
                )
            ),

        "competitive_advantages":
            bool(
                profile.get(
                    "competitive_advantages"
                )
            ),

        "demand_drivers":
            bool(
                profile.get(
                    "demand_drivers"
                )
            ),

        "strategy_changes":
            bool(
                profile.get(
                    "strategy_changes"
                )
            ),

        "financial_snapshot":
            any(
                financial.get(key)
                is not None
                for key in (
                    "revenue",
                    "gross_margin",
                    "net_loss",
                )
            ),

        "value_provenance":
            bool(
                profile.get(
                    "value_provenance"
                )
            ),

        "evidence":
            bool(
                profile.get(
                    "evidence"
                )
            ),
    }


def _production_ready(
    profile: Mapping[str, Any],
    display: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    coverage = _profile_coverage(profile)
    reasons = []

    if not coverage["company_summary"]:
        reasons.append("missing_company_summary")
    if not coverage["evidence"]:
        reasons.append("missing_business_evidence")
    if not coverage["value_provenance"]:
        reasons.append("missing_value_provenance")

    if any(key in profile for key in ("classification", "theme", "sector")):
        reasons.append("ontology_leaked_into_profile")

    display_payload = display.get("display") or {}
    if display_payload.get("locale") != "zh-TW":
        reasons.append("missing_zh_tw_display")
    if not display_payload.get("offerings"):
        reasons.append("missing_frontend_offerings")
    if not display_payload.get("markets"):
        reasons.append("missing_frontend_markets")

    return not reasons, reasons


def _coverage_summary(
    records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    fields = [
        "company_summary",
        "markets",
        "product_stack",
        "market_products",
        "core_technologies",
        "manufacturing",
        "customer_types",
        "ai_exposure",
        "competitive_advantages",
        "demand_drivers",
        "strategy_changes",
        "financial_snapshot",
        "value_provenance",
        "evidence",
        "frontend_offerings",
        "frontend_markets",
    ]

    count = len(records)

    coverage: dict[str, Any] = {}

    for field in fields:
        covered = sum(
            bool(
                (
                    row.get(
                        "coverage"
                    )
                    or {}
                ).get(field)
            )
            for row in records
        )

        coverage[field] = {
            "covered_company_count":
                covered,
            "total_company_count":
                count,
            "coverage":
                (
                    covered / count
                    if count
                    else 0.0
                ),
        }

    return coverage


def build_company_profile_batch(
    root: Path,
    *,
    scope: str = "published",
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    targets = resolve_batch_symbols(
        root,
        scope=scope,
        symbols=symbols,
    )

    records = []
    failures = []
    canonical_profiles = []
    display_profiles = []

    for symbol in targets:
        try:
            profile = (
                build_company_profile_v2(
                    root,
                    symbol=symbol,
                )
            )

            display = (
                build_company_profile_display_zh_tw(
                    root,
                    profile=profile,
                )
            )

            display = enrich_company_profile_display(
                root,
                profile=profile,
                display_payload=display,
            )
        except Exception as exc:
            failures.append(
                {
                    "symbol":
                        symbol,
                    "error_type":
                        type(exc).__name__,
                    "error":
                        str(exc),
                }
            )
            continue

        ready, reasons = (
            _production_ready(
                profile,
                display,
            )
        )

        coverage = _profile_coverage(profile)
        display_payload = display.get("display") or {}
        coverage["frontend_offerings"] = bool(
            display_payload.get("offerings")
        )
        coverage["frontend_markets"] = bool(
            display_payload.get("markets")
        )

        records.append(
            {
                "symbol":
                    symbol,
                "company_id":
                    profile.get(
                        "company_id"
                    ),
                "canonical_schema_version":
                    profile.get(
                        "schema_version"
                    ),
                "display_schema_version":
                    display.get(
                        "schema_version"
                    ),
                "production_ready":
                    ready,
                "readiness_reasons":
                    reasons,
                "coverage":
                    coverage,
            }
        )

        canonical_profiles.append(
            profile
        )

        display_profiles.append(
            display
        )

    ready_count = sum(
        bool(
            row.get(
                "production_ready"
            )
        )
        for row in records
    )

    return {
        "schema_version":
            "axiom-company-profile-batch.v2.5",

        "generation_mode":
            "generic_evidence_batch",

        "scope":
            scope,

        "target_symbols":
            targets,

        "summary": {
            "target_company_count":
                len(targets),
            "generated_company_count":
                len(records),
            "failed_company_count":
                len(failures),
            "production_ready_count":
                ready_count,
            "complete":
                (
                    len(records)
                    == len(targets)
                    and not failures
                    and ready_count
                    == len(targets)
                ),
        },

        "coverage":
            _coverage_summary(
                records
            ),

        "records":
            records,

        "failures":
            failures,

        # Internal write payloads. The CLI removes
        # these from the printed report.
        "_canonical_profiles":
            canonical_profiles,
        "_display_profiles":
            display_profiles,
    }


def _index_for_profiles(
    profiles: list[Mapping[str, Any]],
    *,
    schema_version: str,
) -> dict[str, Any]:
    symbol_to_file = {}
    company_id_to_file = {}

    for profile in profiles:
        company_id = str(
            profile["company_id"]
        )

        symbol = str(
            profile["symbol"]
        ).upper()

        relative = str(
            Path(
                "per-company"
            )
            / _filename(
                company_id
            )
        )

        symbol_to_file[
            symbol
        ] = relative

        company_id_to_file[
            company_id
        ] = relative

    return {
        "schema_version":
            schema_version,
        "symbol_to_file":
            dict(
                sorted(
                    symbol_to_file.items()
                )
            ),
        "company_id_to_file":
            dict(
                sorted(
                    company_id_to_file.items()
                )
            ),
        "symbols":
            sorted(
                symbol_to_file
            ),
        "company_count":
            len(
                company_id_to_file
            ),
    }


def _prune_per_company(
    root: Path,
    *,
    expected: set[str],
) -> None:
    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path in root.glob(
        "*.json"
    ):
        if path.name not in expected:
            path.unlink()


def write_company_profile_batch(
    root: Path,
    report: Mapping[str, Any],
    *,
    allow_partial: bool = False,
) -> dict[str, Any]:
    summary = (
        report.get("summary")
        or {}
    )

    if (
        not allow_partial
        and not summary.get(
            "complete"
        )
    ):
        raise CompanyProfileBatchError(
            "batch is incomplete; production outputs "
            "were not modified"
        )

    canonical_profiles = list(
        report.get(
            "_canonical_profiles"
        )
        or []
    )

    display_profiles = list(
        report.get(
            "_display_profiles"
        )
        or []
    )

    canonical_output = (
        root
        / CANONICAL_OUTPUT
    )

    display_output = (
        root
        / DISPLAY_OUTPUT
    )

    expected_canonical = {
        _filename(
            str(
                row["company_id"]
            )
        )
        for row in canonical_profiles
    }

    expected_display = {
        _filename(
            str(
                row["company_id"]
            )
        )
        for row in display_profiles
    }

    _prune_per_company(
        canonical_output
        / "per-company",
        expected=expected_canonical,
    )

    _prune_per_company(
        display_output
        / "per-company",
        expected=expected_display,
    )

    for profile in canonical_profiles:
        _write_json(
            canonical_output
            / "per-company"
            / _filename(
                str(
                    profile[
                        "company_id"
                    ]
                )
            ),
            profile,
        )

    for display in display_profiles:
        _write_json(
            display_output
            / "per-company"
            / _filename(
                str(
                    display[
                        "company_id"
                    ]
                )
            ),
            display,
        )

    canonical_index = (
        _index_for_profiles(
            canonical_profiles,
            schema_version=(
                "axiom-company-profile-index.v2.5"
            ),
        )
    )

    display_index = (
        _index_for_profiles(
            display_profiles,
            schema_version=(
                "axiom-company-profile-display-index."
                "zh-tw.v2.5"
            ),
        )
    )

    _write_json(
        canonical_output
        / "index.json",
        canonical_index,
    )

    _write_json(
        display_output
        / "index.json",
        display_index,
    )

    public_report = {
        key: value
        for key, value
        in report.items()
        if not str(key).startswith(
            "_"
        )
    }

    _write_json(
        canonical_output
        / "production_readiness.json",
        public_report,
    )

    migration = {
        "schema_version":
            "axiom-company-profile-migration.v2.5",

        "source":
            str(
                LEGACY_PUBLISHED_INDEX
            ),

        "target_canonical_index":
            str(
                CANONICAL_OUTPUT
                / "index.json"
            ),

        "target_zh_tw_index":
            str(
                DISPLAY_OUTPUT
                / "index.json"
            ),

        "symbols":
            canonical_index[
                "symbols"
            ],

        "company_count":
            canonical_index[
                "company_count"
            ],

        "complete":
            bool(
                summary.get(
                    "complete"
                )
            ),
    }

    _write_json(
        canonical_output
        / "migration_manifest.json",
        migration,
    )

    return {
        "canonical_index":
            str(
                CANONICAL_OUTPUT
                / "index.json"
            ),
        "display_index":
            str(
                DISPLAY_OUTPUT
                / "index.json"
            ),
        "readiness_report":
            str(
                CANONICAL_OUTPUT
                / "production_readiness.json"
            ),
        "migration_manifest":
            str(
                CANONICAL_OUTPUT
                / "migration_manifest.json"
            ),
        "company_count":
            canonical_index[
                "company_count"
            ],
    }