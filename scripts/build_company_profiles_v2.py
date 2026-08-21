#!/usr/bin/env python3
"""
V2.6.5.8 — Production Promotion Quality Gate

This file intentionally freezes the V2.6.5.7 extractor implementation at the
known-good repository commit fa9f64c341eda97e457c4178686b6409b12dae33 and
overlays promotion-only quality logic.

Important:
- extractor semantics are not changed here;
- product_stack is never rewritten by the promotion gate;
- PROMOTE / REVIEW / FAIL controls production promotion only;
- OpenAI is not used by this script.

The frozen source is loaded from the repository's own Git object database.
That keeps this handoff file small while making the extractor freeze explicit
and reproducible.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

FROZEN_V2657_COMMIT = (
    "fa9f64c341eda97e457c4178686b6409b12dae33"
)
FROZEN_SCRIPT_PATH = (
    "scripts/build_company_profiles_v2.py"
)


class FrozenExtractorLoadError(RuntimeError):
    pass


def _load_frozen_v2657_namespace() -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "git",
                "show",
                (
                    f"{FROZEN_V2657_COMMIT}:"
                    f"{FROZEN_SCRIPT_PATH}"
                ),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        raise FrozenExtractorLoadError(
            "cannot load frozen V2.6.5.7 extractor from "
            f"{FROZEN_V2657_COMMIT}:{FROZEN_SCRIPT_PATH}"
        ) from exc

    source = result.stdout

    marker = (
        '\nif __name__ == "__main__":\n'
        "    raise SystemExit(main())"
    )

    if marker not in source:
        raise FrozenExtractorLoadError(
            "frozen V2.6.5.7 source has unexpected module tail"
        )

    source = source.replace(
        marker,
        "",
        1,
    )

    namespace: dict[str, Any] = {
        "__name__": "_axiom_frozen_company_profiles_v2657",
        "__file__": str(
            ROOT
            / FROZEN_SCRIPT_PATH
        ),
        "__package__": None,
    }

    exec(
        compile(
            source,
            (
                f"{FROZEN_V2657_COMMIT}:"
                f"{FROZEN_SCRIPT_PATH}"
            ),
            "exec",
        ),
        namespace,
    )

    return namespace


_V2657 = _load_frozen_v2657_namespace()


# Export the frozen implementation first. Promotion-only names below then
# intentionally override selected gate/report functions.
for _name, _value in _V2657.items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value


# === V2.6.5.8 PRODUCTION PROMOTION QUALITY GATE ============================

PROMOTION_GATE_VERSION = "v2.6.5.8"

_PROMOTION_HARD_PREFIX_RE = re.compile(
    r"^(?:"
    r"any\s+|"
    r"are\s+|"
    r"is\s+|"
    r"was\s+|"
    r"were\s+|"
    r"paid\s+licenses?\s+to\s+|"
    r"functionality\s+of\s+|"
    r"completeness\s+of\s+|"
    r"end-to-end\s+platform\s+spanning\s+|"
    r"ev\s+market\s+under\s+"
    r")",
    flags=re.IGNORECASE,
)

_PROMOTION_PROSE_CONTAINS = (
    " designed to comply with ",
    " essentially an operating system ",
    " are based on ",
    " interconnectivity between ",
    " data bandwidth",
    " applicable software solutions",
    " software design tools",
    " listed below:",
    " described in the previous sentence",
    " our devices ",
    " ourselves",
)

_PROMOTION_MARKET_GEOGRAPHY_RE = re.compile(
    r"(?:"
    r"\b(?:Europe|Asia|China|United States|U\.S\.)\b"
    r".*\b(?:market|ourselves|specific product)\b"
    r"|"
    r"\bmarket\s+under\b"
    r")",
    flags=re.IGNORECASE,
)

_PROMOTION_LEGAL_RE = re.compile(
    r"\b(?:"
    r"patents?|patent issued|"
    r"securities|prospectus|"
    r"litigation|regulatory filing"
    r")\b",
    flags=re.IGNORECASE,
)

_PROMOTION_EMBEDDED_FILING_RE = re.compile(
    r"(?:"
    r"•|"
    r"\bOur\s+(?:devices?|products?)\b|"
    r"\bfive\s+major\s+[^:]{0,80}:"
    r")",
    flags=re.IGNORECASE,
)

# Generic organization-name guard. It intentionally does not contain company
# names. Two-or-more title-case tokens ending in an organization head should
# not be promoted as a product.
_PROMOTION_ORGANIZATION_RE = re.compile(
    r"^(?:"
    r"[A-Z][A-Za-z0-9&.+-]*\s+"
    r"){1,5}"
    r"(?:"
    r"Networks?|Systems?|Corporation|Corp\.?|Inc\.?|"
    r"Technologies|Technology|Holdings?|Group"
    r")$"
)

_PROMOTION_EXTERNAL_PRODUCT_RE = re.compile(
    r"^(?:new\s+)?"
    r"(?:"
    r"[A-Z][A-Za-z0-9&.+-]*\s+"
    r"){2,8}"
    r"(?:Ally|Console|Device|Platform)$",
    flags=re.IGNORECASE,
)


def _promotion_issue(
    *,
    issue_type: str,
    symbol: str,
    value: str,
    severity: str = "REVIEW",
) -> dict[str, str]:
    return {
        "type": issue_type,
        "severity": severity,
        "symbol": symbol,
        "value": value,
    }


def _promotion_quality_issue_rows(
    row: dict,
) -> list[dict]:
    """
    Promotion-only diagnostics.

    The extractor output is read but never mutated. Existing V2.6.5.7 quality
    diagnostics remain part of the decision, then V2.6.5.8 adds guards for
    patterns observed to be unsafe for direct frontend promotion.
    """
    symbol = str(
        row.get("symbol")
        or ""
    ).strip().upper()

    products = _record_products(
        row
    )

    if not products:
        return [
            _promotion_issue(
                issue_type="EMPTY_PRODUCT_STACK",
                severity="FAIL",
                symbol=symbol,
                value="",
            )
        ]

    issues: list[dict] = []

    for issue in _quality_issue_rows(
        row
    ):
        normalized = dict(
            issue
        )

        if (
            normalized.get("type")
            == "EMPTY_PRODUCT_STACK"
        ):
            normalized["severity"] = "FAIL"
        else:
            normalized["severity"] = "REVIEW"

        issues.append(
            normalized
        )

    seen = {
        (
            str(issue.get("type") or ""),
            str(issue.get("value") or ""),
        )
        for issue in issues
    }

    def add(
        issue_type: str,
        value: str,
    ) -> None:
        key = (
            issue_type,
            value,
        )

        if key in seen:
            return

        seen.add(
            key
        )
        issues.append(
            _promotion_issue(
                issue_type=issue_type,
                symbol=symbol,
                value=value,
            )
        )

    for raw_value in products:
        text = re.sub(
            r"\s+",
            " ",
            str(raw_value or ""),
        ).strip()

        if not text:
            continue

        lower = text.casefold()

        if _PROMOTION_HARD_PREFIX_RE.search(
            text
        ):
            add(
                "PROMOTION_NON_PRODUCT_CLAUSE",
                text,
            )
            continue

        if any(
            marker in (
                " " + lower + " "
            )
            for marker
            in _PROMOTION_PROSE_CONTAINS
        ):
            add(
                "PROMOTION_FILING_PROSE",
                text,
            )
            continue

        if _PROMOTION_EMBEDDED_FILING_RE.search(
            text
        ):
            add(
                "PROMOTION_EMBEDDED_FILING_TEXT",
                text,
            )
            continue

        if _PROMOTION_LEGAL_RE.search(
            text
        ):
            add(
                "PROMOTION_LEGAL_OR_PATENT_TEXT",
                text,
            )
            continue

        if _PROMOTION_MARKET_GEOGRAPHY_RE.search(
            text
        ):
            add(
                "PROMOTION_MARKET_OR_GEOGRAPHY",
                text,
            )
            continue

        if _PROMOTION_ORGANIZATION_RE.fullmatch(
            text
        ):
            add(
                "PROMOTION_ORGANIZATION_NAME",
                text,
            )
            continue

        if _PROMOTION_EXTERNAL_PRODUCT_RE.fullmatch(
            text
        ):
            add(
                "PROMOTION_EXTERNAL_PRODUCT",
                text,
            )
            continue

        # Sentence punctuation inside a candidate is a strong sign that an SEC
        # prose fragment crossed a list boundary. Product abbreviations and
        # decimal/model punctuation are not affected by this guard.
        if (
            ". " in text
            and len(
                text.split()
            ) >= 7
        ):
            add(
                "PROMOTION_SENTENCE_BOUNDARY",
                text,
            )
            continue

    return issues


def _promotion_quality_gate(
    row: dict,
) -> dict:
    products = _record_products(
        row
    )

    issues = (
        _promotion_quality_issue_rows(
            row
        )
    )

    fail_issues = [
        issue
        for issue in issues
        if issue.get(
            "severity"
        ) == "FAIL"
    ]

    review_issues = [
        issue
        for issue in issues
        if issue.get(
            "severity"
        ) == "REVIEW"
    ]

    if fail_issues:
        status = "FAIL"
    elif review_issues:
        status = "REVIEW"
    else:
        status = "PROMOTE"

    return {
        "status": status,
        "product_stack_count": len(
            products
        ),
        "issue_count": len(
            issues
        ),
        "issue_types": sorted(
            {
                str(
                    issue.get("type")
                    or ""
                )
                for issue in issues
                if issue.get("type")
            }
        ),
        "issue_samples": issues[:8],
    }


def _promotion_gate_summary(
    rows: list[dict],
) -> dict:
    counts = {
        "PROMOTE": 0,
        "REVIEW": 0,
        "FAIL": 0,
    }

    for row in rows:
        status = str(
            row.get(
                "promotion_status"
            )
            or ""
        )

        if status in counts:
            counts[
                status
            ] += 1

    total = len(
        rows
    )

    return {
        "total": total,
        "promote": counts["PROMOTE"],
        "review": counts["REVIEW"],
        "fail": counts["FAIL"],
        "promotion_rate": (
            round(
                counts["PROMOTE"]
                / total,
                4,
            )
            if total
            else 0.0
        ),
        "usable_rate": (
            round(
                (
                    counts["PROMOTE"]
                    + counts["REVIEW"]
                )
                / total,
                4,
            )
            if total
            else 0.0
        ),
    }


def _production_promotion_gate(
    report: dict,
    *,
    sample_limit: int = 12,
) -> dict:
    metadata = (
        _translation_candidate_metadata()
    )

    rows = []

    for record in (
        report.get("records")
        or []
    ):
        symbol = str(
            record.get("symbol")
            or ""
        ).strip().upper()

        meta = metadata.get(
            symbol,
            {},
        )

        gate = _promotion_quality_gate(
            record
        )

        rows.append(
            {
                "symbol": symbol,
                "theme_id": meta.get(
                    "theme_id"
                ),
                "theme_name": meta.get(
                    "theme_name"
                ),
                "promotion_status": gate[
                    "status"
                ],
                "product_stack_count": gate[
                    "product_stack_count"
                ],
                "issue_count": gate[
                    "issue_count"
                ],
                "issue_types": gate[
                    "issue_types"
                ],
                "issue_samples": gate[
                    "issue_samples"
                ],
            }
        )

    by_symbol = {
        row["symbol"]: row
        for row in rows
    }

    core_rows = [
        row
        for row in rows
        if row.get(
            "theme_id"
        )
        in CORE_TECH_THEME_IDS
    ]

    major_rows = []

    for symbol in MAJOR_TECH_SYMBOLS:
        row = by_symbol.get(
            symbol
        )

        if row is None:
            major_rows.append(
                {
                    "symbol": symbol,
                    "promotion_status":
                        "NOT_IN_UNIVERSE",
                }
            )
        else:
            major_rows.append(
                row
            )

    attention = [
        row
        for row in core_rows
        if row[
            "promotion_status"
        ]
        != "PROMOTE"
    ][
        :max(
            30,
            sample_limit,
        )
    ]

    return {
        "gate_version":
            PROMOTION_GATE_VERSION,
        "definitions": {
            "PROMOTE": (
                "non-empty enriched product stack with no "
                "V2.6.5.7 or V2.6.5.8 promotion blocker"
            ),
            "REVIEW": (
                "usable enriched product stack, but promotion "
                "is blocked pending review"
            ),
            "FAIL": (
                "empty product stack or hard extraction failure"
            ),
        },
        "strategic_universe":
            _promotion_gate_summary(
                rows
            ),
        "core_tech_subset":
            _promotion_gate_summary(
                core_rows
            ),
        "major_tech_gate":
            major_rows,
        "core_tech_attention":
            attention,
        "rows":
            rows,
    }


def _compact_census_report_v2658(
    report: dict,
    *,
    sample_limit: int = 12,
    worst_limit: int = 20,
    expand_symbols: set[str] | None = None,
) -> dict:
    base = _V2657[
        "_compact_census_report"
    ](
        report,
        sample_limit=sample_limit,
        worst_limit=worst_limit,
        expand_symbols=expand_symbols,
    )

    base[
        "schema_version"
    ] = (
        "axiom-company-profile-product-census.v2.6.5.8"
    )

    base[
        "promotion_gate"
    ] = (
        _production_promotion_gate(
            report,
            sample_limit=sample_limit,
        )
    )

    return base


def _pct(
    value: float,
) -> str:
    return (
        f"{value * 100:.1f}%"
    )


def _one_screen_promotion_summary(
    report: dict,
) -> str:
    gate = _production_promotion_gate(
        report,
        sample_limit=12,
    )

    strategic = gate[
        "strategic_universe"
    ]
    core = gate[
        "core_tech_subset"
    ]

    lines = [
        "=== V2.6.5.8 Production Promotion Gate ===",
        "",
        "Strategic universe",
        (
            f"  Total {strategic['total']:>6}   "
            f"PROMOTE {strategic['promote']:>6}   "
            f"REVIEW {strategic['review']:>6}   "
            f"FAIL {strategic['fail']:>6}"
        ),
        (
            f"  Promotion rate "
            f"{_pct(strategic['promotion_rate'])}   "
            f"Usable rate "
            f"{_pct(strategic['usable_rate'])}"
        ),
        "",
        "Core AI / Tech",
        (
            f"  Total {core['total']:>6}   "
            f"PROMOTE {core['promote']:>6}   "
            f"REVIEW {core['review']:>6}   "
            f"FAIL {core['fail']:>6}"
        ),
        (
            f"  Promotion rate "
            f"{_pct(core['promotion_rate'])}   "
            f"Usable rate "
            f"{_pct(core['usable_rate'])}"
        ),
        "",
        "Major Tech",
    ]

    for row in gate[
        "major_tech_gate"
    ]:
        symbol = row[
            "symbol"
        ]

        status = row[
            "promotion_status"
        ]

        if status == "NOT_IN_UNIVERSE":
            lines.append(
                f"  {symbol:<6} NOT_IN_UNIVERSE"
            )
            continue

        issue_types = (
            row.get(
                "issue_types"
            )
            or []
        )

        suffix = (
            "  "
            + ", ".join(
                issue_types
            )
            if issue_types
            else ""
        )

        lines.append(
            f"  {symbol:<6} {status:<7}{suffix}"
        )

    attention = (
        gate.get(
            "core_tech_attention"
        )
        or []
    )

    if attention:
        lines.extend(
            [
                "",
                "Core-tech promotion attention",
            ]
        )

        for row in attention[
            :30
        ]:
            issue_types = (
                ", ".join(
                    row.get(
                        "issue_types"
                    )
                    or []
                )
                or "-"
            )

            lines.append(
                (
                    f"  {row['symbol']:<6} "
                    f"{row['promotion_status']:<7} "
                    f"{issue_types}"
                )
            )

    return "\n".join(
        lines
    )


# Patch only reporting/gating behavior in the frozen namespace. Extraction
# helpers such as _extract_named_products, _extract_section_aware_products,
# _extract_subject_gated_product_lists, _enrich_profile_product_recall and
# _apply_product_recall remain the exact V2.6.5.7 implementation.
_V2657[
    "_production_promotion_gate"
] = _production_promotion_gate
_V2657[
    "_promotion_quality_gate"
] = _promotion_quality_gate
_V2657[
    "_promotion_quality_issue_rows"
] = _promotion_quality_issue_rows


def main() -> int:
    """
    Run the frozen V2.6.5.7 build/extraction pipeline, then expose V2.6.5.8
    promotion decisions. Existing --write behavior is intentionally blocked
    for V2.6.5.8 until safe upsert is implemented; this prevents destructive
    batch pruning from being used as a promotion mechanism.
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=(
            "V2.6.5.8 Company Profile build with frozen "
            "V2.6.5.7 extraction and promotion-only quality gate."
        )
    )

    parser.add_argument(
        "--scope",
        choices=(
            "published",
            "strategic",
        ),
        default="strategic",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--write",
        action="store_true",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
    )
    parser.add_argument(
        "--full-report",
        action="store_true",
    )
    parser.add_argument(
        "--diagnostic-limit",
        type=int,
        default=12,
    )
    parser.add_argument(
        "--worst-limit",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--one-screen",
        action="store_true",
    )

    args = parser.parse_args()

    if args.write:
        print(
            json.dumps(
                {
                    "write_status": "blocked",
                    "gate_version":
                        PROMOTION_GATE_VERSION,
                    "write_error": (
                        "V2.6.5.8 blocks destructive batch --write. "
                        "Promotion is dry-run only until safe canonical "
                        "upsert is implemented."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    explicit_symbols = [
        str(symbol)
        .strip()
        .upper()
        for symbol in args.symbol
        if str(symbol).strip()
    ]

    batch_scope = (
        "published"
        if args.scope
        == "published"
        else "evidence"
    )

    symbols = (
        explicit_symbols
        if explicit_symbols
        else (
            _strategic_symbols()
            if args.scope
            == "strategic"
            else []
        )
    )

    report = (
        build_company_profile_batch(
            ROOT,
            scope=batch_scope,
            symbols=symbols,
        )
    )

    report[
        "_requested_scope"
    ] = args.scope

    _apply_product_recall(
        report
    )

    promotion_gate = (
        _production_promotion_gate(
            report,
            sample_limit=max(
                1,
                args.diagnostic_limit,
            ),
        )
    )

    report[
        "promotion_gate"
    ] = promotion_gate

    product_recall_policy = {
        "version": "v2.6.5.8",
        "extractor_version":
            "v2.6.5.7-frozen",
        "promotion_gate_version":
            PROMOTION_GATE_VERSION,
        "principles": [
            "freeze_v2657_extractor",
            "promotion_gate_does_not_mutate_product_stack",
            "promotion_requires_non_empty_product_stack",
            "promotion_blocks_non_product_clauses",
            "promotion_blocks_filing_prose",
            "promotion_blocks_embedded_filing_text",
            "promotion_blocks_legal_or_patent_text",
            "promotion_blocks_market_or_geography_fragments",
            "promotion_blocks_organization_names",
            "promotion_blocks_external_product_signals",
            "destructive_batch_write_disabled",
            "openai_not_used",
        ],
    }

    report[
        "product_recall_policy"
    ] = product_recall_policy

    if (
        args.one_screen
        or (
            args.scope
            == "strategic"
            and not explicit_symbols
            and not args.full_report
        )
    ):
        print(
            _one_screen_promotion_summary(
                report
            )
        )
    elif args.full_report:
        public = _public_report(
            report
        )
        print(
            json.dumps(
                public,
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        output = (
            _compact_census_report_v2658(
                report,
                sample_limit=max(
                    1,
                    args.diagnostic_limit,
                ),
                worst_limit=max(
                    1,
                    args.worst_limit,
                ),
                expand_symbols=set(
                    explicit_symbols
                ),
            )
        )

        output[
            "product_recall_policy"
        ] = product_recall_policy

        print(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2,
            )
        )

    if not (
        report[
            "summary"
        ][
            "complete"
        ]
    ):
        return 1

    return 0


# Export promotion helpers for tests/importers.
globals()[
    "_promotion_quality_issue_rows"
] = _promotion_quality_issue_rows
globals()[
    "_promotion_quality_gate"
] = _promotion_quality_gate
globals()[
    "_production_promotion_gate"
] = _production_promotion_gate


if __name__ == "__main__":
    raise SystemExit(
        main()
    )