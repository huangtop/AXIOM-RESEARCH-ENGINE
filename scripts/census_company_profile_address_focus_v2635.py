#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CENSUS = Path(
    "data/generated/company_profile_v2/full_market_census.json"
)

BUSINESS_EVIDENCE_ROOT = Path(
    "data/generated/canonical_business_evidence"
)

DEFAULT_OUTPUT = Path(
    "data/generated/company_profile_v2/"
    "address_focus_context_census_v2635.json"
)

SUPPORTED_BUSINESS_SECTIONS = {
    "item_1_business",
    "item_4_company_information",
}

ADDRESS_FOCUS_PATTERNS: tuple[str, ...] = (
    r"\baddress(?:es|ed|ing)?\b.{0,180}\bmarkets?\b",
    r"\bfocus(?:es|ed|ing)? on\b.{0,180}\b(?:markets?|industries|sectors|verticals)\b",
    r"\btarget(?:s|ed|ing)?\b.{0,180}\b(?:markets?|industries|sectors|verticals)\b",
)

# Classification buckets requested for V2.6.3.5.
# A sentence may receive multiple secondary flags, but exactly one
# primary_classification is chosen by precedence.
DEMAND_RE = re.compile(
    r"\b(?:"
    r"demand|growth|growing|increase|increasing|"
    r"investment|investments|spending|capex|"
    r"bandwidth|capacity|adoption|penetration|"
    r"secular trend|tailwind|opportunity|opportunities"
    r")\b",
    re.IGNORECASE,
)

STRATEGY_RE = re.compile(
    r"\b(?:"
    r"strategy|strategic|"
    r"prioritize|prioritizes|prioritized|"
    r"initiative|initiatives|roadmap|"
    r"expand|expansion|enter|entry|"
    r"invest|investment|allocate|allocation|"
    r"pursue|pursuing|capture|capturing|"
    r"position|positioning"
    r")\b",
    re.IGNORECASE,
)

PRODUCT_CAPABILITY_RE = re.compile(
    r"\b(?:"
    r"product|products|solution|solutions|"
    r"service|services|platform|platforms|"
    r"technology|technologies|capability|capabilities|"
    r"software|hardware|processor|processors|"
    r"cpu|cpus|gpu|gpus|dram|nand|hbm|"
    r"chip|chips|chipset|chipsets|"
    r"semiconductor|semiconductors|"
    r"module|modules|system|systems|"
    r"portfolio|offering|offerings"
    r")\b",
    re.IGNORECASE,
)

GEOGRAPHY_RE = re.compile(
    r"\b(?:"
    r"geographic|geography|region|regions|country|countries|"
    r"united states|u\.s\.|usa|canada|mexico|"
    r"china|japan|south korea|india|australia|"
    r"europe|asia|asia pacific|"
    r"north america|south america|latin america|"
    r"central america|caribbean|middle east|africa|"
    r"emea|apac"
    r")\b",
    re.IGNORECASE,
)

CUSTOMER_TYPE_RE = re.compile(
    r"\b(?:"
    r"customer|customers|oem|oems|"
    r"distributor|distributors|reseller|resellers|"
    r"retailer|retailers|channel partner|channel partners|"
    r"enterprise|enterprises|hyperscaler|hyperscalers|"
    r"cloud provider|cloud providers|"
    r"service provider|service providers|"
    r"system integrator|system integrators|"
    r"carrier|carriers|telco|telcos|"
    r"government agencies|consumers|consumer"
    r")\b",
    re.IGNORECASE,
)

MARKET_NOUN_RE = re.compile(
    r"\b(?:markets?|industries|industry|sectors?|verticals?)\b",
    re.IGNORECASE,
)

EXTERNAL_MARKET_HINT_RE = re.compile(
    r"\b(?:"
    r"automotive|industrial|healthcare|medical|"
    r"aerospace|defense|data center|data centers|"
    r"telecom|telecommunications|communications|"
    r"networking|storage|broadband|wireless|"
    r"energy|utilities|power|semiconductor|"
    r"manufacturing|construction|education|"
    r"hospitals|schools|warehouses|"
    r"financial services|banking|insurance|"
    r"retail|e-commerce|advertising|media|"
    r"gaming|professional visualization|"
    r"automotive aftermarket|transportation|"
    r"agriculture|pharmaceutical|biopharma|"
    r"public sector|government"
    r")\b",
    re.IGNORECASE,
)


