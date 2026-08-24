from __future__ import annotations

import re
from typing import Any, Mapping


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()

    for value in values:
        value = str(value or "").strip()

        if not value:
            continue

        key = value.lower()

        if key in seen:
            continue

        seen.add(key)
        output.append(value)

    return output


def _value_search_terms(value: Any) -> list[str]:
    terms: list[str] = []

    if isinstance(value, str):
        terms.append(value)

        aliases = {
            "AI": [
                "AI",
                "artificial intelligence",
            ],
            "United States": [
                "U.S.",
                "U.S",
                "US",
                "United States",
            ],
            "Internet Data Center": [
                "internet data center",
            ],
            "Data Center": [
                "Data Center",
                "data center",
            ],
            "Telecom": [
                "telecom",
                "telecommunications",
            ],
            "CATV": [
                "CATV",
                "cable television",
            ],
            "FTTH": [
                "FTTH",
                "fiber-to-the-home",
            ],
            "800Gbps+ optical networking": [
                "800 Gbps",
                "800Gbps",
            ],
            "bandwidth growth": [
                "bandwidth",
            ],
            "Molecular Beam Epitaxy (MBE)": [
                "Molecular Beam Epitaxy",
                "MBE",
            ],
            "Metal Organic Chemical Vapor Deposition (MOCVD)": [
                "Metal Organic Chemical Vapor Deposition",
                "MOCVD",
            ],
        }

        terms.extend(
            aliases.get(value, [])
        )

    elif isinstance(value, bool):
        terms.append(str(value))

    elif isinstance(value, (int, float)):
        numeric = float(value)

        if 0 <= numeric <= 1:
            pct = numeric * 100

            terms.append(
                f"{pct:.1f}%"
            )

            if pct.is_integer():
                terms.append(
                    f"{int(pct)}%"
                )

        elif abs(numeric) >= 1_000_000:
            millions = numeric / 1_000_000

            if millions.is_integer():
                amount = str(
                    int(millions)
                )
            else:
                amount = (
                    f"{millions:.1f}"
                )

            terms.extend([
                f"${amount} million",
                f"{amount} million",
            ])

        terms.append(str(value))

    return _dedupe_strings(terms)


def _field_candidates(
    field_evidence: Mapping[str, Any],
    field_key: str,
    *,
    nested_key: str | None = None,
) -> list[str]:
    value = field_evidence.get(field_key)

    if nested_key is not None:
        if not isinstance(value, Mapping):
            return []

        value = value.get(nested_key)

    if isinstance(value, str):
        return [value]

    if isinstance(value, list):
        return [
            str(item)
            for item in value
            if isinstance(item, str)
            and item.strip()
        ]

    return []


def _find_case_insensitive(
    text: str,
    term: str,
) -> tuple[int, int] | None:
    escaped = re.escape(term)
    if re.fullmatch(r"[A-Za-z0-9]+", term) and (
        len(term) <= 3 or term.isupper()
    ):
        escaped = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"

    match = re.search(
        escaped,
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return match.start(), match.end()


def _find_flexible_text(
    raw_text: str,
    candidate: str,
) -> tuple[int, int] | None:
    candidate = re.sub(
        r"\s+",
        " ",
        candidate,
    ).strip()

    if not candidate:
        return None

    # A whole paragraph can be very long.
    # Use a stable leading sequence instead of creating
    # a huge regex.
    words = re.findall(
        r"\S+",
        candidate,
    )

    if not words:
        return None

    for word_count in (
        min(24, len(words)),
        min(16, len(words)),
        min(10, len(words)),
        min(6, len(words)),
    ):
        if word_count < 4:
            continue

        selected = words[:word_count]

        pattern = r"\s+".join(
            re.escape(word)
            for word in selected
        )

        match = re.search(
            pattern,
            raw_text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.start(), match.end()

    return None


def _sentence_or_paragraph_span(
    raw_text: str,
    start: int,
    end: int,
) -> tuple[int, int]:
    left_limit = max(
        0,
        start - 600,
    )

    right_limit = min(
        len(raw_text),
        end + 900,
    )

    left_window = raw_text[
        left_limit:start
    ]

    left_positions = [
        left_window.rfind("\n"),
        left_window.rfind(". "),
        left_window.rfind("? "),
        left_window.rfind("! "),
    ]

    left_relative = max(left_positions)

    if left_relative >= 0:
        quote_start = (
            left_limit
            + left_relative
            + 1
        )
    else:
        quote_start = left_limit

    right_window = raw_text[
        end:right_limit
    ]

    candidates: list[int] = []

    for marker in (
        ".",
        "\n",
        "?",
        "!",
    ):
        position = right_window.find(
            marker
        )

        if position >= 0:
            candidates.append(position)

    if candidates:
        quote_end = (
            end
            + min(candidates)
            + 1
        )
    else:
        quote_end = right_limit

    while (
        quote_start < quote_end
        and raw_text[quote_start].isspace()
    ):
        quote_start += 1

    while (
        quote_end > quote_start
        and raw_text[quote_end - 1].isspace()
    ):
        quote_end -= 1

    return quote_start, quote_end


def _best_span(
    *,
    raw_text: str,
    value: Any,
    candidates: list[str],
    aliases: list[str] | None = None,
) -> tuple[int, int] | None:
    search_terms = _value_search_terms(
        value
    )
    search_terms = _dedupe_strings(search_terms + list(aliases or []))

    # Best case:
    # find the value inside one of the evidence
    # paragraphs that produced the field.
    for candidate in candidates:
        candidate_span = (
            _find_flexible_text(
                raw_text,
                candidate,
            )
        )

        if not candidate_span:
            continue

        candidate_start, _ = (
            candidate_span
        )

        search_end = min(
            len(raw_text),
            candidate_start
            + max(
                len(candidate) + 1200,
                1800,
            ),
        )

        local_text = raw_text[
            candidate_start:search_end
        ]

        for term in search_terms:
            found = (
                _find_case_insensitive(
                    local_text,
                    term,
                )
            )

            if not found:
                continue

            return (
                candidate_start
                + found[0],
                candidate_start
                + found[1],
            )

        # Do not immediately fall back to the candidate paragraph.
        # Another candidate may contain the literal value.
        continue

    # Fall back to direct value lookup.
    for term in search_terms:
        found = _find_case_insensitive(
            raw_text,
            term,
        )

        if found:
            return found

    return None


def _make_evidence(
    *,
    raw_text: str,
    evidence: Mapping[str, Any],
    value: Any,
    candidates: list[str],
    aliases: list[str] | None = None,
) -> dict[str, Any] | None:
    span = _best_span(
        raw_text=raw_text,
        value=value,
        candidates=candidates,
        aliases=aliases,
    )

    if not span:
        return None

    match_start, match_end = span

    quote_start, quote_end = (
        _sentence_or_paragraph_span(
            raw_text,
            match_start,
            match_end,
        )
    )

    source_offset = int(
        evidence.get(
            "start_character"
        )
        or 0
    )

    return {
        "business_evidence_id":
            evidence.get(
                "business_evidence_id"
            ),
        "form":
            evidence.get("form"),
        "accession_number":
            evidence.get(
                "accession_number"
            ),
        "filing_date":
            evidence.get(
                "filing_date"
            ),
        "section_type":
            evidence.get(
                "section_type"
            ),
        "quote":
            raw_text[
                quote_start:quote_end
            ],
        "evidence_start_character":
            quote_start,
        "evidence_end_character":
            quote_end,
        "document_start_character":
            source_offset
            + quote_start,
        "document_end_character":
            source_offset
            + quote_end,
        "matched_start_character":
            match_start,
        "matched_end_character":
            match_end,
        "text_sha256":
            evidence.get(
                "text_sha256"
            ),
    }


def _provenance_item(
    *,
    raw_text: str,
    evidence: Mapping[str, Any],
    value: Any,
    candidates: list[str],
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "value": value,
        "evidence": _make_evidence(
            raw_text=raw_text,
            evidence=evidence,
            value=value,
            candidates=candidates,
            aliases=aliases,
        ),
    }


def build_value_provenance(
    *,
    profile: Mapping[str, Any],
    raw_text: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    field_evidence = (
        profile.get("field_evidence")
        or {}
    )

    result: dict[str, Any] = {}

    summary = (
        profile.get("company_summary")
        or {}
    )

    one_line = summary.get(
        "one_line_business"
    )

    if one_line:
        result[
            "company_summary.one_line_business"
        ] = _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=one_line,
            candidates=_field_candidates(
                field_evidence,
                "company_summary.one_line_business",
            ),
        )

    markets = (
        profile.get("markets")
        or []
    )

    result["markets"] = [
        _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=value,
            candidates=_field_candidates(
                field_evidence,
                "markets",
            ),
        )
        for value in markets
    ]

    product_stack = (
        profile.get("product_stack")
        or []
    )

    result["product_stack"] = [
        _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=value,
            candidates=(
                _field_candidates(
                    field_evidence,
                    "product_stack_by_value",
                    nested_key=str(value),
                )
                or _field_candidates(
                    field_evidence,
                    "product_stack",
                )
            ),
            aliases=_field_candidates(
                field_evidence,
                "product_stack_source_terms",
                nested_key=str(value),
            ),
        )
        for value in product_stack
    ]

    market_products = (
        profile.get("market_products")
        or {}
    )

    result[
        "market_products"
    ] = {}

    for market_key, values in (
        market_products.items()
    ):
        result[
            "market_products"
        ][market_key] = [
            _provenance_item(
                raw_text=raw_text,
                evidence=evidence,
                value=value,
                candidates=_field_candidates(
                    field_evidence,
                    "market_products",
                    nested_key=market_key,
                ),
            )
            for value in values
        ]

    technologies = (
        profile.get(
            "core_technologies"
        )
        or []
    )

    result[
        "core_technologies"
    ] = [
        _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=value,
            candidates=_field_candidates(
                field_evidence,
                "core_technologies",
            ),
        )
        for value in technologies
    ]

    manufacturing = (
        profile.get("manufacturing")
        or {}
    )

    result["manufacturing"] = {
        "model": [
            _provenance_item(
                raw_text=raw_text,
                evidence=evidence,
                value=value,
                candidates=_field_candidates(
                    field_evidence,
                    "manufacturing",
                ),
            )
            for value in (
                manufacturing.get(
                    "model"
                )
                or []
            )
        ],
        "locations": [
            _provenance_item(
                raw_text=raw_text,
                evidence=evidence,
                value=value,
                candidates=_field_candidates(
                    field_evidence,
                    "manufacturing",
                ),
            )
            for value in (
                manufacturing.get(
                    "locations"
                )
                or []
            )
        ],
        "critical_assets": [
            _provenance_item(
                raw_text=raw_text,
                evidence=evidence,
                value=value,
                candidates=_field_candidates(
                    field_evidence,
                    "manufacturing",
                ),
            )
            for value in (
                manufacturing.get(
                    "critical_assets"
                )
                or []
            )
        ],
    }

    customer_types = (
        profile.get(
            "customer_types"
        )
        or []
    )

    result["customer_types"] = [
        _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=value,
            candidates=_field_candidates(
                field_evidence,
                "customer_types",
            ),
        )
        for value in customer_types
    ]

    ai_exposure = (
        profile.get("ai_exposure")
    )

    if ai_exposure:
        result[
            "ai_exposure"
        ] = _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=ai_exposure,
            candidates=_field_candidates(
                field_evidence,
                "ai_exposure",
            ),
        )

    advantages = (
        profile.get(
            "competitive_advantages"
        )
        or []
    )

    result[
        "competitive_advantages"
    ] = [
        _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=value,
            candidates=_field_candidates(
                field_evidence,
                "competitive_advantages",
            ),
        )
        for value in advantages
    ]

    demand_drivers = (
        profile.get(
            "demand_drivers"
        )
        or []
    )

    result[
        "demand_drivers"
    ] = [
        _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=value,
            candidates=_field_candidates(
                field_evidence,
                "demand_drivers",
            ),
        )
        for value in demand_drivers
    ]

    strategy_changes = (
        profile.get(
            "strategy_changes"
        )
        or []
    )

    result[
        "strategy_changes"
    ] = [
        _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=value,
            candidates=_field_candidates(
                field_evidence,
                "strategy_changes",
            ),
        )
        for value in strategy_changes
    ]

    financial = (
        profile.get(
            "financial_snapshot"
        )
        or {}
    )

    financial_candidates = (
        _field_candidates(
            field_evidence,
            "financial_snapshot",
        )
    )

    def candidates_containing(*terms: str) -> list[str]:
        matched = [
            candidate
            for candidate in financial_candidates
            if all(
                term.lower() in candidate.lower()
                for term in terms
            )
        ]

        return matched or financial_candidates

    result[
        "financial_snapshot"
    ] = {}

    scalar_candidate_map = {
        "fiscal_year": financial_candidates,
        "revenue": candidates_containing(
            "our revenue was"
        ),
        "gross_margin": candidates_containing(
            "gross margin"
        ),
        "net_loss": candidates_containing(
            "net loss"
        ),
    }

    for key in (
        "fiscal_year",
        "revenue",
        "gross_margin",
        "net_loss",
    ):
        value = financial.get(key)

        if value is None:
            continue

        result[
            "financial_snapshot"
        ][key] = _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=value,
            candidates=scalar_candidate_map[key],
        )

    result[
        "financial_snapshot"
    ][
        "revenue_mix"
    ] = {}

    for market, value in (
        financial.get(
            "revenue_mix"
        )
        or {}
    ).items():
        result[
            "financial_snapshot"
        ][
            "revenue_mix"
        ][market] = _provenance_item(
            raw_text=raw_text,
            evidence=evidence,
            value=value,
            candidates=candidates_containing(
                "earned",
                "total revenue",
            )
        )

    result[
        "financial_snapshot"
    ][
        "customer_concentration"
    ] = {}

    for customer, value in (
        financial.get(
            "customer_concentration"
        )
        or {}
    ).items():
        customer_candidates = [
            candidate
            for candidate
            in financial_candidates
            if customer.lower()
            in candidate.lower()
        ]

        if not customer_candidates:
            customer_candidates = (
                financial_candidates
            )

        result[
            "financial_snapshot"
        ][
            "customer_concentration"
        ][customer] = (
            _provenance_item(
                raw_text=raw_text,
                evidence=evidence,
                value=value,
                candidates=customer_candidates,
            )
        )

    return result
