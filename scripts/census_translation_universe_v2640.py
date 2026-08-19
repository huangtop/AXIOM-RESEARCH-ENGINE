#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_OVERVIEW_ROOT = Path(
    "data/generated/company_overview"
)

DEFAULT_PROFILE_CENSUS = Path(
    "data/generated/company_profile_v2/full_market_census.json"
)

DEFAULT_OUTPUT = Path(
    "data/generated/company_profile_v2/"
    "translation_universe_census_v2640.json"
)

# V2.6.4.0 translation universe:
# prioritize technology / growth / strategic-industry themes.
# Traditional banking / insurance / generic finance / non-priority
# legacy sectors are intentionally not auto-selected for localization.
PRIORITY_TRANSLATION_THEME_IDS = {
    "theme:ai_infrastructure",
    "theme:artificial_intelligence",
    "theme:advanced_semiconductors",
    "theme:advanced_communications",
    "theme:advanced_manufacturing",
    "theme:robotics",
    "theme:autonomous_vehicles",
    "theme:quantum_computing",
    "theme:space_economy",
    "theme:clean_energy",
    "theme:health_technology",
    "theme:consumer_technology",
    "theme:enterprise_software",
    "theme:digital_assets",
    "theme:physical_ai",
}

# These are not necessarily wrong. They are merely not an automatic
# localization priority under the current site strategy.
NON_PRIORITY_TRANSLATION_THEME_IDS = {
    "theme:financial_services_technology",
    "theme:travel_leisure",
    "theme:industrial_logistics",
    "theme:education_technology",
    "theme:digital_media_technology",
    "theme:commerce_technology",
}

# Historical auto-published classifications with these low-confidence
# sector outcomes deserve inspection before they become a translation gate.
SUSPECT_SECTOR_IDS = {
    "sector:cloud_infrastructure",
}

CURATED_SOURCE = "curated_core_override"
LOCKED_SOURCE = "locked_published_classification"