def load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def normalize_space(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def sentences(text: str) -> list[str]:
    compact = normalize_space(text)

    if not compact:
        return []

    return [
        item.strip()
        for item in re.split(
            r"(?<=[.!?])\s+(?=[A-Z0-9])",
            compact,
        )
        if len(item.strip()) >= 20
    ]


def is_address_focus_sentence(
    sentence: str,
) -> bool:
    return any(
        re.search(
            pattern,
            sentence,
            flags=re.IGNORECASE,
        )
        for pattern in ADDRESS_FOCUS_PATTERNS
    )


def classify_address_focus_sentence(
    sentence: str,
) -> dict[str, Any]:
    text = normalize_space(sentence)

    signals = {
        "demand_driver": bool(
            DEMAND_RE.search(text)
        ),
        "strategy_statement": bool(
            STRATEGY_RE.search(text)
        ),
        "product_capability": bool(
            PRODUCT_CAPABILITY_RE.search(text)
        ),
        "geography": bool(
            GEOGRAPHY_RE.search(text)
        ),
        "customer_type": bool(
            CUSTOMER_TYPE_RE.search(text)
        ),
        "explicit_market_noun": bool(
            MARKET_NOUN_RE.search(text)
        ),
        "external_market_hint": bool(
            EXTERNAL_MARKET_HINT_RE.search(text)
        ),
    }

    # Precedence is deliberately conservative:
    # obvious geography/customer/product/demand/strategy noise wins
    # over external_market. external_market is assigned only when
    # the sentence has an explicit market noun or a strong vertical hint
    # and no stronger pollution signal.
    if signals["geography"]:
        primary = "geography"
    elif signals["customer_type"]:
        primary = "customer_type"
    elif signals["product_capability"]:
        primary = "product_capability"
    elif signals["demand_driver"]:
        primary = "demand_driver"
    elif signals["strategy_statement"]:
        primary = "strategy_statement"
    elif (
        signals["explicit_market_noun"]
        or signals["external_market_hint"]
    ):
        primary = "external_market"
    else:
        primary = "unclassified"

    secondary = [
        key
        for key in (
            "demand_driver",
            "strategy_statement",
            "product_capability",
            "geography",
            "customer_type",
        )
        if signals[key]
        and key != primary
    ]

    return {
        "primary_classification": primary,
        "secondary_flags": secondary,
        "signals": signals,
    }


def latest_business_evidence(
    rows: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if (
            row.get("section_type")
            in SUPPORTED_BUSINESS_SECTIONS
        )
        and isinstance(
            row.get("text"),
            str,
        )
        and row["text"].strip()
    ]

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda row: str(
            row.get("filing_date")
            or ""
        ),
    )


def missing_market_records(
    census: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []

    for row in (
        census.get("records")
        or []
    ):
        coverage = (
            row.get("coverage")
            or {}
        )

        if coverage.get(
            "frontend_markets"
        ):
            continue

        rows.append(
            {
                "symbol": str(
                    row.get("symbol")
                    or ""
                ).upper(),
                "company_id": str(
                    row.get("company_id")
                    or ""
                ),
                "readiness_reasons": list(
                    row.get(
                        "readiness_reasons"
                    )
                    or []
                ),
            }
        )

    return rows


def analyze_company(
    *,
    symbol: str,
    company_id: str,
    evidence_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    latest = latest_business_evidence(
        evidence_rows
    )

    if latest is None:
        return {
            "symbol": symbol,
            "company_id": company_id,
            "status": "no_supported_business_evidence",
            "address_focus_sentence_count": 0,
            "address_focus_sentences": [],
            "primary_classifications": [],
        }

    matched = []

    for sentence in sentences(
        str(
            latest.get("text")
            or ""
        )
    ):
        if not is_address_focus_sentence(
            sentence
        ):
            continue

        classification = (
            classify_address_focus_sentence(
                sentence
            )
        )

        matched.append(
            {
                "sentence": sentence,
                **classification,
            }
        )

    return {
        "symbol": symbol,
        "company_id": company_id,
        "status": (
            "address_focus_found"
            if matched
            else "no_address_focus_found"
        ),
        "filing_date": latest.get(
            "filing_date"
        ),
        "form": latest.get(
            "form"
        ),
        "section_type": latest.get(
            "section_type"
        ),
        "business_evidence_id": latest.get(
            "business_evidence_id"
        ),
        "address_focus_sentence_count": len(
            matched
        ),
        "primary_classifications": sorted(
            {
                row[
                    "primary_classification"
                ]
                for row in matched
            }
        ),
        "address_focus_sentences": matched,
    }


def build_report(
    root: Path,
    *,
    census_path: Path,
    symbols: set[str] | None = None,
    limit: int | None = None,
    examples_per_class: int = 12,
    progress_every: int = 100,
) -> dict[str, Any]:
    census = load_json(
        census_path
    )

    records = missing_market_records(
        census
    )

    if symbols:
        records = [
            row
            for row in records
            if row["symbol"] in symbols
        ]

    if limit is not None:
        records = records[
            :max(
                int(limit),
                0,
            )
        ]

    evidence_index = load_json(
        root
        / BUSINESS_EVIDENCE_ROOT
        / "index.json"
    )

    company_to_file = (
        evidence_index.get(
            "company_id_to_file"
        )
        or {}
    )

    companies = []

    sentence_class_counts: Counter[
        str
    ] = Counter()

    company_class_counts: Counter[
        str
    ] = Counter()

    examples: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    total = len(
        records
    )

    for position, row in enumerate(
        records,
        start=1,
    ):
        symbol = row[
            "symbol"
        ]
        company_id = row[
            "company_id"
        ]

        rel = company_to_file.get(
            company_id
        )

        if not rel:
            result = {
                "symbol": symbol,
                "company_id": company_id,
                "status": "missing_evidence_index_mapping",
                "address_focus_sentence_count": 0,
                "address_focus_sentences": [],
                "primary_classifications": [],
            }
        else:
            evidence_rows = load_json(
                root
                / BUSINESS_EVIDENCE_ROOT
                / rel
            )

            result = analyze_company(
                symbol=symbol,
                company_id=company_id,
                evidence_rows=evidence_rows,
            )

        companies.append(
            result
        )

        seen_classes = set()

        for item in (
            result.get(
                "address_focus_sentences"
            )
            or []
        ):
            primary = item[
                "primary_classification"
            ]

            sentence_class_counts[
                primary
            ] += 1

            seen_classes.add(
                primary
            )

            if (
                len(
                    examples[
                        primary
                    ]
                )
                < examples_per_class
            ):
                examples[
                    primary
                ].append(
                    {
                        "symbol": symbol,
                        "company_id": (
                            company_id
                        ),
                        "sentence": item[
                            "sentence"
                        ],
                        "secondary_flags": (
                            item[
                                "secondary_flags"
                            ]
                        ),
                    }
                )

        for primary in (
            seen_classes
        ):
            company_class_counts[
                primary
            ] += 1

        if (
            position == 1
            or position == total
            or (
                progress_every > 0
                and position
                % progress_every
                == 0
            )
        ):
            found = sum(
                item.get(
                    "status"
                )
                == "address_focus_found"
                for item in companies
            )

            print(
                "[V2.6.3.5 address/focus census] "
                f"{position}/{total} "
                f"symbol={symbol} "
                f"address_focus={found}",
                flush=True,
            )

    address_focus_companies = [
        row
        for row in companies
        if row.get(
            "status"
        )
        == "address_focus_found"
    ]

    no_address_focus = [
        row
        for row in companies
        if row.get(
            "status"
        )
        == "no_address_focus_found"
    ]

    unavailable = [
        row
        for row in companies
        if row.get(
            "status"
        )
        not in {
            "address_focus_found",
            "no_address_focus_found",
        }
    ]

    classification_rows = [
        {
            "classification": name,
            "company_count": (
                company_class_counts[
                    name
                ]
            ),
            "sentence_count": (
                sentence_class_counts[
                    name
                ]
            ),
            "examples": (
                examples.get(
                    name,
                    [],
                )
            ),
        }
        for name in sorted(
            sentence_class_counts,
            key=lambda name: (
                -company_class_counts[
                    name
                ],
                -sentence_class_counts[
                    name
                ],
                name,
            ),
        )
    ]

    census_summary = (
        census.get(
            "summary"
        )
        or {}
    )

    return {
        "schema_version": (
            "axiom-company-profile-"
            "address-focus-census.v2.6.3.5"
        ),
        "generation_mode": (
            "diagnostic_only_no_profile_mutation"
        ),
        "source_census": str(
            census_path.relative_to(
                root
            )
        ),
        "summary": {
            "full_evidence_company_count": (
                census_summary.get(
                    "evidence_company_count"
                )
            ),
            "full_missing_frontend_market_count": (
                len(
                    missing_market_records(
                        census
                    )
                )
            ),
            "analyzed_company_count": len(
                companies
            ),
            "address_focus_company_count": len(
                address_focus_companies
            ),
            "no_address_focus_company_count": len(
                no_address_focus
            ),
            "unavailable_evidence_company_count": len(
                unavailable
            ),
            "address_focus_rate": (
                len(
                    address_focus_companies
                )
                / len(
                    companies
                )
                if companies
                else 0.0
            ),
        },
        "classifications": (
            classification_rows
        ),
        "address_focus_symbols": [
            row[
                "symbol"
            ]
            for row in (
                address_focus_companies
            )
        ],
        "no_address_focus_symbols": [
            row[
                "symbol"
            ]
            for row in (
                no_address_focus
            )
        ],
        "unavailable_symbols": [
            row[
                "symbol"
            ]
            for row in (
                unavailable
            )
        ],
        "companies": companies,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "V2.6.3.5 diagnostic census "
            "that decomposes address/focus "
            "market-like evidence into external "
            "market, demand driver, strategy, "
            "product capability, geography, "
            "and customer type."
        )
    )

    parser.add_argument(
        "--census",
        default=str(
            DEFAULT_CENSUS
        ),
    )

    parser.add_argument(
        "--output",
        default=str(
            DEFAULT_OUTPUT
        ),
    )

    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--examples-per-class",
        type=int,
        default=12,
    )

    parser.add_argument(
        "--progress-every",
        type=int,
        default=100,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    census_path = (
        ROOT
        / Path(
            args.census
        )
    )

    output_path = (
        ROOT
        / Path(
            args.output
        )
    )

    symbols = (
        {
            str(
                symbol
            ).strip().upper()
            for symbol in (
                args.symbols
            )
            if str(
                symbol
            ).strip()
        }
        if args.symbols
        else None
    )

    report = build_report(
        ROOT,
        census_path=census_path,
        symbols=symbols,
        limit=args.limit,
        examples_per_class=max(
            int(
                args.examples_per_class
            ),
            1,
        ),
        progress_every=max(
            int(
                args.progress_every
            ),
            0,
        ),
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

    summary = report[
        "summary"
    ]

    print()
    print(
        "=== V2.6.3.5 "
        "Address/Focus Context Census ==="
    )

    print(
        "Full evidence companies:       ",
        summary[
            "full_evidence_company_count"
        ],
    )

    print(
        "Full missing frontend markets: ",
        summary[
            "full_missing_frontend_market_count"
        ],
    )

    print(
        "Analyzed:                      ",
        summary[
            "analyzed_company_count"
        ],
    )

    print(
        "Address/focus companies:       ",
        summary[
            "address_focus_company_count"
        ],
    )

    print(
        "No address/focus evidence:     ",
        summary[
            "no_address_focus_company_count"
        ],
    )

    print(
        "Unavailable evidence:          ",
        summary[
            "unavailable_evidence_company_count"
        ],
    )

    print(
        "Address/focus rate:            ",
        (
            f"{summary['address_focus_rate'] * 100:.1f}%"
        ),
    )

    print()
    print(
        "Classification breakdown:"
    )

    for row in (
        report[
            "classifications"
        ]
    ):
        print(
            f"  {row['classification']:22s} "
            f"companies={row['company_count']:4d} "
            f"sentences={row['sentence_count']:5d}"
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