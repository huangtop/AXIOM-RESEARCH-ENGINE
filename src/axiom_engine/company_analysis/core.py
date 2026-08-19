from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.business_evidence_store import load_business_evidence
from axiom_engine.company_analysis.profile_v2 import build_company_profile_v2


class CompanyAnalysisError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyAnalysisError(f"cannot read {path}: {exc}") from exc


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _join_zh(values: list[str]) -> str:
    values = list(dict.fromkeys(value for value in values if value))
    if len(values) < 2:
        return values[0] if values else ""
    return "、".join(values[:-1]) + "與" + values[-1]


def _source_ids(signals: list[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            str(value)
            for signal in signals
            for value in signal.get("source_business_evidence_ids") or []
        }
    )


def _claim(
    text: str,
    signals: list[Mapping[str, Any]],
    derivation: str,
) -> dict[str, Any]:
    return {
        "text": text,
        "evidence_ids": _source_ids(signals),
        "signal_ids": sorted(
            str(signal["signal_id"])
            for signal in signals
        ),
        "derivation": derivation,
    }


def _has_reviewed_classification_authority(
    overview: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    symbol: str,
    legacy_published_symbols: set[str],
) -> bool:
    """
    Consumer-side compatibility gate for published thematic classifications.

    Historical production overviews can be fully locked and evidence-backed
    while lacking the explicit ``classification_source`` field because an
    earlier full-market rebuild rewrote the artifact before restoring the
    source marker.  Those artifacts are still valid publication state when
    all of the following remain true:

      * status == classified
      * classification_lock is locked/manual_override_only
      * both theme and sector are present
      * classification evidence is present

    Explicit classification_source, when present, still has to be one of the
    policy-approved reviewed sources.  This keeps the gate generic and avoids
    ticker/company-specific exceptions.
    """
    scope = policy["scope"]
    lock = overview.get("classification_lock") or {}

    if scope.get("require_classification_lock") and (
        lock.get("status") != "locked"
        or lock.get("update_mode") != "manual_override_only"
    ):
        return False

    source = str(
        overview.get("classification_source") or ""
    ).strip()

    allowed_sources = {
        str(value)
        for value in scope.get(
            "allowed_classification_sources"
        )
        or []
    }

    if source:
        return source in allowed_sources

    path = overview.get("path") or {}
    theme = (
        path.get("theme")
        if isinstance(path, Mapping)
        else None
    )
    sector = (
        path.get("sector")
        if isinstance(path, Mapping)
        else None
    )
    evidence = overview.get("evidence") or []

    # Missing explicit source is accepted only for a company that was
    # already present in the previously published company-analysis index.
    # That index is publication state, not company-specific policy: it lets
    # a legacy reviewed artifact survive schema migration while preventing
    # a newly encountered lock (for example an unreviewed thematic path)
    # from being promoted merely because it has evidence and a lock.
    return (
        symbol in legacy_published_symbols
        and overview.get("status") == "classified"
        and isinstance(theme, Mapping)
        and bool(theme)
        and isinstance(sector, Mapping)
        and bool(sector)
        and bool(evidence)
    )


