#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.company_overview import (
    build_company_overviews,
    write_company_overviews,
)


ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> Any:
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def _primary_business_score(
    item: Mapping[str, Any],
) -> int:
    if "primary_business_score" in item:
        return int(
            item.get(
                "primary_business_score"
            )
            or 0
        )

    source_ids = {
        str(value)
        for value in (
            item.get(
                "source_signal_ids"
            )
            or []
        )
    }

    if any(
        value.startswith(
            "product:"
        )
        for value in source_ids
    ):
        return 2

    if any(
        value.startswith(
            (
                "capability:",
                "infrastructure:",
            )
        )
        for value in source_ids
    ):
        return 1

    return 0


def _print_publication_diagnostics(
    report: Mapping[str, Any],
) -> None:
    knowledge_payload = _load(
        ROOT
        / "data/generated/knowledge_inference/"
        "knowledge_inference.json"
    )

    knowledge_by_company = {
        str(row["company_id"]): row
        for row in (
            knowledge_payload.get(
                "records"
            )
            or []
        )
        if row.get("company_id")
    }

    reason_counts: Counter[str] = Counter()
    classified_sector_score_counts: Counter[str] = Counter()
    unclassified_sector_score_counts: Counter[str] = Counter()

    primary_business_evidence_count = 0
    official_industry_count = 0

    examples: dict[
        str,
        list[str],
    ] = {}

    for row in report.get(
        "records"
    ) or []:
        cid = str(
            row.get("company_id")
            or ""
        )

        source = knowledge_by_company.get(
            cid,
            {},
        )

        if source.get(
            "primary_business_evidence"
        ):
            primary_business_evidence_count += 1

        if row.get(
            "official_industry"
        ):
            official_industry_count += 1

        knowledge = list(
            source.get(
                "knowledge"
            )
            or []
        )

        theme_id = str(
            (
                (
                    row.get("path")
                    or {}
                ).get("theme")
                or {}
            ).get("id")
            or ""
        )

        sector_id = str(
            (
                (
                    row.get("path")
                    or {}
                ).get("sector")
                or {}
            ).get("id")
            or ""
        )

        selected_sector = next(
            (
                item
                for item in knowledge
                if str(
                    item.get(
                        "knowledge_id"
                    )
                    or ""
                )
                == sector_id
            ),
            None,
        )

        selected_sector_score = (
            _primary_business_score(
                selected_sector
            )
            if selected_sector
            else 0
        )

        if row.get(
            "status"
        ) == "classified":
            classified_sector_score_counts[
                str(
                    selected_sector_score
                )
            ] += 1
            continue

        if row.get(
            "status"
        ) == "awaiting_business_evidence":
            reason = (
                "awaiting_business_evidence"
            )

        elif not theme_id:
            reason = (
                "no_theme"
            )

        elif not sector_id:
            reason = (
                "no_sector"
            )

        elif selected_sector is None:
            reason = (
                "selected_sector_missing_from_knowledge"
            )

        elif selected_sector_score <= 0:
            reason = (
                "selected_sector_not_primary_business"
            )

        elif not (
            row.get(
                "evidence"
            )
            or []
        ):
            reason = (
                "selected_path_missing_business_evidence"
            )

        else:
            reason = (
                "other_publication_gate"
            )

        reason_counts[
            reason
        ] += 1

        if (
            row.get("status")
            == "evidence_available_unclassified"
        ):
            unclassified_sector_score_counts[
                str(
                    selected_sector_score
                )
            ] += 1

        ticker = str(
            row.get(
                "ticker"
            )
            or cid
        )

        examples.setdefault(
            reason,
            [],
        )

        if len(
            examples[
                reason
            ]
        ) < 12:
            examples[
                reason
            ].append(
                ticker
            )

    print()
    print(
        "=== Company Overview Publication Diagnostics ==="
    )

    print(
        "Primary business evidence in valuation scope:"
        f" {primary_business_evidence_count}"
    )

    if official_industry_count:
        print(
            "Official industry in valuation scope:       "
            f"{official_industry_count}"
        )

    print()
    print(
        "Unclassified / pending reasons:"
    )

    for reason, count in reason_counts.most_common():
        sample = ", ".join(
            examples.get(
                reason,
                [],
            )
        )

        print(
            f"  {reason:<42}"
            f"{count:>6}"
            + (
                f"   e.g. {sample}"
                if sample
                else ""
            )
        )

    print()
    print(
        "Selected sector primary-business score "
        "(classified):"
    )

    for score, count in sorted(
        classified_sector_score_counts.items()
    ):
        print(
            f"  score={score:<3}"
            f"{count:>6}"
        )

    print()
    print(
        "Selected sector primary-business score "
        "(evidence-available unclassified):"
    )

    for score, count in sorted(
        unclassified_sector_score_counts.items()
    ):
        print(
            f"  score={score:<3}"
            f"{count:>6}"
        )


def main() -> int:
    print("PATCH: overview-publication-diagnostics-v1")

    report = build_company_overviews(
        ROOT,
        respect_existing_locks=False,
    )

    write_company_overviews(
        report,
        ROOT
        / "data/generated/company_overview",
        preserve_existing=False,
    )

    summary = report[
        "summary"
    ]

    print(
        "=== Full-Market Company Overview Rebuild ==="
    )

    print(
        "Companies:                       "
        f"{summary['company_count']}"
    )

    print(
        "Classified:                      "
        f"{summary['classified_count']}"
    )

    print(
        "Evidence available, unclassified:"
        f" {summary['evidence_available_unclassified_count']}"
    )

    print(
        "Awaiting business evidence:      "
        f"{summary['awaiting_evidence_count']}"
    )

    print(
        "Output: data/generated/company_overview"
    )

    _print_publication_diagnostics(
        report
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )