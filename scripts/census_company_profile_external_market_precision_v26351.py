#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT = Path(
    "data/generated/company_profile_v2/"
    "address_focus_context_census_v2635.json"
)

DEFAULT_OUTPUT = Path(
    "data/generated/company_profile_v2/"
    "external_market_precision_audit_v26351.json"
)

LIST_CONNECTOR_RE = re.compile(
    r"\s*(?:,|;|\band\b|\bor\b|&)\s*",
    re.IGNORECASE,
)

LEADING_FRAME_RE = re.compile(
    r"^(?:"
    r"the\s+|"
    r"both\s+the\s+|"
    r"our\s+|"
    r"their\s+|"
    r"new\s+|"
    r"global\s+|"
    r"key\s+|"
    r"major\s+|"
    r"core\s+|"
    r"primary\s+|"
    r"target(?:ed)?\s+|"
    r"addressable\s+"
    r")+",
    re.IGNORECASE,
)

TRAILING_MARKET_RE = re.compile(
    r"\s+(?:"
    r"markets?|industries|industry|"
    r"sectors?|verticals?|end[- ]markets?"
    r")\s*$",
    re.IGNORECASE,
)

ADDRESS_FOCUS_CAPTURE_PATTERNS: tuple[
    re.Pattern[str],
    ...
] = (
    re.compile(
        r"\baddress(?:es|ed|ing)?\b"
        r".{0,80}?\b(?:"
        r"markets?|industries|sectors|verticals|end[- ]markets?"
        r")\b"
        r"(?:\s+(?:for|including|such as|across|in)\s+)?"
        r"(?P<tail>[^.;:]{2,220})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfocus(?:es|ed|ing)?\s+on\s+"
        r"(?P<body>[^.;:]{2,220}?)"
        r"\b(?:"
        r"markets?|industries|sectors|verticals|end[- ]markets?"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\btarget(?:s|ed|ing)?\s+"
        r"(?P<body>[^.;:]{2,220}?)"
        r"\b(?:"
        r"markets?|industries|sectors|verticals|end[- ]markets?"
        r")\b",
        re.IGNORECASE,
    ),
)

GENERIC_NOISE = {
    "market",
    "markets",
    "industry",
    "industries",
    "sector",
    "sectors",
    "vertical",
    "verticals",
    "end market",
    "end markets",
    "opportunity",
    "opportunities",
    "growth",
    "demand",
    "customers",
    "customer",
    "products",
    "product",
    "solutions",
    "solution",
    "services",
    "service",
    "business",
    "businesses",
    "applications",
    "application",
}

FRAGMENT_RE = re.compile(
    r"^(?:"
    r"both|either|among|including|include|"
    r"such as|for example|other|others|"
    r"various|several|certain|these|those|"
    r"which|that|where|with|without|"
    r"to|from|of|for|by|as|at|into"
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
    r"module|modules|system|systems|"
    r"portfolio|offering|offerings|"
    r"performance|processing|compute|computing"
    r")\b",
    re.IGNORECASE,
)

CUSTOMER_RE = re.compile(
    r"\b(?:"
    r"customer|customers|oem|oems|"
    r"distributor|distributors|reseller|resellers|"
    r"retailer|retailers|channel partner|channel partners|"
    r"enterprise customers?|hyperscalers?|"
    r"cloud providers?|service providers?|"
    r"system integrators?|carriers?|telcos?|"
    r"consumers?"
    r")\b",
    re.IGNORECASE,
)

GEOGRAPHY_RE = re.compile(
    r"\b(?:"
    r"united states|u\.s\.|usa|canada|mexico|"
    r"china|japan|south korea|india|australia|"
    r"europe|asia|asia pacific|north america|"
    r"south america|latin america|central america|"
    r"caribbean|middle east|africa|emea|apac|"
    r"countries|country|regions?|geographic"
    r")\b",
    re.IGNORECASE,
)

DEMAND_STRATEGY_RE = re.compile(
    r"\b(?:"
    r"demand|growth|growing|increase|increasing|"
    r"spending|investment|investments|adoption|"
    r"opportunity|opportunities|tailwind|"
    r"strategy|strategic|initiative|initiatives|"
    r"roadmap|prioritize|prioritized|expansion|"
    r"capture|capturing|position|positioning"
    r")\b",
    re.IGNORECASE,
)

KNOWN_EXTERNAL_MARKET_RE = re.compile(
    r"\b(?:"
    r"automotive(?: aftermarket)?|industrial|healthcare|medical|"
    r"aerospace|defense|data center|data centers|"
    r"telecom|telecommunications|communications infrastructure|"
    r"networking|storage|broadband|wireless|"
    r"energy|utilities|power|manufacturing|construction|"
    r"education|hospitals|schools|warehouses|"
    r"financial services|banking|insurance|"
    r"retail|e-commerce|advertising|media|gaming|"
    r"professional visualization|transportation|"
    r"agriculture|pharmaceutical|biopharma|"
    r"public sector|government|broadcasting|"
    r"semiconductor"
    r")\b",
    re.IGNORECASE,
)


def load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def normalize_space(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def clean_candidate(value: str) -> str:
    candidate = normalize_space(value)
    candidate = candidate.strip(
        " \t\r\n,;:()[]{}\"'“”‘’"
    )
    candidate = re.sub(
        r"^(?:and|or)\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = LEADING_FRAME_RE.sub(
        "",
        candidate,
    )
    candidate = TRAILING_MARKET_RE.sub(
        "",
        candidate,
    )
    candidate = candidate.strip(
        " \t\r\n,;:()[]{}\"'“”‘’"
    )
    return normalize_space(candidate)


def title_market(value: str) -> str:
    words = []
    for token in value.split():
        if token.upper() in {
            "AI",
            "IT",
            "PC",
            "PCs",
            "RF",
            "EV",
            "EVs",
        }:
            words.append(token.upper())
        else:
            words.append(
                token.capitalize()
            )
    return " ".join(words)


def canonical_market(value: str) -> str:
    lower = normalize_space(
        value
    ).lower()

    canonical = {
        "data centers": "Data Center",
        "data center": "Data Center",
        "automotive aftermarket": (
            "Automotive Aftermarket"
        ),
        "professional visualization": (
            "Professional Visualization"
        ),
        "financial services": (
            "Financial Services"
        ),
        "public sector": "Public Sector",
        "communications infrastructure": (
            "Communications Infrastructure"
        ),
    }

    if lower in canonical:
        return canonical[lower]

    return title_market(
        normalize_space(value)
    )


def extract_market_phrase_candidates(
    sentence: str,
) -> list[str]:
    text = normalize_space(
        sentence
    )

    raw_segments: list[str] = []

    # Most address/focus sentences put the vertical list immediately
    # before the market noun: "focus on automotive and industrial markets".
    for pattern in (
        ADDRESS_FOCUS_CAPTURE_PATTERNS[
            1:
        ]
    ):
        match = pattern.search(
            text
        )
        if match:
            body = match.groupdict().get(
                "body"
            )
            if body:
                raw_segments.append(
                    body
                )

    # Also support "address markets including automotive and industrial".
    address_match = (
        ADDRESS_FOCUS_CAPTURE_PATTERNS[
            0
        ].search(
            text
        )
    )
    if address_match:
        tail = (
            address_match.groupdict().get(
                "tail"
            )
        )
        if tail:
            raw_segments.append(
                tail
            )

    values: list[str] = []
    seen: set[str] = set()

    for segment in raw_segments:
        segment = re.sub(
            r"\b(?:rely|depend|use|using|"
            r"with|through|where|which|that)\b.*$",
            "",
            segment,
            flags=re.IGNORECASE,
        )

        parts = [
            clean_candidate(
                part
            )
            for part in (
                LIST_CONNECTOR_RE.split(
                    segment
                )
            )
        ]

        for part in parts:
            if not part:
                continue

            key = part.lower()

            if key in seen:
                continue

            seen.add(
                key
            )
            values.append(
                part
            )

    return values


def classify_candidate(
    candidate: str,
) -> dict[str, Any]:
    value = clean_candidate(
        candidate
    )
    lower = value.lower()

    reasons: list[str] = []

    if (
        not value
        or lower in GENERIC_NOISE
        or len(value) < 3
    ):
        classification = (
            "fragment"
        )
        reasons.append(
            "empty_or_generic"
        )

    elif FRAGMENT_RE.search(
        value
    ):
        classification = (
            "fragment"
        )
        reasons.append(
            "fragment_prefix"
        )

    elif GEOGRAPHY_RE.search(
        value
    ):
        classification = (
            "geography_contamination"
        )
        reasons.append(
            "geography_signal"
        )

    elif CUSTOMER_RE.search(
        value
    ):
        classification = (
            "customer_contamination"
        )
        reasons.append(
            "customer_signal"
        )

    elif PRODUCT_CAPABILITY_RE.search(
        value
    ):
        classification = (
            "product_capability_contamination"
        )
        reasons.append(
            "product_capability_signal"
        )

    elif DEMAND_STRATEGY_RE.search(
        value
    ):
        classification = (
            "strategy_demand_contamination"
        )
        reasons.append(
            "strategy_or_demand_signal"
        )

    elif KNOWN_EXTERNAL_MARKET_RE.search(
        value
    ):
        classification = (
            "clean_market"
        )
        reasons.append(
            "known_external_market_signal"
        )

    else:
        classification = (
            "ambiguous"
        )
        reasons.append(
            "no_strong_market_or_noise_signal"
        )

    return {
        "candidate": value,
        "canonical_candidate": (
            canonical_market(
                value
            )
            if classification
            == "clean_market"
            else None
        ),
        "classification": (
            classification
        ),
        "reasons": reasons,
    }


def external_market_sentences(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[
        dict[str, Any]
    ] = []

    for company in (
        payload.get(
            "companies"
        )
        or []
    ):
        symbol = str(
            company.get(
                "symbol"
            )
            or ""
        ).upper()

        company_id = str(
            company.get(
                "company_id"
            )
            or ""
        )

        for item in (
            company.get(
                "address_focus_sentences"
            )
            or []
        ):
            if (
                item.get(
                    "primary_classification"
                )
                != "external_market"
            ):
                continue

            rows.append(
                {
                    "symbol": symbol,
                    "company_id": (
                        company_id
                    ),
                    "sentence": (
                        normalize_space(
                            item.get(
                                "sentence"
                            )
                            or ""
                        )
                    ),
                    "source_secondary_flags": list(
                        item.get(
                            "secondary_flags"
                        )
                        or []
                    ),
                }
            )

    return rows


def audit_sentence(
    row: dict[str, Any],
) -> dict[str, Any]:
    candidates = (
        extract_market_phrase_candidates(
            row[
                "sentence"
            ]
        )
    )

    audited = [
        classify_candidate(
            candidate
        )
        for candidate in candidates
    ]

    clean = [
        item[
            "canonical_candidate"
        ]
        for item in audited
        if (
            item[
                "classification"
            ]
            == "clean_market"
            and item[
                "canonical_candidate"
            ]
        )
    ]

    clean = list(
        dict.fromkeys(
            clean
        )
    )

    classes = {
        item[
            "classification"
        ]
        for item in audited
    }

    if (
        clean
        and classes
        <= {
            "clean_market",
        }
    ):
        sentence_status = (
            "clean"
        )
    elif clean:
        sentence_status = (
            "mixed"
        )
    elif not audited:
        sentence_status = (
            "no_candidate"
        )
    elif classes == {
        "ambiguous"
    }:
        sentence_status = (
            "ambiguous"
        )
    else:
        sentence_status = (
            "contaminated"
        )

    return {
        **row,
        "sentence_status": (
            sentence_status
        ),
        "clean_market_candidates": (
            clean
        ),
        "candidates": audited,
    }


def build_report(
    payload: dict[str, Any],
    *,
    limit: int | None = None,
    examples_per_class: int = 15,
) -> dict[str, Any]:
    source_rows = (
        external_market_sentences(
            payload
        )
    )

    if limit is not None:
        source_rows = source_rows[
            :max(
                int(limit),
                0,
            )
        ]

    audited_rows = [
        audit_sentence(
            row
        )
        for row in source_rows
    ]

    sentence_status_counts: Counter[
        str
    ] = Counter()

    candidate_class_counts: Counter[
        str
    ] = Counter()

    company_statuses: dict[
        str,
        set[str],
    ] = defaultdict(set)

    clean_markets_by_company: dict[
        str,
        list[str],
    ] = defaultdict(list)

    examples: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in audited_rows:
        status = row[
            "sentence_status"
        ]
        sentence_status_counts[
            status
        ] += 1

        company_key = (
            row[
                "company_id"
            ]
            or row[
                "symbol"
            ]
        )
        company_statuses[
            company_key
        ].add(
            status
        )

        for market in (
            row[
                "clean_market_candidates"
            ]
        ):
            if market not in (
                clean_markets_by_company[
                    company_key
                ]
            ):
                clean_markets_by_company[
                    company_key
                ].append(
                    market
                )

        for candidate in (
            row[
                "candidates"
            ]
        ):
            classification = (
                candidate[
                    "classification"
                ]
            )
            candidate_class_counts[
                classification
            ] += 1

            if (
                len(
                    examples[
                        classification
                    ]
                )
                < examples_per_class
            ):
                examples[
                    classification
                ].append(
                    {
                        "symbol": (
                            row[
                                "symbol"
                            ]
                        ),
                        "sentence": (
                            row[
                                "sentence"
                            ]
                        ),
                        "candidate": (
                            candidate[
                                "candidate"
                            ]
                        ),
                        "canonical_candidate": (
                            candidate[
                                "canonical_candidate"
                            ]
                        ),
                        "reasons": (
                            candidate[
                                "reasons"
                            ]
                        ),
                    }
                )

    promotable_company_keys = {
        key
        for key, markets in (
            clean_markets_by_company.items()
        )
        if markets
    }

    strict_clean_company_keys = {
        key
        for key, statuses in (
            company_statuses.items()
        )
        if (
            statuses
            and statuses
            <= {
                "clean",
            }
            and key
            in promotable_company_keys
        )
    }

    source_summary = (
        payload.get(
            "summary"
        )
        or {}
    )

    return {
        "schema_version": (
            "axiom-company-profile-"
            "external-market-precision-audit.v2.6.3.5.1"
        ),
        "generation_mode": (
            "diagnostic_only_no_profile_mutation"
        ),
        "summary": {
            "source_address_focus_company_count": (
                source_summary.get(
                    "address_focus_company_count"
                )
            ),
            "source_external_market_company_count": len(
                {
                    row[
                        "company_id"
                    ]
                    or row[
                        "symbol"
                    ]
                    for row in source_rows
                }
            ),
            "audited_sentence_count": len(
                audited_rows
            ),
            "promotable_company_count": len(
                promotable_company_keys
            ),
            "strict_clean_company_count": len(
                strict_clean_company_keys
            ),
            "sentence_status_counts": dict(
                sorted(
                    sentence_status_counts.items()
                )
            ),
            "candidate_class_counts": dict(
                sorted(
                    candidate_class_counts.items()
                )
            ),
        },
        "promotable_companies": [
            {
                "company_key": key,
                "markets": (
                    clean_markets_by_company[
                        key
                    ]
                ),
                "strict_clean": (
                    key
                    in strict_clean_company_keys
                ),
            }
            for key in sorted(
                promotable_company_keys
            )
        ],
        "examples": {
            key: value
            for key, value in sorted(
                examples.items()
            )
        },
        "sentences": audited_rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "V2.6.3.5.1 precision audit for "
            "external-market address/focus sentences."
        )
    )

    parser.add_argument(
        "--input",
        default=str(
            DEFAULT_INPUT
        ),
    )

    parser.add_argument(
        "--output",
        default=str(
            DEFAULT_OUTPUT
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--examples-per-class",
        type=int,
        default=15,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_path = (
        ROOT
        / Path(
            args.input
        )
    )

    output_path = (
        ROOT
        / Path(
            args.output
        )
    )

    payload = load_json(
        input_path
    )

    report = build_report(
        payload,
        limit=args.limit,
        examples_per_class=max(
            int(
                args.examples_per_class
            ),
            1,
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

    print(
        "=== V2.6.3.5.1 "
        "External Market Precision Audit ==="
    )
    print(
        "External-market companies: ",
        summary[
            "source_external_market_company_count"
        ],
    )
    print(
        "Audited sentences:         ",
        summary[
            "audited_sentence_count"
        ],
    )
    print(
        "Promotable companies:      ",
        summary[
            "promotable_company_count"
        ],
    )
    print(
        "Strict-clean companies:    ",
        summary[
            "strict_clean_company_count"
        ],
    )

    print()
    print(
        "Sentence status:"
    )
    for key, value in (
        summary[
            "sentence_status_counts"
        ].items()
    ):
        print(
            f"  {key:18s} {value:5d}"
        )

    print()
    print(
        "Candidate classification:"
    )
    for key, value in (
        summary[
            "candidate_class_counts"
        ].items()
    ):
        print(
            f"  {key:32s} {value:5d}"
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