def build_company_analyses(
    root: Path,
    *,
    company_ids: set[str] | None = None,
    signals_payload: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    policy = _load(
        root / "config/company_analysis.v1.json"
    )

    if (
        policy.get("schema_version")
        != "company-analysis-policy.v1"
    ):
        raise CompanyAnalysisError(
            "unsupported company analysis policy"
        )

    forbidden = {
        "ticker",
        "tickers",
        "company_id",
        "company_ids",
        "symbols",
    }

    if any(
        forbidden.intersection(value)
        for value in policy.values()
        if isinstance(value, dict)
    ):
        raise CompanyAnalysisError(
            "company-specific membership is forbidden in analysis policy"
        )

    eligibility = _load(
        root
        / "data/generated/research_eligibility/"
        "research_eligibility.json"
    )

    allowed_themes = set(
        policy["scope"]["allowed_theme_ids"]
    )

    scoped_company_ids = {
        str(row["company_id"])
        for row in eligibility.get("records") or []
        if (
            (
                (row.get("decisions") or {})
                .get("supply_chain")
                or {}
            ).get("enabled")
            is True
        )
        and allowed_themes.intersection(
            row.get("matched_catalog_theme_ids")
            or []
        )
    }

    companies = {
        str(row["company_id"]): row
        for row in _load(
            root / "data/universe/companies.json"
        )
    }

    securities = _load(
        root / "data/universe/securities.json"
    )

    security_by_company: dict[
        str,
        dict[str, str],
    ] = {}

    for row in securities:
        company_id = str(
            row.get("company_id") or ""
        )
        symbol = str(
            row.get("ticker") or ""
        ).upper()

        if company_id and symbol and (
            row.get("primary_listing") is True
            or company_id not in security_by_company
        ):
            security_by_company[company_id] = {
                "symbol": symbol,
                "exchange": str(
                    row.get("exchange") or ""
                ).upper(),
            }

    signals_report = (
        signals_payload
        or _load(
            root
            / "data/generated/company_signals/"
            "company_signals.json"
        )
    )

    signal_by_company = {
        str(row["company_id"]): row
        for row in signals_report.get("records")
        or []
    }

    evidence = load_business_evidence(
        root
        / "data/generated/canonical_business_evidence"
    )

    evidence_by_id = {
        str(row["business_evidence_id"]): row
        for row in evidence
    }

    overview_dir = (
        root
        / "data/generated/company_overview/"
        "per-company"
    )

    overview_by_company = {}

    for path in overview_dir.glob("*.json"):
        overview = _load(path)
        if overview.get("company_id"):
            overview_by_company[
                str(overview["company_id"])
            ] = overview

    legacy_analysis_index_path = (
        root
        / "data/generated/company_analysis/index.json"
    )
    legacy_published_symbols: set[str] = set()

    if legacy_analysis_index_path.is_file():
        legacy_analysis_index = _load(
            legacy_analysis_index_path
        )
        legacy_published_symbols = {
            str(symbol).upper()
            for symbol in (
                legacy_analysis_index.get(
                    "symbol_to_file"
                )
                or {}
            )
        }

    labels = policy["display_names_zh_tw"]
    kinds = policy["kind_by_dimension"]
    records = []

    for company_id, source in sorted(
        signal_by_company.items()
    ):
        if company_id not in scoped_company_ids:
            continue

        if (
            company_ids is not None
            and company_id not in company_ids
        ):
            continue

        overview = overview_by_company.get(
            company_id
        )
        security = (
            security_by_company.get(company_id)
            or {}
        )
        symbol = security.get("symbol")

        if (
            not overview
            or not symbol
            or source.get("status")
            != "signals_available"
        ):
            continue

        if not _has_reviewed_classification_authority(
            overview,
            policy,
            symbol=str(symbol),
            legacy_published_symbols=legacy_published_symbols,
        ):
            continue

        classification_evidence_ids = {
            str(row.get("business_evidence_id"))
            for row in (
                overview.get("evidence")
                or []
            )
            if row.get("business_evidence_id")
        }

        if not classification_evidence_ids:
            continue

        signals = list(
            source.get("signals") or []
        )

        primary_products = [
            signal
            for signal in signals
            if signal.get("dimension")
            in {
                "product",
                "capability",
                "infrastructure",
            }
            and int(
                signal.get(
                    "primary_business_score"
                )
                or 0
            )
            >= 3
        ]

        supporting = [
            signal
            for signal in signals
            if signal.get("dimension")
            in {
                "capability",
                "infrastructure",
            }
            and int(
                signal.get(
                    "primary_business_score"
                )
                or 0
            )
            >= 3
        ]

        offering_candidates = {
            str(signal["signal_id"]): signal
            for signal in [
                *primary_products,
                *supporting,
            ]
        }

        offering_signals = sorted(
            offering_candidates.values(),
            key=lambda row: (
                -int(
                    row.get(
                        "primary_business_score"
                    )
                    or 0
                ),
                -int(
                    row.get(
                        "offering_occurrence_count"
                    )
                    or 0
                ),
                -float(
                    row.get("confidence") or 0
                ),
                str(row["signal_id"]),
            ),
        )[
            : int(policy["maximum_offerings"])
        ]

        # A company analysis without a verified
        # offering would be technology-keyword
        # prose, not a description of what the
        # company sells.
        if not primary_products:
            continue

        end_markets = sorted(
            [
                signal
                for signal in signals
                if signal.get("dimension")
                == "end_market"
                and int(
                    signal.get(
                        "occurrence_count"
                    )
                    or 0
                )
                >= int(
                    policy[
                        "minimum_end_market_occurrences"
                    ]
                )
            ],
            key=lambda row: (
                -int(
                    row.get(
                        "occurrence_count"
                    )
                    or 0
                ),
                str(row["signal_id"]),
            ),
        )[
            : int(policy["maximum_end_markets"])
        ]

        roles = sorted(
            [
                signal
                for signal in signals
                if signal.get("dimension")
                == "supply_chain_role"
                and int(
                    signal.get(
                        "primary_business_score"
                    )
                    or 0
                )
                >= 3
            ],
            key=lambda row: (
                -int(
                    row.get(
                        "occurrence_count"
                    )
                    or 0
                ),
                str(row["signal_id"]),
            ),
        )[:2]

        upstream_inputs = sorted(
            [
                signal
                for signal in signals
                if signal.get("dimension")
                == "upstream_input"
            ],
            key=lambda row: (
                -int(
                    row.get(
                        "occurrence_count"
                    )
                    or 0
                ),
                str(row["signal_id"]),
            ),
        )[
            : int(policy["maximum_offerings"])
        ]

        offering_names = [
            labels.get(
                str(row["signal_id"]),
                str(
                    row.get(
                        "canonical_name"
                    )
                    or ""
                ),
            )
            for row in offering_signals
        ]

        market_names = [
            labels.get(
                str(row["signal_id"]),
                str(
                    row.get(
                        "canonical_name"
                    )
                    or ""
                ),
            )
            for row in end_markets
        ]

        role_names = [
            labels.get(
                str(row["signal_id"]),
                str(
                    row.get(
                        "canonical_name"
                    )
                    or ""
                ),
            )
            for row in roles
        ]

        upstream_names = [
            labels.get(
                str(row["signal_id"]),
                str(
                    row.get(
                        "canonical_name"
                    )
                    or ""
                ),
            )
            for row in upstream_inputs
        ]

        company = companies.get(
            company_id
        ) or {}

        display_name = str(
            company.get("display_name")
            or company.get("legal_name")
            or symbol
        )

        display_name = re.sub(
            r"\s+(?:Common Stock|- Ordinary Shares?)$",
            "",
            display_name,
            flags=re.IGNORECASE,
        ).strip()

        sector = (
            (
                (
                    overview.get("path")
                    or {}
                ).get("sector")
                or {}
            ).get("display_name_zh_tw")
            or "未分類產業"
        )

        theme = (
            (
                (
                    overview.get("path")
                    or {}
                ).get("theme")
                or {}
            ).get("display_name_zh_tw")
            or "未分類主題"
        )

        used_signals = list(
            {
                str(row["signal_id"]): row
                for row in [
                    *offering_signals,
                    *end_markets,
                    *roles,
                    *upstream_inputs,
                ]
            }.values()
        )

        evidence_ids = _source_ids(
            used_signals
        )

        # A lock alone is not evidence
        # confirmation.  The reviewed
        # classification and generated prose
        # must share a source filing.
        if not classification_evidence_ids.intersection(
            evidence_ids
        ):
            continue

        evidence_rows = []

        for evidence_id in evidence_ids:
            row = evidence_by_id.get(
                evidence_id,
                {},
            )

            evidence_rows.append(
                {
                    "evidence_id": evidence_id,
                    "source_type": "sec_filing",
                    "form": row.get("form"),
                    "filing_date": row.get(
                        "filing_date"
                    ),
                    "section": (
                        "Item 1. Business"
                        if str(
                            row.get("form")
                            or ""
                        ).startswith("10-K")
                        else (
                            "Item 4. Information "
                            "on the Company"
                        )
                    ),
                }
            )

        latest_date = max(
            (
                str(
                    row.get(
                        "filing_date"
                    )
                    or ""
                )
                for row in evidence_rows
            ),
            default="",
        )

        records.append(
            {
                "schema_version": (
                    "axiom-company-analysis.v1"
                ),
                "generation_mode": (
                    "deterministic_evidence_template"
                ),
                "company_id": company_id,
                "symbol": symbol,
                "company_profile_v2": (
                    build_company_profile_v2(
                        company_id,
                        evidence,
                    )
                ),
                "exchange": security.get(
                    "exchange"
                ),
                "display_name": display_name,
                "as_of": latest_date,
                "classification": {
                    "theme": theme,
                    "sector": sector,
                    "supply_chain_role": (
                        _join_zh(role_names)
                        or "待更多證據確認"
                    ),
                },
                "business_model": {
                    "operating_capabilities": [
                        _claim(
                            name,
                            [signal],
                            "evidence_signal",
                        )
                        for name, signal in zip(
                            [
                                *role_names,
                                *[
                                    name
                                    for name, signal
                                    in zip(
                                        offering_names,
                                        offering_signals,
                                    )
                                    if signal.get(
                                        "dimension"
                                    )
                                    == "capability"
                                ],
                            ],
                            [
                                *roles,
                                *[
                                    signal
                                    for signal
                                    in offering_signals
                                    if signal.get(
                                        "dimension"
                                    )
                                    == "capability"
                                ],
                            ],
                        )
                    ],
                },
                "offerings": [
                    {
                        "name": name,
                        "kind": kinds.get(
                            str(
                                signal.get(
                                    "dimension"
                                )
                            ),
                            "offering",
                        ),
                        "evidence_ids": (
                            _source_ids(
                                [signal]
                            )
                        ),
                        "signal_ids": [
                            str(
                                signal[
                                    "signal_id"
                                ]
                            )
                        ],
                    }
                    for name, signal in zip(
                        offering_names,
                        offering_signals,
                    )
                    if signal.get(
                        "dimension"
                    )
                    != "capability"
                ],
                "value_chain": {
                    "upstream": [
                        _claim(
                            name,
                            [signal],
                            "evidence_signal",
                        )
                        for name, signal in zip(
                            upstream_names,
                            upstream_inputs,
                        )
                    ],
                    "core": [
                        _claim(
                            name,
                            [signal],
                            "evidence_signal",
                        )
                        for name, signal in zip(
                            [
                                *role_names,
                                *[
                                    name
                                    for name, signal
                                    in zip(
                                        offering_names,
                                        offering_signals,
                                    )
                                    if signal.get(
                                        "value_chain_stage"
                                    )
                                    != (
                                        "infrastructure_delivery"
                                    )
                                ],
                            ],
                            [
                                *roles,
                                *[
                                    signal
                                    for signal
                                    in offering_signals
                                    if signal.get(
                                        "value_chain_stage"
                                    )
                                    != (
                                        "infrastructure_delivery"
                                    )
                                ],
                            ],
                        )
                    ],
                    "infrastructure_delivery": [
                        _claim(
                            name,
                            [signal],
                            "evidence_signal",
                        )
                        for name, signal in zip(
                            offering_names,
                            offering_signals,
                        )
                        if signal.get(
                            "value_chain_stage"
                        )
                        == (
                            "infrastructure_delivery"
                        )
                    ],
                    "downstream": [
                        _claim(
                            name,
                            [signal],
                            "evidence_signal",
                        )
                        for name, signal in zip(
                            market_names,
                            end_markets,
                        )
                    ],
                },
                "evidence": evidence_rows,
            }
        )

    return {
        "schema_version": (
            "axiom-company-analysis-index.v1"
        ),
        "generated_at": current.isoformat(),
        "summary": {
            "company_count": len(records)
        },
        "scope": {
            "source": (
                "research_eligibility.decisions."
                "supply_chain.enabled"
            ),
            "eligible_company_count": len(
                scoped_company_ids
            ),
            "allowed_theme_ids": sorted(
                allowed_themes
            ),
            "contains_company_membership": False,
            "required_classification_lock": True,
            "classification_authority": (
                "reviewed_source_or_legacy_"
                "published_locked_evidence_backed_path"
            ),
            "allowed_classification_sources": (
                sorted(
                    policy["scope"][
                        "allowed_classification_sources"
                    ]
                )
            ),
        },
        "records": records,
    }


def write_company_analyses(
    report: Mapping[str, Any],
    output: Path,
) -> None:
    files = {}

    for row in report.get("records") or []:
        filename = f"{row['symbol']}.json"
        files[str(row["symbol"])] = filename
        _write(
            output / "per-company" / filename,
            row,
        )

    _write(
        output / "index.json",
        {
            "schema_version": report[
                "schema_version"
            ],
            "generated_at": report[
                "generated_at"
            ],
            "summary": report["summary"],
            "symbol_to_file": files,
        },
    )