def _load(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _overview_rows(
    root: Path,
) -> list[dict[str, Any]]:
    index_path = (
        root
        / DEFAULT_OVERVIEW_ROOT
        / "index.json"
    )

    index = _load(index_path)

    ticker_to_file = (
        index.get("ticker_to_file")
        or {}
    )

    # A single per-company file may have several ticker aliases.
    filenames = sorted(
        set(
            str(value)
            for value in ticker_to_file.values()
            if value
        )
    )

    rows: list[dict[str, Any]] = []

    for filename in filenames:
        path = (
            root
            / DEFAULT_OVERVIEW_ROOT
            / "per-company"
            / filename
        )

        if not path.exists():
            continue

        payload = _load(path)

        if isinstance(payload, dict):
            rows.append(payload)

    rows.sort(
        key=lambda row: str(
            row.get("ticker")
            or row.get("company_id")
            or ""
        )
    )

    return rows


def _profile_ready_symbols(
    root: Path,
    census_path: Path,
) -> set[str]:
    path = (
        census_path
        if census_path.is_absolute()
        else root / census_path
    )

    if not path.exists():
        return set()

    payload = _load(path)

    ready: set[str] = set()

    for row in (
        payload.get("records")
        or payload.get("companies")
        or []
    ):
        symbol = str(
            row.get("symbol")
            or row.get("ticker")
            or ""
        ).strip().upper()

        if not symbol:
            continue

        direct = row.get(
            "production_ready"
        )

        if direct is True:
            ready.add(symbol)
            continue

        status = str(
            row.get("status")
            or row.get("readiness")
            or ""
        ).strip().lower()

        if status in {
            "production_ready",
            "ready",
            "published",
        }:
            ready.add(symbol)
            continue

        readiness = row.get(
            "production_readiness"
        )

        if isinstance(
            readiness,
            Mapping,
        ) and readiness.get(
            "production_ready"
        ) is True:
            ready.add(symbol)

    return ready


def _classify_quality(
    row: Mapping[str, Any],
) -> tuple[str, list[str]]:
    status = str(
        row.get("status")
        or ""
    )

    source = str(
        row.get(
            "classification_source"
        )
        or ""
    )

    path = (
        row.get("path")
        or {}
    )

    theme = (
        path.get("theme")
        or {}
    )

    sector = (
        path.get("sector")
        or {}
    )

    theme_id = str(
        theme.get("id")
        or ""
    )

    sector_id = str(
        sector.get("id")
        or ""
    )

    theme_conf = _safe_float(
        theme.get("confidence")
    )

    sector_conf = _safe_float(
        sector.get("confidence")
    )

    reasons: list[str] = []

    if status != "classified":
        reasons.append(
            "not_classified"
        )
        return (
            "REVIEW",
            reasons,
        )

    if source == CURATED_SOURCE:
        return (
            "HIGH",
            [
                "curated_override",
            ],
        )

    if source == LOCKED_SOURCE:
        reasons.append(
            "historical_locked_classification"
        )

    if (
        sector_conf is not None
        and sector_conf < 0.65
    ):
        reasons.append(
            "low_sector_confidence"
        )

    if (
        theme_conf is not None
        and theme_conf < 0.65
    ):
        reasons.append(
            "low_theme_confidence"
        )

    if (
        source == LOCKED_SOURCE
        and sector_id
        in SUSPECT_SECTOR_IDS
        and (
            sector_conf is None
            or sector_conf < 0.75
        )
    ):
        reasons.append(
            "possible_end_market_proxy"
        )

    if (
        theme_id
        in {
            "theme:artificial_intelligence",
            "theme:ai_infrastructure",
        }
        and source == LOCKED_SOURCE
        and sector_conf is not None
        and sector_conf < 0.60
    ):
        reasons.append(
            "weak_ai_sector_assignment"
        )

    if any(
        reason in reasons
        for reason in {
            "possible_end_market_proxy",
            "weak_ai_sector_assignment",
        }
    ):
        return (
            "SUSPECT",
            sorted(
                set(reasons)
            ),
        )

    if any(
        reason in reasons
        for reason in {
            "low_sector_confidence",
            "low_theme_confidence",
        }
    ):
        return (
            "REVIEW",
            sorted(
                set(reasons)
            ),
        )

    return (
        "HIGH",
        sorted(
            set(reasons)
        ),
    )


def _translation_bucket(
    row: Mapping[str, Any],
    *,
    profile_ready: bool,
    quality: str,
) -> str:
    if not profile_ready:
        return (
            "not_profile_ready"
        )

    if str(
        row.get("status")
        or ""
    ) != "classified":
        return (
            "classification_review"
        )

    if quality in {
        "SUSPECT",
        "REVIEW",
    }:
        return (
            "classification_review"
        )

    theme_id = str(
        (
            row.get("path")
            or {}
        ).get(
            "theme",
            {},
        ).get(
            "id"
        )
        or ""
    )

    if theme_id in (
        PRIORITY_TRANSLATION_THEME_IDS
    ):
        return (
            "translate_priority"
        )

    if theme_id in (
        NON_PRIORITY_TRANSLATION_THEME_IDS
    ):
        return (
            "skip_non_priority_theme"
        )

    return (
        "manual_theme_review"
    )


def _row_for_report(
    row: Mapping[str, Any],
    *,
    profile_ready: bool,
) -> dict[str, Any]:
    path = (
        row.get("path")
        or {}
    )

    theme = (
        path.get("theme")
        or {}
    )

    sector = (
        path.get("sector")
        or {}
    )

    quality, reasons = (
        _classify_quality(
            row
        )
    )

    bucket = (
        _translation_bucket(
            row,
            profile_ready=profile_ready,
            quality=quality,
        )
    )

    return {
        "ticker": str(
            row.get("ticker")
            or ""
        ).upper(),
        "company_id": row.get(
            "company_id"
        ),
        "display_name": row.get(
            "display_name"
        ),
        "classification_status": (
            row.get("status")
        ),
        "classification_source": (
            row.get(
                "classification_source"
            )
        ),
        "classification_locked": (
            (
                row.get(
                    "classification_lock"
                )
                or {}
            ).get(
                "status"
            )
            == "locked"
        ),
        "theme_id": theme.get(
            "id"
        ),
        "theme_name": theme.get(
            "name"
        ),
        "theme_zh_tw": theme.get(
            "display_name_zh_tw"
        ),
        "theme_confidence": (
            _safe_float(
                theme.get(
                    "confidence"
                )
            )
        ),
        "sector_id": sector.get(
            "id"
        ),
        "sector_name": sector.get(
            "name"
        ),
        "sector_zh_tw": sector.get(
            "display_name_zh_tw"
        ),
        "sector_confidence": (
            _safe_float(
                sector.get(
                    "confidence"
                )
            )
        ),
        "business_evidence_available": bool(
            row.get("evidence")
        ),
        "business_evidence_count": len(
            row.get("evidence")
            or []
        ),
        "profile_production_ready": (
            profile_ready
        ),
        "classification_quality": (
            quality
        ),
        "quality_reasons": reasons,
        "translation_bucket": bucket,
    }


def build_report(
    root: Path,
    *,
    census_path: Path = DEFAULT_PROFILE_CENSUS,
) -> dict[str, Any]:
    overviews = _overview_rows(
        root
    )

    ready_symbols = (
        _profile_ready_symbols(
            root,
            census_path,
        )
    )

    records = [
        _row_for_report(
            row,
            profile_ready=(
                str(
                    row.get("ticker")
                    or ""
                ).upper()
                in ready_symbols
            ),
        )
        for row in overviews
    ]

    theme_counts: dict[
        tuple[str, str],
        Counter[str],
    ] = defaultdict(
        Counter
    )

    sector_counts: dict[
        tuple[str, str],
        Counter[str],
    ] = defaultdict(
        Counter
    )

    source_counts: Counter[
        str
    ] = Counter()

    quality_counts: Counter[
        str
    ] = Counter()

    bucket_counts: Counter[
        str
    ] = Counter()

    for row in records:
        theme_key = (
            str(
                row.get("theme_id")
                or ""
            ),
            str(
                row.get("theme_zh_tw")
                or row.get("theme_name")
                or ""
            ),
        )

        sector_key = (
            str(
                row.get("sector_id")
                or ""
            ),
            str(
                row.get("sector_zh_tw")
                or row.get("sector_name")
                or ""
            ),
        )

        theme_counts[
            theme_key
        ][
            "all"
        ] += 1

        sector_counts[
            sector_key
        ][
            "all"
        ] += 1

        if row[
            "profile_production_ready"
        ]:
            theme_counts[
                theme_key
            ][
                "profile_ready"
            ] += 1

            sector_counts[
                sector_key
            ][
                "profile_ready"
            ] += 1

        if (
            row[
                "translation_bucket"
            ]
            == "translate_priority"
        ):
            theme_counts[
                theme_key
            ][
                "translation_priority"
            ] += 1

            sector_counts[
                sector_key
            ][
                "translation_priority"
            ] += 1

        source_counts[
            str(
                row.get(
                    "classification_source"
                )
                or "unclassified"
            )
        ] += 1

        quality_counts[
            row[
                "classification_quality"
            ]
        ] += 1

        bucket_counts[
            row[
                "translation_bucket"
            ]
        ] += 1

    def _family_rows(
        counts: Mapping[
            tuple[str, str],
            Counter[str],
        ],
        *,
        id_key: str,
        name_key: str,
    ) -> list[
        dict[str, Any]
    ]:
        result = []

        for (
            identifier,
            name,
        ), counter in counts.items():
            if not identifier:
                continue

            result.append(
                {
                    id_key: identifier,
                    name_key: name,
                    "all_company_count": (
                        counter[
                            "all"
                        ]
                    ),
                    "profile_ready_count": (
                        counter[
                            "profile_ready"
                        ]
                    ),
                    "translation_priority_count": (
                        counter[
                            "translation_priority"
                        ]
                    ),
                }
            )

        result.sort(
            key=lambda item: (
                -int(
                    item[
                        "translation_priority_count"
                    ]
                ),
                -int(
                    item[
                        "profile_ready_count"
                    ]
                ),
                -int(
                    item[
                        "all_company_count"
                    ]
                ),
                str(
                    item[
                        name_key
                    ]
                ),
            )
        )

        return result

    suspect_records = [
        row
        for row in records
        if row[
            "classification_quality"
        ]
        == "SUSPECT"
    ]

    review_records = [
        row
        for row in records
        if row[
            "classification_quality"
        ]
        == "REVIEW"
    ]

    priority_records = [
        row
        for row in records
        if row[
            "translation_bucket"
        ]
        == "translate_priority"
    ]

    return {
        "schema_version": (
            "axiom-translation-universe-census.v2.6.4.0"
        ),
        "generation_mode": (
            "diagnostic_only_no_classification_mutation"
        ),
        "summary": {
            "overview_company_count": len(
                records
            ),
            "classified_company_count": sum(
                row[
                    "classification_status"
                ]
                == "classified"
                for row in records
            ),
            "profile_ready_symbol_count": len(
                ready_symbols
            ),
            "overview_and_profile_ready_count": sum(
                row[
                    "profile_production_ready"
                ]
                for row in records
            ),
            "translation_priority_count": len(
                priority_records
            ),
            "classification_suspect_count": len(
                suspect_records
            ),
            "classification_review_count": len(
                review_records
            ),
            "classification_source_counts": dict(
                sorted(
                    source_counts.items()
                )
            ),
            "classification_quality_counts": dict(
                sorted(
                    quality_counts.items()
                )
            ),
            "translation_bucket_counts": dict(
                sorted(
                    bucket_counts.items()
                )
            ),
        },
        "translation_policy": {
            "priority_theme_ids": sorted(
                PRIORITY_TRANSLATION_THEME_IDS
            ),
            "non_priority_theme_ids": sorted(
                NON_PRIORITY_TRANSLATION_THEME_IDS
            ),
            "note": (
                "Only profile-ready companies with HIGH-quality "
                "classified paths in priority themes are automatic "
                "translation candidates."
            ),
        },
        "themes": _family_rows(
            theme_counts,
            id_key="theme_id",
            name_key="theme_name",
        ),
        "sectors": _family_rows(
            sector_counts,
            id_key="sector_id",
            name_key="sector_name",
        ),
        "translation_priority_companies": (
            priority_records
        ),
        "classification_suspects": sorted(
            suspect_records,
            key=lambda row: (
                float(
                    row.get(
                        "sector_confidence"
                    )
                    if row.get(
                        "sector_confidence"
                    )
                    is not None
                    else 1.0
                ),
                float(
                    row.get(
                        "theme_confidence"
                    )
                    if row.get(
                        "theme_confidence"
                    )
                    is not None
                    else 1.0
                ),
                row[
                    "ticker"
                ],
            ),
        ),
        "classification_reviews": sorted(
            review_records,
            key=lambda row: (
                float(
                    row.get(
                        "sector_confidence"
                    )
                    if row.get(
                        "sector_confidence"
                    )
                    is not None
                    else 1.0
                ),
                row[
                    "ticker"
                ],
            ),
        ),
        "records": records,
    }


def _print_report(
    report: Mapping[str, Any],
) -> None:
    summary = report[
        "summary"
    ]

    print(
        "=== V2.6.4.0 Translation Universe Census ==="
    )
    print(
        "Company overviews:              ",
        summary[
            "overview_company_count"
        ],
    )
    print(
        "Classified:                     ",
        summary[
            "classified_company_count"
        ],
    )
    print(
        "Profile-ready symbols:          ",
        summary[
            "profile_ready_symbol_count"
        ],
    )
    print(
        "Overview ∩ profile-ready:       ",
        summary[
            "overview_and_profile_ready_count"
        ],
    )
    print(
        "Translation priority:           ",
        summary[
            "translation_priority_count"
        ],
    )

    print()
    print(
        "Translation buckets:"
    )

    for key, value in (
        summary[
            "translation_bucket_counts"
        ].items()
    ):
        print(
            f"  {key:30s} {value:5d}"
        )

    print()
    print(
        "Top translation themes:"
    )

    for row in (
        report[
            "themes"
        ][
            :20
        ]
    ):
        if (
            row[
                "translation_priority_count"
            ]
            <= 0
        ):
            continue

        print(
            "  "
            f"{row['theme_name'][:28]:28s} "
            f"all={row['all_company_count']:4d} "
            f"ready={row['profile_ready_count']:4d} "
            f"translate={row['translation_priority_count']:4d}"
        )

    print()
    print(
        "=== Classification Quality Audit ==="
    )
    print(
        "HIGH:                          ",
        summary[
            "classification_quality_counts"
        ].get(
            "HIGH",
            0,
        ),
    )
    print(
        "REVIEW:                        ",
        summary[
            "classification_quality_counts"
        ].get(
            "REVIEW",
            0,
        ),
    )
    print(
        "SUSPECT:                       ",
        summary[
            "classification_quality_counts"
        ].get(
            "SUSPECT",
            0,
        ),
    )

    print()
    print(
        "Top suspect classifications:"
    )

    for row in (
        report[
            "classification_suspects"
        ][
            :25
        ]
    ):
        print(
            "  "
            f"{row['ticker']:6s} "
            f"{str(row['theme_zh_tw'] or row['theme_name'] or '')[:20]:20s} "
            "→ "
            f"{str(row['sector_zh_tw'] or row['sector_name'] or '')[:24]:24s} "
            f"theme={row['theme_confidence']} "
            f"sector={row['sector_confidence']} "
            f"source={row['classification_source']} "
            f"reasons={','.join(row['quality_reasons'])}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "V2.6.4.0 census: determine the translation "
            "universe and audit low-confidence / historically "
            "locked company classifications."
        )
    )

    parser.add_argument(
        "--profile-census",
        default=str(
            DEFAULT_PROFILE_CENSUS
        ),
    )

    parser.add_argument(
        "--output",
        default=str(
            DEFAULT_OUTPUT
        ),
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    report = build_report(
        ROOT,
        census_path=Path(
            args.profile_census
        ),
    )

    output_path = Path(
        args.output
    )

    if not output_path.is_absolute():
        output_path = (
            ROOT
            / output_path
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    _print_report(
        report
    )

    print()
    print(
        "Report:",
        output_path.relative_to(
            ROOT
        ),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )