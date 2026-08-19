from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from axiom_engine.business_evidence_store import load_business_evidence


class CompanySignalsError(RuntimeError):
    pass


FORBIDDEN_MEMBERSHIP_KEYS = {
    "ticker",
    "tickers",
    "symbol",
    "symbols",
    "company_id",
    "company_ids",
}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanySignalsError(f"cannot read {path}: {exc}") from exc


def _pattern(alias: str) -> re.Pattern[str]:
    escaped = (
        re.escape(alias.strip())
        .replace(r"\-", r"[\-\u2010-\u2015]")
        .replace(r"\ ", r"[\s\-/\u2010-\u2015]+")
    )
    return re.compile(
        rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _context(
    text: str,
    start: int,
    end: int,
    maximum: int,
) -> dict[str, Any]:
    half = max(0, maximum // 2)
    left = max(0, start - half)
    right = min(len(text), end + half)
    return {
        "start_character": start,
        "end_character": end,
        "matched_text": text[start:end],
        "context": " ".join(text[left:right].split()),
    }


def _compact_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _sentence_units(text: str) -> list[tuple[int, int, str]]:
    """
    Deterministically split filing text into sentence-like units while
    preserving source character offsets.

    SEC Item 1 text is often semi-structured and may use semicolons or
    line breaks instead of conventional sentence punctuation.
    """
    output: list[tuple[int, int, str]] = []
    start = 0

    for match in re.finditer(r"(?<=[.!?;])\s+|\n+", text):
        end = match.start()
        raw = text[start:end]
        compact = _compact_space(raw)
        if len(compact) >= 20:
            output.append((start, end, compact))
        start = match.end()

    raw = text[start:]
    compact = _compact_space(raw)
    if len(compact) >= 20:
        output.append((start, len(text), compact))

    return output


def _offering_role(sentence: str) -> str | None:
    """
    Identify generic primary-offering statements without assigning taxonomy.

    Roles are intentionally broad:
      - product
      - service
      - operator_business

    This is evidence extraction only. It must not emit product:* / sector:* /
    theme:* knowledge from free text.
    """
    lowered = f" {_compact_space(sentence).lower()} "

    # Explicit customer/use-case/end-market framing is not the company's
    # primary offering statement.
    if re.search(
        r"\b(?:"
        r"used by|used in|for use in|designed for|sold into|"
        r"serves? customers?|serving customers?|"
        r"customers? include|end markets? include|"
        r"applications? include|deployed in"
        r")\b",
        lowered,
    ):
        # A sentence can still be an offering sentence when the offering is
        # stated first and the customer clause follows. Only reject sentences
        # that lack an ownership/action cue.
        if not re.search(
            r"\b(?:we|our company|the company|our business)\b.{0,120}"
            r"\b(?:design|develop|manufactur|sell|offer|provide|supply|"
            r"produce|deliver|operate|own|manage|market)\w*\b",
            lowered,
        ):
            return None

    # Procurement/dependency language is not an offering.
    if re.search(
        r"\b(?:"
        r"purchase|purchases|procure|procures|source|sources|"
        r"suppliers?|dependent on|dependence on|costs? of|costs? from"
        r")\b",
        lowered,
    ):
        return None

    # Product-oriented ownership language.
    product_patterns = (
        r"\bwe\b.{0,100}\b(?:design|develop|manufactur|produce|sell|market|supply)\w*\b",
        r"\bour (?:products?|product portfolio|portfolio|offerings?)\b.{0,100}\b(?:include|includes|comprise|comprises|consist of|consists of)\b",
        r"\b(?:manufacturer|developer|supplier|producer) of\b",
        r"\bour business\b.{0,80}\b(?:manufactur|product|equipment|devices?|systems?|components?)\b",
    )

    if any(re.search(pattern, lowered) for pattern in product_patterns):
        return "product"

    # Service-oriented ownership language.
    service_patterns = (
        r"\bwe\b.{0,100}\b(?:provide|offer|deliver|operate|manage)\w*\b.{0,100}\bservices?\b",
        r"\bour (?:services?|service offerings?|solutions?)\b.{0,100}\b(?:include|includes|comprise|comprises|consist of|consists of)\b",
        r"\b(?:provider|operator) of\b.{0,100}\b(?:services?|platforms?|networks?|facilities?)\b",
        r"\bour business\b.{0,80}\b(?:provides?|offers?|delivers?)\b",
    )

    if any(re.search(pattern, lowered) for pattern in service_patterns):
        return "service"

    # Operating-business statements are common for banks, insurers, retailers,
    # REITs, hotels, airlines, utilities and other service/asset operators.
    operator_patterns = (
        r"\bwe (?:are|operate as|own and operate|operate|manage)\b",
        r"\bour business (?:primarily )?(?:consists of|comprises|focuses on|is engaged in)\b",
        r"\bthe company (?:operates|owns|manages|provides|offers)\b",
        r"\bwe are (?:a|an|the)\b.{0,100}\b(?:bank|insurer|retailer|operator|airline|utility|reit|restaurant|hotel|broker|lender|distributor)\b",
    )

    if any(re.search(pattern, lowered) for pattern in operator_patterns):
        return "operator_business"

    return None


def _extract_primary_offering_evidence(
    source_rows: list[Mapping[str, Any]],
    *,
    maximum_records: int = 12,
) -> list[dict[str, Any]]:
    """
    Extract generic primary-offering evidence from canonical SEC business text.

    Output is intentionally evidence-only and does not invent taxonomy IDs.
    """
    candidates: list[dict[str, Any]] = []

    for source in source_rows:
        text = str(source.get("text") or "")
        if not text:
            continue

        for start, end, sentence in _sentence_units(text):
            role = _offering_role(sentence)
            if role is None:
                continue

            # Confidence is deterministic and based on explicitness, not on
            # company identity or ticker.
            lowered = sentence.lower()

            confidence = 0.78

            if re.search(
                r"\b(?:we|our company|the company|our business)\b",
                lowered,
            ):
                confidence += 0.08

            if re.search(
                r"\b(?:design|develop|manufactur|sell|offer|provide|"
                r"operate|own|manage|supplier|provider|manufacturer)\w*\b",
                lowered,
            ):
                confidence += 0.06

            if re.search(
                r"\b(?:products?|services?|portfolio|offerings?|business)\b",
                lowered,
            ):
                confidence += 0.04

            confidence = round(min(0.96, confidence), 4)

            candidates.append(
                {
                    "business_evidence_id": source.get(
                        "business_evidence_id"
                    ),
                    "provenance_id": source.get("provenance_id"),
                    "accession_number": source.get("accession_number"),
                    "filing_date": source.get("filing_date"),
                    "offering_role": role,
                    "confidence": confidence,
                    "statement": sentence,
                    "start_character": start,
                    "end_character": end,
                }
            )

    # Deterministic de-duplication: same role + same normalized statement.
    seen: set[tuple[str, str]] = set()
    output: list[dict[str, Any]] = []

    for row in sorted(
        candidates,
        key=lambda item: (
            -float(item["confidence"]),
            str(item.get("filing_date") or ""),
            str(item.get("business_evidence_id") or ""),
            str(item.get("statement") or ""),
        ),
        reverse=False,
    ):
        key = (
            str(row["offering_role"]),
            _compact_space(str(row["statement"])).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
        if len(output) >= maximum_records:
            break

    return output


def _is_company_offering(
    text: str,
    match_start: int,
    company_names: tuple[str, ...] = (),
    matched_alias: str = "",
) -> bool:
    """Distinguish company-owned offerings from customer, application, and end-market uses."""
    prefix = text[max(0, match_start - 180):match_start].lower()

    # Keep only the current sentence-like segment.
    prefix = re.split(r"[.!?;]", prefix)[-1]

    # Procurement / dependency language is not a company offering.
    if re.search(
        r"\b(?:"
        r"costs? (?:of|from)|"
        r"purchases?|"
        r"procures?|"
        r"sources?|"
        r"suppliers?|"
        r"dependent on|"
        r"dependence on"
        r")\b",
        prefix,
    ):
        return False

    # Application / customer / deployment target is not the thing the company sells.
    relation_tail = prefix[-140:]
    if re.search(
        r"\b(?:"
        r"enable(?:s|d|ing)?|"
        r"support(?:s|ed|ing)?|"
        r"power(?:s|ed|ing)?|"
        r"target(?:s|ed|ing)?|"
        r"serve(?:s|d|ing)?|"
        r"sold\s+into|"
        r"designed\s+for|"
        r"used\s+in|"
        r"deployed\s+in"
        r")\b"
        r"[^.!?;]{0,100}$",
        relation_tail,
    ):
        return False

    heading_tail = prefix[-100:]
    heading_match = re.search(
        r"(?:^|[.!?;])\s*"
        r"([A-Za-z0-9()\"'&/\-\s]{1,60}):\s*$",
        heading_tail,
    )

    if heading_match and matched_alias:
        heading_text = heading_match.group(1).lower()
        alias_text = matched_alias.lower()

        def normalize_token(token: str) -> str:
            if token.endswith("s") and len(token) > 3:
                return token[:-1]
            return token

        heading_tokens = {
            normalize_token(token)
            for token in re.findall(r"[a-z0-9]+", heading_text)
            if len(token) >= 3
        }

        alias_tokens = {
            normalize_token(token)
            for token in re.findall(r"[a-z0-9]+", alias_text)
            if len(token) >= 3
        }

        if heading_tokens & alias_tokens:
            return True

    named_company_offering = any(
        name.lower() in prefix
        and re.search(
            r"\b(?:"
            r"is|are|"
            r"designs?|"
            r"develops?|"
            r"manufactures?|"
            r"markets?|"
            r"sells?|"
            r"offers?|"
            r"provides?|"
            r"supplies?|"
            r"produces?|"
            r"delivers?|"
            r"delivering"
            r")\b",
            prefix[
                prefix.rfind(name.lower()) + len(name):
            ],
        )
        for name in company_names
        if name.strip()
    )

    return named_company_offering or bool(
        re.search(
            r"(?:\bwe\b|\bour company\b|\bthe company\b|\bbusiness\b).{0,100}"
            r"(?:design|develop|manufactur|market|sell|offer|provide|supply|produce|deliver)",
            prefix,
        )
        or re.search(
            r"(?:supplier|provider|manufacturer|developer|operator) of",
            prefix,
        )
        or re.search(
            r"(?:portfolio|suite|range|family) of",
            prefix,
        )
        or re.search(
            r"\bportfolio\s*,?\s*(?:including|includes?)\b",
            prefix,
        )
        or re.search(
            r"\bwe (?:introduced|launched|developed|created) "
            r"(?:our |the )?"
            r"[a-z0-9&/\- ]{0,60}$",
            prefix,
        )
        or re.search(
            r"\bour (?:invention|introduction|development|creation) of "
            r"(?:the )?"
            r"[a-z0-9&/\- ]{0,60}$",
            prefix,
        )
        or re.search(
            r"\bwe are (?:an?|the)\b",
            prefix,
        )
        or re.search(
            r"\bwe(?:['’]ve| have) grown into (?:an?|the)\b",
            prefix,
        )
        or re.search(
            r"\bwe(?:['’]ve| have).{0,100}\b"
            r"(?:provider|manufacturer|foundry|operator)\b",
            prefix,
        )
        or re.search(
            r"\b(?:our )?business (?:primarily )?"
            r"(?:comprises|consists of|focuses on|is engaged in)",
            prefix,
        )
        or re.search(
            r"\bour .{0,100}"
            r"(?:offerings|products|platforms|solutions) "
            r"(?:include|includes|comprise|comprises|consist of)",
            prefix,
        )
        or re.search(
            r"\bour .{0,100}capabilities .{0,40}"
            r"(?:include|includes|comprise|comprises|consist of)",
            prefix,
        )
        or re.search(
            r"\b(?:our )?platform "
            r"(?:includes|comprises|consists of)",
            prefix,
        )
    )


def _validate_policy(
    policy: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    if (
        policy.get("schema_version")
        != "company-signal-rules.v031c.2"
    ):
        raise CompanySignalsError(
            "unsupported company signal policy"
        )

    signals = policy.get("signals")

    if not isinstance(signals, list):
        raise CompanySignalsError(
            "company signal policy signals must be an array"
        )

    ids: set[str] = set()

    for signal in signals:
        signal_id = str(
            signal.get("signal_id")
            or ""
        )

        aliases = signal.get("aliases")

        if (
            not signal_id
            or signal_id in ids
            or not isinstance(aliases, list)
            or not aliases
        ):
            raise CompanySignalsError(
                f"invalid or duplicate signal rule: {signal_id}"
            )

        if FORBIDDEN_MEMBERSHIP_KEYS.intersection(signal):
            raise CompanySignalsError(
                "ticker/company membership is forbidden "
                f"in signal rules: {signal_id}"
            )

        excluded_context_patterns = signal.get(
            "excluded_context_patterns",
            [],
        )

        if (
            not isinstance(
                excluded_context_patterns,
                list,
            )
            or not all(
                isinstance(pattern, str)
                and pattern.strip()
                for pattern in excluded_context_patterns
            )
        ):
            raise CompanySignalsError(
                f"invalid excluded context patterns: {signal_id}"
            )

        try:
            for pattern in excluded_context_patterns:
                re.compile(
                    pattern,
                    re.IGNORECASE,
                )
        except re.error as exc:
            raise CompanySignalsError(
                f"invalid excluded context pattern for {signal_id}: {exc}"
            ) from exc

        ids.add(signal_id)

    return signals


def build_company_signals(
    root: Path,
    *,
    company_ids: set[str] | None = None,
    rules_path: str = "config/company_signal_rules.v031c.2.json",
    companies_path: str = "data/universe/companies.json",
    evidence_path: str = "data/generated/canonical_business_evidence/business_evidence.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(
        timezone.utc
    )

    if (
        current.tzinfo is None
        or current.utcoffset() is None
    ):
        raise ValueError(
            "now must be timezone-aware"
        )

    policy = _load(
        root / rules_path
    )

    companies = _load(
        root / companies_path
    )

    if company_ids is not None:
        companies = [
            row
            for row in companies
            if str(
                row.get("company_id")
                or ""
            )
            in company_ids
        ]

    evidence = load_business_evidence(
        root / evidence_path
    )

    rules = _validate_policy(
        policy
    )

    if (
        not isinstance(companies, list)
        or not isinstance(evidence, list)
    ):
        raise CompanySignalsError(
            "company and evidence inputs must be arrays"
        )

    evidence_by_company: dict[
        str,
        list[Mapping[str, Any]],
    ] = defaultdict(list)

    for row in evidence:
        if (
            row.get("company_id")
            and row.get("text")
            and row.get("business_evidence_id")
        ):
            evidence_by_company[
                str(row["company_id"])
            ].append(row)

    maximum_locations = int(
        policy["matching"][
            "maximum_locations_per_signal"
        ]
    )

    maximum_context = int(
        policy["matching"][
            "maximum_context_characters"
        ]
    )

    minimum_occurrences = int(
        policy["matching"][
            "minimum_occurrences"
        ]
    )

    compiled_rules = [
        (
            rule,
            [
                (
                    str(alias),
                    _pattern(str(alias)),
                )
                for alias in rule["aliases"]
            ],
            [
                re.compile(
                    str(pattern),
                    re.IGNORECASE,
                )
                for pattern in rule.get(
                    "excluded_context_patterns",
                    [],
                )
            ],
        )
        for rule in rules
    ]

    records: list[dict[str, Any]] = []

    signal_counts: Counter[str] = Counter()
    dimension_counts: Counter[str] = Counter()
    offering_role_counts: Counter[str] = Counter()

    companies_with_offering_evidence = 0

    for company in sorted(
        companies,
        key=lambda row: str(
            row.get("company_id")
            or ""
        ),
    ):
        company_id = str(
            company.get("company_id")
            or ""
        )

        full_company_names = {
            str(
                company.get(key)
                or ""
            ).strip()
            for key in (
                "legal_name",
                "display_name",
            )
            if str(
                company.get(key)
                or ""
            ).strip()
        }

        company_name_roots = {
            re.sub(
                r"\b(?:incorporated|inc|corporation|corp|limited|ltd|plc|holdings?)\b.*$",
                "",
                name,
                flags=re.IGNORECASE,
            ).strip(" ,.-")
            for name in full_company_names
        }

        company_names = tuple(
            sorted(
                full_company_names
                | {
                    name
                    for name in company_name_roots
                    if len(name) >= 4
                }
            )
        )

        source_rows = sorted(
            evidence_by_company.get(
                company_id,
                [],
            ),
            key=lambda row: (
                str(
                    row.get("filing_date")
                    or ""
                ),
                str(
                    row.get("business_evidence_id")
                    or ""
                ),
            ),
            reverse=True,
        )

        primary_offering_evidence = (
            _extract_primary_offering_evidence(
                source_rows
            )
        )

        if primary_offering_evidence:
            companies_with_offering_evidence += 1
            for offering in primary_offering_evidence:
                offering_role_counts[
                    str(
                        offering[
                            "offering_role"
                        ]
                    )
                ] += 1

        extracted: list[
            dict[str, Any]
        ] = []

        for (
            rule,
            compiled_aliases,
            excluded_context_patterns,
        ) in compiled_rules:
            occurrences: list[
                dict[str, Any]
            ] = []

            aliases_hit: set[str] = set()
            source_ids: set[str] = set()
            count = 0
            offering_count = 0

            for source in source_rows:
                text = str(
                    source["text"]
                )

                for (
                    alias,
                    pattern,
                ) in compiled_aliases:
                    for match in pattern.finditer(
                        text
                    ):
                        match_context = str(
                            _context(
                                text,
                                match.start(),
                                match.end(),
                                maximum_context,
                            )["context"]
                        )

                        if any(
                            excluded.search(
                                match_context
                            )
                            for excluded
                            in excluded_context_patterns
                        ):
                            continue

                        count += 1

                        if (
                            rule.get("dimension")
                            in {
                                "product",
                                "capability",
                                "infrastructure",
                            }
                            and _is_company_offering(
                                text,
                                match.start(),
                                company_names,
                                alias,
                            )
                        ):
                            offering_count += 1

                        elif (
                            rule.get("dimension")
                            == "supply_chain_role"
                            and (
                                alias.lower().startswith(
                                    (
                                        "we ",
                                        "our ",
                                    )
                                )
                                or "manufacturing partner"
                                in alias.lower()
                            )
                        ):
                            offering_count += 1

                        aliases_hit.add(alias)
                        source_ids.add(
                            str(
                                source[
                                    "business_evidence_id"
                                ]
                            )
                        )

                        if (
                            len(occurrences)
                            < maximum_locations
                        ):
                            occurrences.append(
                                {
                                    "business_evidence_id": (
                                        source[
                                            "business_evidence_id"
                                        ]
                                    ),
                                    "provenance_id": (
                                        source.get(
                                            "provenance_id"
                                        )
                                    ),
                                    "accession_number": (
                                        source.get(
                                            "accession_number"
                                        )
                                    ),
                                    **_context(
                                        text,
                                        match.start(),
                                        match.end(),
                                        maximum_context,
                                    ),
                                }
                            )

            if count < minimum_occurrences:
                continue

            confidence = round(
                min(
                    0.95,
                    0.55
                    + 0.08
                    * min(
                        count - 1,
                        3,
                    )
                    + 0.04
                    * min(
                        len(
                            aliases_hit
                        )
                        - 1,
                        2,
                    ),
                ),
                4,
            )

            extracted.append(
                {
                    "signal_id": rule[
                        "signal_id"
                    ],
                    "dimension": rule[
                        "dimension"
                    ],
                    "value_chain_stage": (
                        rule.get(
                            "value_chain_stage"
                        )
                    ),
                    "canonical_name": (
                        rule[
                            "canonical_name"
                        ]
                    ),
                    "confidence": (
                        confidence
                    ),
                    "occurrence_count": (
                        count
                    ),
                    "offering_occurrence_count": (
                        offering_count
                    ),
                    "primary_business_score": (
                        3
                        if offering_count
                        else 0
                    ),
                    "matched_aliases": sorted(
                        aliases_hit
                    ),
                    "source_business_evidence_ids": (
                        sorted(
                            source_ids
                        )
                    ),
                    "locations": (
                        occurrences
                    ),
                }
            )

            signal_counts[
                str(
                    rule[
                        "signal_id"
                    ]
                )
            ] += 1

            dimension_counts[
                str(
                    rule[
                        "dimension"
                    ]
                )
            ] += 1

        extracted.sort(
            key=lambda row: (
                row["dimension"],
                -row["confidence"],
                row["signal_id"],
            )
        )

        records.append(
            {
                "company_id": company_id,
                "status": (
                    "signals_available"
                    if extracted
                    else (
                        "no_signals_detected"
                        if source_rows
                        else "business_evidence_unavailable"
                    )
                ),
                "source_business_evidence_ids": [
                    str(
                        row[
                            "business_evidence_id"
                        ]
                    )
                    for row
                    in source_rows
                ],
                "primary_offering_evidence": (
                    primary_offering_evidence
                ),
                "signals": extracted,
            }
        )

    return {
        "schema_version": (
            "company-signals.v031c.2"
        ),
        "version": "V031C.2",
        "generated_at": (
            current.isoformat()
        ),
        "summary": {
            "company_count": len(
                records
            ),
            "business_evidence_company_count": sum(
                bool(
                    row[
                        "source_business_evidence_ids"
                    ]
                )
                for row
                in records
            ),
            "primary_offering_evidence_company_count": (
                companies_with_offering_evidence
            ),
            "primary_offering_evidence_role_counts": dict(
                sorted(
                    offering_role_counts.items()
                )
            ),
            "signals_available_company_count": sum(
                row["status"]
                == "signals_available"
                for row
                in records
            ),
            "no_signals_detected_company_count": sum(
                row["status"]
                == "no_signals_detected"
                for row
                in records
            ),
            "business_evidence_unavailable_company_count": sum(
                row["status"]
                == "business_evidence_unavailable"
                for row
                in records
            ),
            "signal_company_counts": dict(
                sorted(
                    signal_counts.items()
                )
            ),
            "dimension_signal_counts": dict(
                sorted(
                    dimension_counts.items()
                )
            ),
        },
        "policy": {
            "rules_path": rules_path,
            "contains_ticker_membership": (
                False
            ),
            "generic_primary_offering_extraction": (
                True
            ),
        },
        "records": records,
        "indexes": {
            "company_id_to_position": {
                row["company_id"]: index
                for (
                    index,
                    row,
                )
                in enumerate(
                    records
                )
            }
        },
    }


def write_company_signals(
    report: Mapping[str, Any],
    output: Path,
) -> None:
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )
        + "\n",
        encoding="utf-8",
    )