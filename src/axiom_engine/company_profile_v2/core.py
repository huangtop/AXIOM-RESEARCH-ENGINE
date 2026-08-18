from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class CompanyProfileV2Error(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyProfileV2Error(f"cannot read {path}: {exc}") from exc


def _find_security(root: Path, symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    securities = _load_json(root / "data/universe/securities.json")

    for row in securities:
        if str(row.get("ticker") or "").upper() == symbol:
            return row

    raise CompanyProfileV2Error(f"unknown symbol: {symbol}")


def _load_business_evidence(
    root: Path,
    company_id: str,
) -> list[dict[str, Any]]:
    base = root / "data/generated/canonical_business_evidence"
    index = _load_json(base / "index.json")

    rel = index.get("company_id_to_file", {}).get(company_id)
    if not rel:
        raise CompanyProfileV2Error(
            f"no canonical business evidence for {company_id}"
        )

    rows = _load_json(base / rel)

    if not isinstance(rows, list):
        raise CompanyProfileV2Error(
            f"business evidence must be a list: {company_id}"
        )

    return rows


def _latest_business_evidence(
    rows: list[dict[str, Any]],
    symbol: str,
) -> dict[str, Any]:
    candidates = [
        row
        for row in rows
        if row.get("section_type") == "item_1_business"
        and isinstance(row.get("text"), str)
        and row["text"].strip()
    ]

    if not candidates:
        raise CompanyProfileV2Error(
            f"no Item 1 Business text for {symbol}"
        )

    return max(
        candidates,
        key=lambda row: str(row.get("filing_date") or ""),
    )


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = re.sub(
        r"\n\d+\nTable of Contents\n",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _paragraphs(text: str) -> list[str]:
    rows = []

    for raw in text.splitlines():
        value = raw.strip()

        if not value:
            continue

        if value.lower() == "table of contents":
            continue

        if re.fullmatch(r"\d+", value):
            continue

        rows.append(value)

    return rows


def _sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text).strip()

    return [
        value.strip()
        for value in re.split(
            r"(?<=[.!?])\s+(?=[A-Z0-9])",
            compact,
        )
        if len(value.strip()) >= 20
    ]


def _slug(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def _dedupe(values: list[str]) -> list[str]:
    output = []
    seen = set()

    for value in values:
        value = re.sub(r"\s+", " ", value).strip(" ,.;:-")

        if not value:
            continue

        key = value.lower()

        if key not in seen:
            seen.add(key)
            output.append(value)

    return output


def _canonical_market_label(value: str) -> str:
    value = value.strip(" ,.;")

    quoted = re.findall(
        r'["“]([A-Za-z0-9-]{2,15})["”]',
        value,
    )

    if quoted:
        alias = quoted[-1]
        if len(alias) <= 8:
            return alias.upper() if alias.isupper() else alias.title()

    value = re.sub(r"\([^)]*\)", "", value)
    value = value.strip(" ,.;")

    special = {
        "internet data center": "Internet Data Center",
        "data center": "Data Center",
        "professional visualization": "Professional Visualization",
        "fiber-to-the-home": "FTTH",
        "telecommunications": "Telecom",
        "telecom": "Telecom",
        "cable television": "CATV",
    }

    lowered = value.lower()

    if lowered in special:
        return special[lowered]

    if value.isupper():
        return value

    return value.title()


def _split_list_phrase(value: str) -> list[str]:
    value = re.sub(r"\([^)]*\)", "", value)
    value = value.replace(" as well as ", ", ")
    value = re.sub(r"\band\b", ",", value, flags=re.IGNORECASE)
    value = re.sub(r"\bor\b", ",", value, flags=re.IGNORECASE)

    parts = []

    for item in value.split(","):
        item = item.strip(" .;:-")

        item = re.sub(
            r"^(?:a|an|the|our|their)\s+",
            "",
            item,
            flags=re.IGNORECASE,
        )

        if 1 <= len(item.split()) <= 8:
            parts.append(item)

    return _dedupe(parts)


def _extract_one_line_business(
    text: str,
) -> tuple[str | None, str | None]:
    lines = _paragraphs(text)

    preferred_markers = {
        "overview",
        "our company",
        "company overview",
        "business overview",
    }

    for index, line in enumerate(lines):
        if line.lower() not in preferred_markers:
            continue

        for candidate in lines[index + 1:index + 4]:
            if len(candidate) < 40:
                continue

            sentences = _sentences(candidate)

            if sentences:
                return sentences[0], candidate

    sentences = _sentences(text)

    for sentence in sentences:
        lower = sentence.lower()

        if (
            " is a " in lower
            or " is an " in lower
            or " is now " in lower
            or " provides " in lower
            or " pioneered " in lower
        ):
            return sentence, sentence

    return None, None


def _extract_markets(
    text: str,
) -> tuple[list[str], list[str]]:
    markets: list[str] = []
    evidence: list[str] = []

    opening = text[:10000]

    patterns = [
        r"(?:networking\s+)?end[- ]markets?\s*:\s*([^.]+)",
        r"(?:four|three|several)\s+(?:large\s+)?markets?\s*:\s*([^.]+)",
        r"target markets?\s+(?:are|include)\s+([^.]+)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            opening,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        phrase = match.group(1)

        pieces = re.split(
            r",\s*(?=[A-Za-z])|\s+and\s+",
            phrase,
        )

        for piece in pieces:
            piece = piece.strip()

            if not piece:
                continue

            label = _canonical_market_label(piece)

            if label and len(label) <= 50:
                markets.append(label)

        evidence.append(match.group(0))
        break

    # Filing structures such as NVIDIA:
    # Our Markets
    # Data Center
    # ...
    # Gaming
    # ...
    section_match = re.search(
        r"\nOur Markets\s*\n(.*?)(?:\nBusiness Strategies\s*\n|\nOur Strategy\s*\n|\Z)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if section_match:
        section = section_match.group(1)
        lines = section.splitlines()

        for index, raw in enumerate(lines[:-1]):
            line = raw.strip()

            if not line:
                continue

            if len(line) > 45:
                continue

            if len(line.split()) > 5:
                continue

            if re.search(r"[.!?:;]", line):
                continue

            next_line = lines[index + 1].strip()

            if len(next_line) < 80:
                continue

            if line[0].isupper():
                markets.append(
                    _canonical_market_label(line)
                )

        evidence.append(section[:3000])

    return _dedupe(markets), evidence


def _extract_product_stack(
    text: str,
) -> tuple[list[str], list[str]]:
    values: list[str] = []
    evidence: list[str] = []

    patterns = [
        r"levels? of integration,\s*from\s+(.+?)\.",
        r"ranging from\s+(.+?)\.",
        r"from\s+(.+?)\s+to\s+complete\s+(.+?)\.",
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            raw = " ".join(
                value
                for value in match.groups()
                if value
            )

            values.extend(_split_list_phrase(raw))
            evidence.append(match.group(0))

    building_blocks = re.search(
        r"(?:building blocks?|foundation(?:al)? products?) of\s+([^.]+)",
        text,
        flags=re.IGNORECASE,
    )

    if building_blocks:
        values = (
            _split_list_phrase(building_blocks.group(1))
            + values
        )
        evidence.append(building_blocks.group(0))

    return _dedupe(values), evidence


def _market_aliases(label: str) -> list[str]:
    aliases = [label.lower()]

    mapping = {
        "internet data center": [
            "internet data center",
            "data center",
        ],
        "catv": [
            "catv",
            "cable television",
        ],
        "telecom": [
            "telecom",
            "telecommunications",
        ],
        "ftth": [
            "ftth",
            "fiber-to-the-home",
        ],
        "professional visualization": [
            "professional visualization",
        ],
        "automotive": [
            "automotive",
        ],
        "gaming": [
            "gaming",
        ],
    }

    aliases.extend(
        mapping.get(label.lower(), [])
    )

    return _dedupe(aliases)


def _extract_products_from_paragraph(
    paragraph: str,
) -> list[str]:
    products: list[str] = []

    patterns = [
        r"\bwe supply\s+(.+?)(?:\.| that | which | for use )",
        r"\bproducts?[^.]{0,80}?\binclude\s+(.+?)\.",
        r"\bofferings? include\s+(.+?)\.",
        r"\bconsists? of\s+(.+?)\.",
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            paragraph,
            flags=re.IGNORECASE,
        ):
            phrase = match.group(1)

            phrase = re.sub(
                r"^(?:a broad array of products,\s*)?(?:including\s+)?",
                "",
                phrase,
                flags=re.IGNORECASE,
            )

            products.extend(
                _split_list_phrase(phrase)
            )

    for match in re.finditer(
        r"\bincluding\s+([^.;]+)",
        paragraph,
        flags=re.IGNORECASE,
    ):
        phrase = match.group(1)

        if len(phrase.split()) <= 30:
            products.extend(
                _split_list_phrase(phrase)
            )

    own_components = re.search(
        r"\butilize our own\s+(.+?)(?:, and|, which|\.|\()",
        paragraph,
        flags=re.IGNORECASE,
    )

    if own_components:
        products.extend(
            _split_list_phrase(
                own_components.group(1)
            )
        )

    alias_matches = re.findall(
        r'refer to .*? as ["“]([^"”]+)["”]',
        paragraph,
        flags=re.IGNORECASE,
    )

    products.extend(alias_matches)

    return _dedupe(products)


def _extract_market_products(
    text: str,
    markets: list[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    paragraphs = _paragraphs(text)

    output: dict[str, list[str]] = {}
    field_evidence: dict[str, list[str]] = {}

    for market in markets:
        aliases = _market_aliases(market)
        matched_paragraphs = []

        for paragraph in paragraphs:
            lowered = paragraph.lower()

            if any(
                alias in lowered
                for alias in aliases
            ):
                matched_paragraphs.append(paragraph)

        products = []

        for paragraph in matched_paragraphs:
            products.extend(
                _extract_products_from_paragraph(
                    paragraph
                )
            )

        key = _slug(market)

        if products:
            output[key] = _dedupe(products)
            field_evidence[key] = matched_paragraphs[:6]

    return output, field_evidence


def _extract_core_technologies(
    text: str,
) -> tuple[list[str], list[str]]:
    technologies: list[str] = []
    evidence: list[str] = []

    # Preserve company-disclosed expanded technology names.
    acronym_pattern = re.compile(
        r"([A-Z][A-Za-z0-9\- ]{3,80}?)\s*"
        r"\([\"“]([A-Z0-9-]{2,12})[\"”]\)"
    )

    for match in acronym_pattern.finditer(text):
        start = max(0, match.start() - 160)
        end = min(len(text), match.end() + 160)
        context = text[start:end].lower()

        if not any(
            token in context
            for token in (
                "technology",
                "engineering",
                "fabrication",
                "process",
                "design",
                "architecture",
                "manufactur",
            )
        ):
            continue

        expansion = re.sub(
            r"\s+",
            " ",
            match.group(1),
        ).strip()

        technologies.append(
            f"{expansion} ({match.group(2)})"
        )
        evidence.append(
            text[start:end].strip()
        )

    engineering_patterns = [
        r"expertise in\s+([^.]+engineering[^.]*)",
        r"([A-Za-z0-9-]+(?:\s+[A-Za-z0-9-]+){0,4}\s+engineering)\s+capabilit",
    ]

    for pattern in engineering_patterns:
        for match in re.finditer(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            phrase = match.group(1)

            for item in _split_list_phrase(phrase):
                if (
                    "engineering" in item.lower()
                    or "semiconductor" in item.lower()
                    or "optical" in item.lower()
                ):
                    technologies.append(item)

            evidence.append(match.group(0))

    return _dedupe(technologies), evidence


def _extract_manufacturing(
    text: str,
) -> tuple[dict[str, Any], list[str]]:
    model = []

    descriptors = [
        "vertically integrated",
        "highly automated",
        "geographically distributed",
    ]

    lowered = text.lower()

    for descriptor in descriptors:
        if descriptor in lowered:
            model.append(descriptor)

    locations = []
    evidence = []

    location_patterns = [
        r"manufacturing facilities in\s+(.+?)(?:,\s+we|\.\s+[A-Z]|\n|$)",
        r"manufacturing(?: operations)?[^.]{0,80}?in\s+(?:the\s+)?(.+?)(?:,\s+we|\.\s+[A-Z]|\n|$)",
    ]

    for pattern in location_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        raw = match.group(1)
        raw = (
            raw
            .replace("U.S.", "United States")
            .replace("U.S", "United States")
        )

        for value in _split_list_phrase(raw):
            normalized = value.strip()

            replacements = {
                "U.S.": "United States",
                "U.S": "United States",
                "US": "United States",
                "United States of America": "United States",
            }

            normalized = replacements.get(
                normalized,
                normalized,
            )
            
            if len(normalized.split()) <= 5:
                locations.append(normalized)

        evidence.append(match.group(0))

    critical_assets = []

    for match in re.finditer(
        r"All of our\s+(.+?)\s+are manufactured in our facility in\s+([^.]+)\.",
        text,
        flags=re.IGNORECASE,
    ):
        asset = match.group(1).strip()

        if asset.endswith("chips"):
            asset = asset[:-1]

        elif asset.endswith("s") and not asset.endswith("ss"):
            asset = asset[:-1]

        critical_assets.append(
            {
                "asset": f"{asset} manufacturing",
                "location": match.group(2).strip(),
            }
        )
        evidence.append(match.group(0))

    return {
        "model": _dedupe(model),
        "locations": _dedupe(locations),
        "critical_assets": critical_assets,
    }, evidence


def _extract_customer_types(
    text: str,
) -> tuple[list[str], list[str]]:
    customers = []
    evidence = []

    patterns = [
        r"customers in this market are generally\s+(.+?)\.",
        r"customers in this segment consist mostly of\s+(.+?)\.",
        r"our customers include\s+(.+?)\.",
        r"direct customers include\s+(.+?)\.",
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            phrase = match.group(1)

            customers.extend(
                _split_list_phrase(phrase)
            )
            evidence.append(match.group(0))

    return _dedupe(customers), evidence


def _extract_ai_exposure(
    text: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    candidates = []

    for sentence in _sentences(text):
        lower = sentence.lower()

        if (
            ("artificial intelligence" in lower or re.search(r"\bAI\b", sentence))
            and any(
                token in lower
                for token in (
                    "demand",
                    "investment",
                    "build",
                    "upgrade",
                    "growth",
                    "opportunity",
                    "bandwidth",
                    "compute",
                )
            )
        ):
            score = 0

            if re.search(r"800\s*gbps", sentence, re.IGNORECASE):
                score += 5
            if "bandwidth" in lower:
                score += 2
            if "data center" in lower:
                score += 2
            if "demand" in lower:
                score += 1
            if "investment" in lower:
                score += 1

            candidates.append(
                (score, sentence)
            )

    if not candidates:
        return None, []

    candidates.sort(
        key=lambda row: (-row[0], -len(row[1]))
    )

    summary = candidates[0][1]

    # Normalize speed notation for stable API presentation.
    summary = re.sub(
        r"(\d+)\s+Gbps",
        r"\1Gbps",
        summary,
        flags=re.IGNORECASE,
    )

    return {
        "type": "direct_company_disclosure",
        "summary": summary,
    }, [candidates[0][1]]


def _extract_competitive_advantages(
    text: str,
) -> tuple[list[str], list[str]]:
    match = re.search(
        r"\nOur Strengths\s*\n(.*?)(?:\nOur Strategy\s*\n|\nBusiness Strategies\s*\n|\Z)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return [], []

    section = match.group(1)
    parts = re.split(r"\n[-•\-]\s*\n?", section)

    strengths = []

    for part in parts:
        sentences = _sentences(part)

        if not sentences:
            continue

        first = sentences[0].strip()

        if len(first) <= 280:
            strengths.append(first)

    return _dedupe(strengths), [section[:5000]]


def _extract_surface_demand_drivers(
    text: str,
) -> tuple[list[str], list[str]]:
    # These are literal surface mentions, not ontology mappings.
    patterns = [
        ("AI", r"\bartificial intelligence\b|\bAI\b"),
        ("DOCSIS 4.0", r"\bDOCSIS\s*4\.0\b"),
        ("5G", r"\b5G\b"),
        ("PON", r"\bPONs?\b"),
        ("cloud computing", r"\bcloud computing\b"),
        ("bandwidth growth", r"\bbandwidth\b"),
        ("800Gbps+ optical networking", r"\b800\s*Gbps\b"),
        ("HPC", r"\bHPC\b"),
        ("generative AI", r"\bgenerative AI\b"),
        ("agentic AI", r"\bagentic AI\b"),
        ("robotics", r"\brobotics\b"),
    ]

    values = []
    evidence = []

    for label, pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        values.append(label)

        start = max(0, match.start() - 160)
        end = min(len(text), match.end() + 220)

        evidence.append(
            re.sub(
                r"\s+",
                " ",
                text[start:end],
            ).strip()
        )

    return values, evidence


def _extract_strategy_changes(
    text: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    changes = []
    evidence = []

    for sentence in _sentences(text):
        match = re.search(
            r"\bIn\s+(20\d{2}),\s+we\s+(?:began|started|launched|introduced|expanded)\s+(.+)",
            sentence,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        if not any(
            token in sentence.lower()
            for token in (
                "direct",
                "brand",
                "launch",
                "introduc",
                "expand",
                "strategy",
                "offering",
                "platform",
            )
        ):
            continue

        brand = None

        brand_match = re.search(
            r"under\s+(.+?)\s+brand name",
            sentence,
            flags=re.IGNORECASE,
        )

        if brand_match:
            brand = (
                brand_match.group(1)
                .replace("™", "")
                .replace("®", "")
                .strip()
            )

        row: dict[str, Any] = {
            "year": int(match.group(1)),
            "change": sentence,
        }

        if brand:
            row["brand"] = brand

        changes.append(row)
        evidence.append(sentence)

    return changes, evidence


def _money_from_text(
    text: str,
    pattern: str,
) -> float | None:
    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return (
        float(match.group(1).replace(",", ""))
        * 1_000_000
    )


def _percent(value: str) -> float:
    return float(value) / 100.0


def _extract_financial_snapshot(
    text: str,
) -> tuple[dict[str, Any], list[str]]:
    evidence = []

    revenue = _money_from_text(
        text,
        r"In 2025, 2024 and 2023, our revenue was \$([\d,.]+) million",
    )

    gross_match = re.search(
        r"our gross margin was ([\d.]+)%",
        text,
        flags=re.IGNORECASE,
    )

    loss = _money_from_text(
        text,
        r"we had net loss of \$([\d,.]+) million",
    )

    revenue_mix: dict[str, float] = {}

    mix_match = re.search(
        r"earned\s+([\d.]+)% of our total revenue from the\s+(.+?)\s+market"
        r"\s+and\s+([\d.]+)% of our total revenue from the\s+(.+?)\s+market",
        text,
        flags=re.IGNORECASE,
    )

    if mix_match:
        market_1 = _canonical_market_label(
            mix_match.group(2)
        )
        market_2 = _canonical_market_label(
            mix_match.group(4)
        )

        revenue_mix[market_1] = _percent(
            mix_match.group(1)
        )
        revenue_mix[market_2] = _percent(
            mix_match.group(3)
        )

        evidence.append(mix_match.group(0))

    customer_concentration: dict[str, float] = {}

    concentration_pattern = re.compile(
        r"In 2025,\s*2024,?\s*and\s*2023,\s*"
        r"([A-Z][A-Za-z0-9&.' -]+?)\s+"
        r"accounted for\s+([\d.]+)%",
        flags=re.IGNORECASE,
    )

    for match in concentration_pattern.finditer(text):
        name = match.group(1).strip()

        if name.lower() in {
            "we",
            "the company",
        }:
            continue

        customer_concentration[name] = _percent(
            match.group(2)
        )
        evidence.append(match.group(0))

    financial_sentence = re.search(
        r"In 2025, 2024 and 2023, our revenue was \$[\d,.]+ million.*?"
        r"respectively\.",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if financial_sentence:
        evidence.append(
            financial_sentence.group(0)
        )

    return {
        "fiscal_year": 2025,
        "revenue": revenue,
        "gross_margin": (
            _percent(gross_match.group(1))
            if gross_match
            else None
        ),
        "net_loss": loss,
        "revenue_mix": revenue_mix,
        "customer_concentration": customer_concentration,
    }, evidence


def _evidence_metadata(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "business_evidence_id":
            evidence["business_evidence_id"],
        "form": evidence.get("form"),
        "accession_number":
            evidence.get("accession_number"),
        "filing_date":
            evidence.get("filing_date"),
        "section_type":
            evidence.get("section_type"),
        "document_url":
            evidence.get("document_url"),
        "text_sha256":
            evidence.get("text_sha256"),
    }


def build_company_profile_v2(
    root: Path,
    *,
    symbol: str,
) -> dict[str, Any]:
    security = _find_security(
        root,
        symbol,
    )

    company_id = str(
        security["company_id"]
    )

    evidence_rows = _load_business_evidence(
        root,
        company_id,
    )

    evidence = _latest_business_evidence(
        evidence_rows,
        symbol,
    )

    text = _clean_text(
        evidence["text"]
    )

    one_line, one_line_evidence = (
        _extract_one_line_business(text)
    )

    markets, markets_evidence = (
        _extract_markets(text)
    )

    product_stack, product_stack_evidence = (
        _extract_product_stack(text)
    )

    market_products, market_products_evidence = (
        _extract_market_products(
            text,
            markets,
        )
    )

    technologies, technologies_evidence = (
        _extract_core_technologies(text)
    )

    manufacturing, manufacturing_evidence = (
        _extract_manufacturing(text)
    )

    customer_types, customer_evidence = (
        _extract_customer_types(text)
    )

    ai_exposure, ai_evidence = (
        _extract_ai_exposure(text)
    )

    competitive_advantages, strengths_evidence = (
        _extract_competitive_advantages(text)
    )

    demand_drivers, demand_evidence = (
        _extract_surface_demand_drivers(text)
    )

    strategy_changes, strategy_evidence = (
        _extract_strategy_changes(text)
    )

    financial_snapshot, financial_evidence = (
        _extract_financial_snapshot(text)
    )

    field_evidence = {
        "company_summary.one_line_business":
            [one_line_evidence]
            if one_line_evidence else [],
        "markets":
            markets_evidence,
        "product_stack":
            product_stack_evidence,
        "market_products":
            market_products_evidence,
        "core_technologies":
            technologies_evidence,
        "manufacturing":
            manufacturing_evidence,
        "customer_types":
            customer_evidence,
        "ai_exposure":
            ai_evidence,
        "competitive_advantages":
            strengths_evidence,
        "demand_drivers":
            demand_evidence,
        "strategy_changes":
            strategy_evidence,
        "financial_snapshot":
            financial_evidence,
    }

    return {
        "schema_version":
            "axiom-company-profile.v2.1",
        "generation_mode":
            "evidence_first_generic_extractor",

        "company_id":
            company_id,
        "symbol":
            symbol.upper(),
        "exchange":
            security.get("exchange"),
        "as_of":
            evidence.get("filing_date"),

        "company_summary": {
            "one_line_business":
                one_line,
        },

        "markets":
            markets,

        "product_stack":
            product_stack,

        "market_products":
            market_products,

        "core_technologies":
            technologies,

        "manufacturing":
            manufacturing,

        "customer_types":
            customer_types,

        "ai_exposure":
            ai_exposure,

        "competitive_advantages":
            competitive_advantages,

        "demand_drivers":
            demand_drivers,

        "strategy_changes":
            strategy_changes,

        "financial_snapshot":
            financial_snapshot,

        "field_evidence":
            field_evidence,

        "evidence": [
            _evidence_metadata(evidence)
        ],
    }
