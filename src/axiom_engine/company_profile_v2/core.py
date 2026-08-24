from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from .provenance import build_value_provenance


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
    supported_business_sections = {
        "item_1_business",
        "item_4_company_information",
    }

    candidates = [
        row
        for row in rows
        if row.get("section_type") in supported_business_sections
        and isinstance(row.get("text"), str)
        and row["text"].strip()
    ]

    if not candidates:
        raise CompanyProfileV2Error(
            f"no supported business section for {symbol}"
        )

    return max(
        candidates,
        key=lambda row: str(row.get("filing_date") or ""),
    )


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
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
        "data centers": "Data Center",
        "automotive aftermarket": "Automotive Aftermarket",
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
            r"^(?:a|an|the|our|their|including)\s+",
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
                for sentence in sentences:
                    if re.search(
                        r"\b(?:is|are)\s+(?:a|an)\s+[^.]{0,140}\b"
                        r"(?:company|producer|provider|supplier|manufacturer)\b",
                        sentence,
                        flags=re.IGNORECASE,
                    ):
                        return sentence, candidate
                return sentences[0], candidate

    sentences = _sentences(text)

    # Prefer an explicit company identity/business-model sentence before the
    # broad fallback below. This avoids strategy, liquidity, and section prose
    # that merely happens to contain "provides" or another weak marker.
    for sentence in sentences:
        normalized = re.sub(
            r"^(?:(?:BUSINESS|GENERAL|OVERVIEW OF OUR BUSINESS)"
            r"[\s\u200b]*[.:]?[\s\u200b]*)+",
            "",
            sentence,
            flags=re.IGNORECASE,
        ).strip()
        lower = normalized.lower()

        identity_relation = re.search(
            r"\b(?:is|are)\s+(?:a|an)\s+[^.]{0,120}\b"
            r"(?:company|provider|supplier|manufacturer)\b",
            normalized,
            flags=re.IGNORECASE,
        )
        operating_relation = re.search(
            r"\b(?:designs?|manufactures?|services?|develops?|provides?)\b"
            r"[^.]{0,160}\b(?:equipment|products?|solutions?|systems?)\b",
            normalized,
            flags=re.IGNORECASE,
        )

        if (
            (identity_relation or operating_relation)
            and not re.search(
                r"\b(?:cash flows?|cash balance|capital to fund|"
                r"compensation|employees?|benefits?)\b",
                lower,
            )
        ):
            return normalized, sentence

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

# === V2.6.3 GENERIC MARKET / END-MARKET EXTRACTION ===

_MARKET_BLOCKED_EXACT = {
    "united states",
    "u.s.",
    "us",
    "china",
    "japan",
    "india",
    "canada",
    "mexico",
    "europe",
    "asia",
    "australia",
    "south america",
    "north america",
    "latin america",
    "central america",
    "caribbean",
    "south korea",
    "new zealand",

    "markets",
    "market",
    "industries",
    "industry",
    "applications",
    "application",
    "customers",
    "customer",
    "products",
    "services",
    "solutions",
    "business",
    "target",
    "large",
    "diverse",
    "digitization",
    "and other",
    "other",
    "field",
}

_MARKET_BLOCKED_PREFIXES = (
    "our products",
    "our services",
    "our customers",
    "customers include",
    "customers such as",
    "we sell",
    "we offer",
    "we provide",
    "we manufacture",
    "we develop",
    "we design",
    "demand for",
    "growth in",
    "increase in",
    "investment in",
)

_MARKET_BLOCKED_CONTAINS = (
    " distributors",
    " retailers",
    " resellers",
    " sales representatives",
    " channel partners",
    " employees",
    " suppliers",
    " revenue",
    " gross margin",
    " operating income",
)

# === V2.6.3.1 MARKET CONTEXT GUARD ===

_MARKET_NON_MARKET_EXACT = {
    # Generic fragments / actors
    "diverse",
    "partners",
    "partner",
    "developers",
    "developer",

    # Product / technology nouns
    "cpu",
    "cpus",
    "gpu",
    "gpus",
    "cuda",
    "dram",
    "nand",
    "hbm",
    "dimm",
    "dimms",
    "memory modules",
}

_MARKET_PRODUCT_TERMS = (
    " cpu",
    " cpus",
    " gpu",
    " gpus",
    " cuda",
    " dram",
    " nand",
    " hbm",
    " dimm",
    " dimms",
    " memory module",
    " memory modules",
    " semiconductor",
    " semiconductors",
    " processor",
    " processors",
    " chipset",
    " chipsets",
    " accelerator",
    " accelerators",
    " software",
    " hardware",
)

_MARKET_PRODUCT_SUFFIXES = (
    " module",
    " modules",
    " solution",
    " solutions",
    " product",
    " products",
    " technology",
    " technologies",
    " platform",
    " platforms",
)

_MARKET_FRAGMENT_PREFIXES = (
    "driven by ",
    "by ",
    "from ",
    "through ",
    "using ",
    "based on ",
    "enabled by ",
    "supported by ",
)

_MARKET_FRAGMENT_CONTAINS = (
    " third-party ",
    " third party ",
    " fundamental building blocks",
    " demand across ",
    " demand for ",
)


# === V2.6.3.4.1 TIER 2 SEMANTIC CLEANUP ===

_MARKET_TIER2_BLOCKED_EXACT = {
    # Demonstratives / fragments
    "this",
    "that",
    "these",
    "those",
    "other",
    "others",
    "end",

    # Competitive-factor / commercial-noise nouns
    "cost position",
    "price",
    "quality",
    "reliability of bauxite supply",
    "proximity to customers",
    "design",
    "test",
    "measurement",
    "emulation",
    "prototyping",

    # Product / technology nouns that appeared in Tier 2 smoke
    "laptop pcs",
    "pcs",
    "socs",
    "audio",
    "video",

    # V2.6.3.4.2 observed entity / fragment pollution
    "rio tinto",
    "both the professional",
    "vision",
}

_MARKET_TIER2_BLOCKED_PREFIXES = (
    "a very wide range of",
    "wide range of",
    "a provider of",
    "provider of",
    "development services for",
    "services for",
    "among other",
    "including other",
)

_MARKET_TIER2_BLOCKED_CONTAINS = (
    " game consoles",
    " cloud gaming service",
    " cloud gaming services",
    " development services",
    " optical products",
    " test equipment",
    " communications test",
    " processing capabilities",
    " integrated ai processing capabilities",
)

_MARKET_TIER2_GEOGRAPHY_TERMS = (
    "brazil",
    "united states",
    "u.s.",
    "usa",
    "canada",
    "mexico",
    "china",
    "japan",
    "south korea",
    "new zealand",
    "india",
    "australia",
    "europe",
    "asia",
    "north america",
    "south america",
    "latin america",
    "central america",
    "caribbean",
    "middle east",
    "africa",
)


def _clean_market_candidate(
    value: str,
) -> str:
    value = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip(" ,.;:-")

    value = re.sub(
        r"^(?:"
        r"the |our |global |worldwide |"
        r"large |major |primary |principal |"
        r"key |target |served "
        r")",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"\s+(?:"
        r"end[- ]markets?|markets?|industries|"
        r"industry|sectors?|verticals?"
        r")$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip(" ,.;:-")

    return value


def _market_candidate_allowed(
    value: str,
) -> bool:
    candidate = _clean_market_candidate(
        value
    )

    if not candidate:
        return False

    lower = candidate.casefold()

    # Existing V2.6.3 hard rejects.
    if lower in _MARKET_BLOCKED_EXACT:
        return False

    # V2.6.3.1:
    # reject generic actors, technologies,
    # products and obvious prose fragments.
    if lower in _MARKET_NON_MARKET_EXACT:
        return False

    if lower.startswith(
        _MARKET_FRAGMENT_PREFIXES
    ):
        return False

    padded = f" {lower} "

    if any(
        fragment in padded
        for fragment in _MARKET_FRAGMENT_CONTAINS
    ):
        return False

    if lower.endswith(
        _MARKET_PRODUCT_SUFFIXES
    ):
        return False

    if any(
        product_term in padded
        for product_term in _MARKET_PRODUCT_TERMS
    ):
        return False

    # Existing V2.6.3 contextual rejects.
    if lower.startswith(
        _MARKET_BLOCKED_PREFIXES
    ):
        return False

    if any(
        blocked in padded
        for blocked in _MARKET_BLOCKED_CONTAINS
    ):
        return False

    # Avoid long prose fragments.
    if len(candidate.split()) > 8:
        return False

    if re.search(
        r"\b(?:"
        r"we|our|which|that|who|"
        r"because|while|where|when"
        r")\b",
        lower,
    ):
        return False

    if re.search(
        r"^(?:"
        r"is|are|was|were|"
        r"providing|serving|selling|"
        r"used|using|supporting"
        r")\b",
        lower,
    ):
        return False

    # V2.6.3.4 Tier 2 semantic guard.
    # These are actors/channels/geographies/demand/product technology,
    # not external end markets.
    if re.search(
        r"\b(?:"
        r"oems?|distributors?|resellers?|retailers?|"
        r"channel partners?|sales representatives?|"
        r"employees?|workforce|"
        r"united states|south korea|new zealand|"
        r"north america|latin america|asia pacific|"
        r"europe|china|japan|"
        r"demand|growth|investment|bandwidth|"
        r"cpus?|gpus?|cuda|dram|nand|hbm|dimms?|"
        r"processors?|chipsets?|semiconductors?"
        r")\b",
        lower,
    ):
        return False

    # V2.6.3.4.1 Tier 2 semantic cleanup.
    if lower in _MARKET_TIER2_BLOCKED_EXACT:
        return False

    if lower.startswith(
        _MARKET_TIER2_BLOCKED_PREFIXES
    ):
        return False

    padded_tier2 = f" {lower} "

    if any(
        blocked in padded_tier2
        for blocked in _MARKET_TIER2_BLOCKED_CONTAINS
    ):
        return False

    # Reject geography-only candidates. We intentionally do not reject
    # phrases merely because they contain a geographic adjective in a
    # legitimate external market name; the exact candidate must match
    # the geography term.
    if lower in _MARKET_TIER2_GEOGRAPHY_TERMS:
        return False

    # Reject obvious trailing prose fragments left by broad Tier 2
    # sentence captures.
    if re.search(
        r"\b(?:"
        r"among other countries|"
        r"rely on our products|"
        r"as the fundamental building blocks"
        r")$",
        lower,
    ):
        return False

    return True


def _split_market_phrase(
    value: str,
) -> list[str]:
    value = re.sub(
        r"\([^)]{0,80}\)",
        "",
        value,
    )

    value = value.replace(
        ";",
        ",",
    )

    value = re.sub(
        r"\s+as well as\s+",
        ", ",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"\s+(?:and|or)\s+",
        ", ",
        value,
        flags=re.IGNORECASE,
    )

    output = []

    for raw in value.split(","):
        raw = re.sub(
            r"^\s*(?:and|or)\s+",
            "",
            raw,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(
            r"^(?:including|such as)(?:\s+but\s+not\s+limited\s+to"
            r"(?:\s+the\s+following)?)?\s+",
            "",
            raw.strip(),
            flags=re.IGNORECASE,
        )
        candidate = re.sub(
            r"^but\s+not\s+limited\s+to(?:\s+the\s+following)?\s*:\s*",
            "",
            candidate,
            flags=re.IGNORECASE,
        )

        candidate = re.sub(
            r"^(?:"
            r"this|that|these|those|"
            r"among other countries|"
            r"a very wide range of"
            r")\s*",
            "",
            candidate,
            flags=re.IGNORECASE,
        )

        candidate = _clean_market_candidate(
            candidate
        )

        if re.search(
            r"\b(?:new\s+construction|renovation|retrofit)\b",
            candidate,
            flags=re.IGNORECASE,
        ):
            continue

        # V2.6.3.4.2: collapse audience/channel framing
        # around the actual external market.
        if re.search(
            r"\bautomotive aftermarket\b",
            candidate,
            flags=re.IGNORECASE,
        ):
            candidate = "Automotive Aftermarket"

        if not _market_candidate_allowed(
            candidate
        ):
            continue

        output.append(
            _canonical_market_label(
                candidate
            )
        )

    return _dedupe(output)


def _extract_generic_markets(
    text: str,
) -> tuple[list[str], list[str]]:
    markets: list[str] = []
    evidence: list[str] = []

    patterns = [
        # ---------------------------------
        # V2.6.3 baseline explicit wording
        # ---------------------------------
        r"\bour end[- ]markets?\s+(?:include|includes|are|consist of)\s+(.+?)(?:\.|;)",
        r"\bend[- ]markets?\s+(?:include|includes|are|consist of)\s+(.+?)(?:\.|;)",
        r"\btarget markets?\s+(?:include|includes|are|consist of)\s+(.+?)(?:\.|;)",
        r"\bserved markets?\s+(?:include|includes|are|consist of)\s+(.+?)(?:\.|;)",

        r"\bmarkets? we serve\s+(?:include|includes|are|consist of)\s+(.+?)(?:\.|;)",
        r"\bindustries we serve\s+(?:include|includes|are|consist of)\s+(.+?)(?:\.|;)",
        r"\bserved industries\s+(?:include|includes|are|consist of)\s+(.+?)(?:\.|;)",
        r"\bverticals we serve\s+(?:include|includes|are|consist of)\s+(.+?)(?:\.|;)",

        r"\bwe serve\s+(?:customers in\s+)?(?:the\s+)?(.+?)\s+industr(?:y|ies)(?:\.|;)",
        r"\bwe serve\s+(?:the\s+)?(.+?)\s+markets?(?:\.|;)",
        r"\bwe operate in\s+(?:the\s+)?(.+?)\s+markets?(?:\.|;)",
        r"\bwe participate in\s+(?:the\s+)?(.+?)\s+markets?(?:\.|;)",

        r"\bour products are used in\s+(.+?)\s+applications?(?:\.|;)",
        r"\bour products serve\s+(.+?)\s+applications?(?:\.|;)",

        # ---------------------------------
        # V2.6.3.3 Tier 1 recall promotion
        # Low-risk census families only:
        # explicit_end_market
        # serve_industry_market
        # market_list
        # industry_list
        # ---------------------------------

        # Explicit primary / principal market disclosure.
        r"\bprimary markets?\s+(?:include|includes|are|consist of)\s+(.+?)(?:\.|;)",
        r"\bprincipal markets?\s+(?:include|includes|are|consist of)\s+(.+?)(?:\.|;)",

        # Generic but explicit market lists.
        r"\bmarkets?\s+(?:include|includes|consist of)\s+(.+?)(?:\.|;)",
        r"\bmarkets?\s+such as\s+(.+?)(?:\.|;)",
        r"\bmarket segments?\s+(?:include|includes|consist of)\s+(.+?)(?:\.|;)",
        r"\bmarket sectors?\s+(?:include|includes|consist of)\s+(.+?)(?:\.|;)",

        # Generic but explicit industry / sector / vertical lists.
        r"\bindustries\s+(?:include|includes|consist of)\s+(.+?)(?:\.|;)",
        r"\bindustries\s+such as\s+(.+?)(?:\.|;)",
        r"\bindustry sectors?\s+(?:include|includes|consist of)\s+(.+?)(?:\.|;)",
        r"\bsectors?\s+(?:include|includes|consist of)\s+(.+?)(?:\.|;)",
        r"\bverticals?\s+(?:include|includes|consist of)\s+(.+?)(?:\.|;)",

        # Company-served industries / sectors / verticals.
        # Keep the capture bounded by the explicit industry head noun.
        r"\b(?:serve|serves|served|serving)\s+(?:customers?\s+in\s+)?(?:the\s+)?(.+?)\s+industr(?:y|ies)(?:\.|;)",
        r"\b(?:serve|serves|served|serving)\s+(?:customers?\s+in\s+)?(?:the\s+)?(.+?)\s+sectors?(?:\.|;)",
        r"\b(?:serve|serves|served|serving)\s+(?:customers?\s+in\s+)?(?:the\s+)?(.+?)\s+verticals?(?:\.|;)",

        # ---------------------------------
        # V2.6.3.4 Tier 2 recall promotion
        # Guarded census families:
        # customer_industry_context
        # participate_operate
        # sold_into_deployed
        # ---------------------------------

        # Customer industry / market context.
        r"\bcustomers?\s+in\s+(?:the\s+)?(.+?)\s+(?:markets?|industr(?:y|ies)|sectors?|verticals?)\b",
        r"\bcustomer base\s+(?:includes|include|consists of|is concentrated in)\s+(?:the\s+)?(.+?)\s+(?:markets?|industr(?:y|ies)|sectors?|verticals?)\b",

        # Participation / operation explicitly bounded by a market noun.
        r"\b(?:we|the company)\s+(?:participate|participates|participated|participating)\s+in\s+(?:the\s+)?(.+?)\s+markets?(?:\.|;)",
        r"\b(?:we|the company)\s+(?:operate|operates|operated|operating)\s+in\s+(?:the\s+)?(.+?)\s+(?:markets?|industr(?:y|ies)|sectors?|verticals?)(?:\.|;)",

        # Sold/deployed/used into explicitly named external markets,
        # industries, sectors or verticals. Do not promote bare channel
        # or geography statements.
        r"\b(?:our products|our solutions|our services|products|solutions|services)\s+(?:are\s+)?sold into\s+(?:the\s+)?(.+?)\s+(?:markets?|industr(?:y|ies)|sectors?|verticals?)(?:\.|;)",
        r"\b(?:our products|our solutions|our services|products|solutions|services)\s+(?:are\s+)?deployed (?:in|across)\s+(?:the\s+)?(.+?)\s+(?:markets?|industr(?:y|ies)|sectors?|verticals?)(?:\.|;)",
        r"\b(?:our products|our solutions|our services|products|solutions|services)\s+(?:are\s+)?used across\s+(?:the\s+)?(.+?)\s+(?:markets?|industr(?:y|ies)|sectors?|verticals?)(?:\.|;)",
    ]

    for sentence in _sentences(text):
        lower = sentence.lower()

        if any(
            blocked in lower
            for blocked in (
                "geographic market",
                "geographic markets",
                "sales offices",
                "employees",
                "compensation",
                "benefits",
                "risk factors",

                # V2.6.3.3 Tier 1:
                # do not confuse internal reportable/business
                # segment lists with external end markets.
                "reportable segment",
                "reportable segments",
                "operating segment",
                "operating segments",
                "business segment",
                "business segments",
                "segment reporting",

                # V2.6.3.4 Tier 2 context guard:
                # reject channel/customer-type, geography, demand,
                # employee and obvious product-technology sentences
                # before candidate splitting.
                "sold through",
                "distributed through",
                "distribution partners",
                "channel partners",
                "sales representatives",
                "employees",
                "workforce",
                "compensation",
                "benefits",
            )
        ):
            continue

        # Market lists must describe a company-to-end-market relation.  A
        # competitive-factor list merely happens to occur near the word
        # "market", and an organization may serve an industry's supply chain
        # without that industry being a market served by the company.
        if re.search(
            r"\b(?:significant\s+)?competitive\s+(?:factors?|criteria)\b",
            sentence,
            flags=re.IGNORECASE,
        ):
            continue

        for pattern in patterns:
            for match in re.finditer(
                pattern,
                sentence,
                flags=re.IGNORECASE,
            ):
                prefix = sentence[max(0, match.start() - 120):match.start()]
                captured = match.group(1)

                if re.search(
                    r"\b(?:large|diverse)\b.*\b(?:experiencing|tailwinds?)\b",
                    captured,
                    flags=re.IGNORECASE,
                ):
                    continue

                if (
                    re.search(
                        r"\b(?:organization|association|consortium|alliance|"
                        r"council|society|institute|foundation)\s*$",
                        prefix,
                        flags=re.IGNORECASE,
                    )
                    and re.search(
                        r"\b(?:manufacturing\s+)?supply\s+chain\b",
                        captured,
                        flags=re.IGNORECASE,
                    )
                ):
                    continue

                candidates = _split_market_phrase(
                    captured
                )

                if not candidates:
                    continue

                markets.extend(candidates)

                evidence.append(
                    re.sub(
                        r"\s+",
                        " ",
                        match.group(0),
                    ).strip()
                )

    return (
        _dedupe(markets),
        _dedupe(evidence),
    )

def _extract_markets(
    text: str,
) -> tuple[list[str], list[str]]:
    markets: list[str] = []
    evidence: list[str] = []

    # V2.6.3 generic market extraction.
    generic_markets, generic_evidence = (
        _extract_generic_markets(
            text
        )
    )

    markets.extend(
        generic_markets
    )
    evidence.extend(
        generic_evidence
    )

    # A strongly owned "we design/develop our products for ... end markets"
    # disclosure is safe even when a market label (for example, Storage and
    # Computing) contains a word that the broader market gate conservatively
    # treats as product-like.
    explicit_product_market_re = re.compile(
        r"\b(?:we|the company)\s+(?:design(?:s)?(?:\s+and\s+develop(?:s)?)?|"
        r"develop(?:s)?)\s+(?:our\s+)?products?\s+for\s+(?:the\s+)?"
        r"(.+?)\s+end[- ]markets?(?:\.|;)",
        flags=re.IGNORECASE,
    )
    for sentence in _sentences(text):
        for match in explicit_product_market_re.finditer(sentence):
            # Commas delimit the disclosed markets.  Preserve an internal
            # conjunction such as "storage and computing".
            for raw in match.group(1).split(","):
                candidate = re.sub(
                    r"^\s*and\s+",
                    "",
                    raw,
                    flags=re.IGNORECASE,
                ).strip(" ,.;:-")
                if (
                    candidate
                    and len(candidate.split()) <= 5
                    and candidate.casefold() not in _MARKET_BLOCKED_EXACT
                    and not re.search(
                        r"\b(?:distributors?|resellers?|channel partners?|"
                        r"customers?|employees?)\b",
                        candidate,
                        flags=re.IGNORECASE,
                    )
                ):
                    markets.append(_canonical_market_label(candidate))
                    evidence.append(match.group(0))

    explicit_industry_relation_re = re.compile(
        r"\bour\s+[^.]{1,100}?\b(?:products?|lasers?|systems?|solutions?)\s+"
        r"(?:cater|caters)\s+to\s+industries\s+such\s+as\s+(.+?)(?:,\s*where|\.|;)",
        flags=re.IGNORECASE,
    )
    for sentence in _sentences(text):
        for match in explicit_industry_relation_re.finditer(sentence):
            for raw in re.split(r",|\s+and\s+", match.group(1)):
                candidate = raw.strip(" ,.;:-")
                if (
                    candidate
                    and len(candidate.split()) <= 6
                    and candidate.casefold() not in _MARKET_BLOCKED_EXACT
                    and not re.search(
                        r"\b(?:distributors?|resellers?|channel partners?|"
                        r"customers?|employees?)\b",
                        candidate,
                        flags=re.IGNORECASE,
                    )
                ):
                    markets.append(_canonical_market_label(candidate))
                    evidence.append(match.group(0))

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

        pieces = (
            re.split(r",\s*(?=[A-Za-z])", phrase)
            if "," in phrase
            else re.split(r"\s+and\s+", phrase, flags=re.IGNORECASE)
        )

        for piece in pieces:
            piece = re.sub(
                r"^\s*(?:and|or)\s+",
                "",
                piece,
                flags=re.IGNORECASE,
            ).strip()

            if not piece:
                continue

            label = _canonical_market_label(piece)

            explicit_head = pattern.startswith(
                r"(?:networking\s+)?end[- ]markets?"
            )
            if (
                label
                and len(label) <= 50
                and (
                    _market_candidate_allowed(label)
                    or (
                        explicit_head
                        and label.casefold() not in _MARKET_BLOCKED_EXACT
                        and len(label.split()) <= 5
                    )
                )
            ):
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

    return (
        _dedupe(markets),
        _dedupe(evidence),
    )


def _clean_offering_phrase(
    value: str,
) -> str:
    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip(
        " ,.;:-"
    )

    value = re.sub(
        r"^(?:"
        r"a |an |the |our |"
        r"a range of |"
        r"a broad range of |"
        r"a broad portfolio of |"
        r"a portfolio of |"
        r"a variety of |"
        r"various |"
        r"multiple "
        r")",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^(?:products?|services?|solutions?|offerings?)\s+"
        r"(?:including|include|consisting of|consist of)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return value.strip(
        " ,.;:-"
    )


def _valid_offering(
    value: str,
) -> bool:
    value = _clean_offering_phrase(
        value
    )

    if not value:
        return False

    words = value.split()

    if (
        len(words) < 1
        or len(words) > 10
    ):
        return False

    lower = value.lower()

    blocked_exact = {
        "products",
        "product",
        "services",
        "service",
        "solutions",
        "solution",
        "offerings",
        "offering",
        "platform",
        "platforms",
        "technology",
        "technologies",
        "customers",
        "markets",
        "businesses",
        "business",
        "operations",
        "capabilities",
    }

    if lower in blocked_exact:
        return False

    blocked_phrases = (
        "our customers",
        "our business",
        "our market",
        "our markets",
        "our operations",
        "our strategy",
        "our employees",
        "our facilities",
        "our intellectual property",
        "research and development",
        "sales and marketing",
        "general and administrative",
        "manufacturing costs",
        "operating expenses",
        "competitive advantage",
        "customer demand",
        "market demand",
        "supply chain",
        "raw materials",
        "working capital",
        "cash flows",
        "capital expenditures",
    )

    if any(
        phrase in lower
        for phrase in blocked_phrases
    ):
        return False

    # Avoid collecting complete prose clauses
    # as product names.
    clause_tokens = (
        " we ",
        " our ",
        " which ",
        " that ",
        " because ",
        " while ",
        " where ",
        " when ",
    )

    padded = (
        " "
        + lower
        + " "
    )

    if any(
        token in padded
        for token in clause_tokens
    ):
        return False

    return True

def _offering_context_allowed(
    text: str,
) -> bool:
    """
    V2.6.2.1 context gate.

    Accept only sentences/clauses that are
    plausibly describing products, services,
    platforms, systems, solutions, or what the
    company commercially provides.

    Reject HR, investor relations, distribution,
    warranty, ESG and other non-offering prose.
    """

    lower = re.sub(
        r"\s+",
        " ",
        text,
    ).strip().lower()

    if not lower:
        return False

    blocked_context = (
        # Employees / HR / benefits
        "employee assistance",
        "employees with",
        "employee benefits",
        "team members",
        "mental health",
        "counseling",
        "fitness center",
        "wellness",
        "healthy habits",
        "financial education",
        "career development",
        "advance their careers",
        "competitive salaries",
        "equity ownership",

        # Investor relations / SEC
        "sec filing",
        "sec filings",
        "investor event",
        "investor events",
        "press release",
        "press releases",
        "earnings release",
        "earnings releases",
        "notifications of news",

        # Competitor/entity lists are not company offerings even when their
        # grammar contains "our products include".
        "principal competitors",
        "competitors with respect to our products",

        # Product mentions inside trade-control and regulatory obligations
        # describe legal scope, not commercial offerings.
        "subject to laws and regulations",
        "export controls and sanctions laws",
        "customs regulations",

        # ESG / volunteering
        "company-matched donations",
        "matched donations",
        "volunteering",
        "volunteer their time",
        "community engagement",

        # Distribution / channel
        "direct sales force",
        "independent distributors",
        "through distributors",
        "distribution partners",
        "sales representatives",
        "manufacturers' representatives",
        "manufacturer representatives",
        "channel partners",
        "direct marketing",
        "co-marketing",
        "electronic commerce",
        "web-based customer-direct sales channel",

        # Warranty / support terms
        "limited warranties",
        "warranty",
        "three-year",
        "support program",

        # Corporate boilerplate
        "our employees",
        "our people",
        "human capital",
        "compensation",
        "benefits program",
        "corporate governance",
        "risk factors",
        "intellectual property protection",

        "major end markets",
        "end markets:",
        "markets we serve",
        "geographic markets",
    )

    if any(
        phrase in lower
        for phrase in blocked_context
    ):
        return False

    # Strong positive commercial context.
    positive_context = (
        "our products",
        "our services",
        "our solutions",
        "our offerings",
        "our portfolio",
        "our platform",
        "our platforms",
        "our systems",
        "we offer",
        "we provide",
        "we sell",
        "we manufacture",
        "we develop",
        "we design",
        "we market",
        "products include",
        "services include",
        "solutions include",
        "offerings include",
        "portfolio includes",
        "platform consists of",
        "platform includes",
        "systems include",
        "principal products",
        "product lines",
        "product families",
    )

    return any(
        phrase in lower
        for phrase in positive_context
    )

_SINGLE_TOKEN_OFFERING_NOUNS = {
    "software",
    "hardware",
    "instruments",
    "consumables",
    "reagents",
    "kits",
    "filters",
    "components",
    "modules",
    "wafers",
    "processors",
    "controllers",
    "sensors",
    "transceivers",
    "amplifiers",
    "switches",
    "routers",
    "servers",
    "storage",
    "ssds",

    # V2.6.2.2 common compute/network
    # product nouns.
    "accelerator",
    "accelerators",
    "adapter",
    "adapters",
    "cpu",
    "cpus",
    "gpu",
    "gpus",
    "dpu",
    "dpus",
    "nic",
    "nics",
    "fpga",
    "fpgas",
    "chip",
    "chips",
    "chipset",
    "chipsets",
    "semiconductor",
    "semiconductors",
    "memory",
    "dram",
    "nand",
    "hbm",
}

_FRAGMENT_STARTS = (
    "for ",
    "to ",
    "with ",
    "through ",
    "via ",
    "under ",
    "from ",
    "by ",
    "in ",
    "on ",
    "at ",
    "following ",
    "including ",
    "which ",
    "that ",
    "who ",
)

_FRAGMENT_EXACT = {
    "fast",
    "complete",
    "designed",
    "implemented",
    "simulate",
    "inferencing",
    "write",
    "protect data",
    "mostly",
    "operational",
    "educational",
    "priorities",
    "in 2025",
    "inc",
}

_FRAGMENT_ENDINGS = (
    " end market",
    " end markets",
    " customers",
    " manufacturers",
    " distributors",
    " suppliers",
    " deployments",
    " applications",
    " capabilities",
)

_PRODUCT_HEAD_WORDS = (
    " product",
    " products",
    " service",
    " services",
    " software",
    " hardware",
    " solution",
    " solutions",
    " system",
    " systems",
    " platform",
    " platforms",
    " module",
    " modules",
    " device",
    " devices",
    " processor",
    " processors",
    " accelerator",
    " accelerators",
    " controller",
    " controllers",
    " sensor",
    " sensors",
    " chip",
    " chips",
    " chipset",
    " chipsets",
    " semiconductor",
    " semiconductors",
    " fpga",
    " fpgas",
    " cpu",
    " cpus",
    " gpu",
    " gpus",
    " dpu",
    " dpus",
    " nic",
    " nics",
    " ssd",
    " ssds",
    " memory",
    " nand",
    " dram",
    " hbm",
    " wafer",
    " wafers",
    " filter",
    " filters",
    " transceiver",
    " transceivers",
    " instrument",
    " instruments",
    " consumable",
    " consumables",
    " reagent",
    " reagents",
    " kit",
    " kits",
    " coil",
    " coils",
    " heat pump",
    " heat pumps",
    " unit",
    " units",
)


def _strip_offering_tail(
    value: str,
) -> str:
    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip(" ,.;:-")

    # Cut obvious use/customer/acquisition tails.
    tail_patterns = [
        r"\s+to\s+(?:customers?|aib manufacturers|oems|odms)\b.*$",
        r"\s+for\s+(?:entry level|customers?|use in|use by)\b.*$",
        r"\s+with\s+the acquisition\b.*$",
        r"\s+through\s+(?:distributors|channel partners)\b.*$",
        r"\s+who\s+in turn\b.*$",
        r"\s+which\s+(?:enable|provide|support)\b.*$",
        r"\s+that\s+(?:enable|provide|support)\b.*$",
        r"\s+(?=We\s+(?:design|certify|comply|adhere)\b).*$",
    ]

    for pattern in tail_patterns:
        value = re.sub(
            pattern,
            "",
            value,
            flags=re.IGNORECASE,
        ).strip(" ,.;:-")

    return value


def _looks_like_descriptor_chain(
    parts: list[str],
) -> bool:
    """
    Preserve:
        high-speed,
        high-bandwidth,
        low-latency networking solutions

    as one offering phrase instead of three
    broken candidates.
    """

    if len(parts) < 2:
        return False

    descriptors = parts[:-1]
    final = parts[-1].lower()

    if not any(
        token in f" {final}"
        for token in _PRODUCT_HEAD_WORDS
    ):
        return False

    for raw in descriptors:
        value = raw.strip().lower()

        if not value:
            return False

        words = value.split()

        if len(words) > 3:
            return False

        if not (
            "-" in value
            or value.startswith(
                (
                    "high ",
                    "low ",
                    "ultra ",
                    "advanced ",
                    "secure ",
                    "integrated ",
                )
            )
        ):
            return False

    return True

# === V2.6.2.3 OFFERING SEMANTIC GUARD ===

_NON_OFFERING_EXACT = {
    # Generic / incomplete fragments
    "is action-oriented",
    "two types of platforms",
    "family of high performance",
    "product families with secure",
    "open models",
    "customer experience",

    # Markets / customer groups
    "service provider",
    "service providers",
    "mobility service providers",
    "enterprise networks",
    "storage markets",

    # Geography fragments
    "south america",
    "south korea",
    "new zealand",
    "north america",
    "central america",
    "latin america",
    "europe",
    "asia",
    "china",
    "japan",
    "india",
    "australia",
    "mexico",
    "canada",
    "qatar",
    "caribbean",
}

_NON_OFFERING_PREFIXES = (
    # Action / sentence fragments
    "addressing ",
    "designed ",
    "implemented ",
    "execute ",
    "enabling ",
    "mostly ",
    "directly to ",
    "sold to ",
    "provided to ",
    "used by ",
    "used in ",

    # Customer / market framing
    "customers ",
    "customer ",
    "pharmaceutical customers ",
    "for customers ",
    "for the ",
    "in the ",
    "into the ",
)

_NON_OFFERING_CONTAINS = (
    # Customer groups / channels
    " customers ",
    " customer base",
    " service providers",
    " telcos",
    " distributors",
    " channel partners",
    " manufacturers who",
    " suppliers",

    # Capability rather than offering
    " manufacturing capabilities",
    " technical capabilities",
    " engineering capabilities",
    " expertise",

    # Market / geographic framing
    " end markets",
    " geographic markets",
    " storage markets",
    " market segments",

    # Employment / corporate
    " employees ",
    " team members ",
)

_NON_OFFERING_SUFFIXES = (
    # Clearly incomplete fragments
    " with",
    " with secure",
    " of high performance",
    " to train",
    " to load",

    # Market / customer classes
    " markets",
    " market",
    " customers",
    " providers",
    " suppliers",
    " manufacturers",

    # Capability labels
    " expertise",
    " capabilities",
)

_ACTION_FRAGMENT_RE = re.compile(
    r"^(?:"
    r"is|are|was|were|"
    r"addressing|enabling|executing|"
    r"designed|implemented|providing|"
    r"supporting|helping|allowing|"
    r"used|using"
    r")\b",
    flags=re.IGNORECASE,
)

_GENERIC_QUANTITY_FRAGMENT_RE = re.compile(
    r"^(?:"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten)"
    r"|several|multiple|various"
    r")\s+"
    r"(?:types?|kinds?|families?|categories?)\s+of\b",
    flags=re.IGNORECASE,
)


def _semantic_offering_guard(
    value: str,
) -> bool:
    """
    Final V2.6.2.3 semantic hygiene gate.

    This does not discover new offerings.
    It only rejects candidates that are
    structurally much more likely to be:

    - customers
    - markets
    - geographies
    - capabilities
    - actions
    - incomplete prose fragments
    """

    candidate = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip(" ,.;:-")

    if not candidate:
        return False

    lower = candidate.casefold()

    if lower in _NON_OFFERING_EXACT:
        return False

    if lower.startswith(
        _NON_OFFERING_PREFIXES
    ):
        return False

    if lower.endswith(
        _NON_OFFERING_SUFFIXES
    ):
        return False

    padded = (
        " "
        + lower
        + " "
    )

    if any(
        phrase in padded
        for phrase in _NON_OFFERING_CONTAINS
    ):
        return False

    if _ACTION_FRAGMENT_RE.search(
        candidate
    ):
        return False

    if _GENERIC_QUANTITY_FRAGMENT_RE.search(
        candidate
    ):
        return False

    # Reject sentence fragments ending in
    # weak connective/prepositional words.
    if re.search(
        r"\b(?:"
        r"for|to|with|by|from|via|"
        r"including|such as|"
        r"both|their|our"
        r")$",
        lower,
    ):
        return False

    return True

def _offering_candidate_allowed(
    value: str,
) -> bool:
    candidate = _strip_offering_tail(
        _clean_offering_phrase(
            value
        )
    )
    candidate = re.sub(
        r"^(?:and|or)\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip()

    if not _valid_offering(
        candidate
    ):
        return False

    lower = candidate.lower()

    if lower in _FRAGMENT_EXACT:
        return False

    if lower.startswith(
        _FRAGMENT_STARTS
    ):
        return False

    if lower.endswith(
        _FRAGMENT_ENDINGS
    ):
        return False

    blocked_candidate_phrases = (
        # Sales / distribution
        "distributor",
        "distributors",
        "sales representative",
        "sales representatives",
        "direct sales",
        "sales force",
        "channel partner",
        "channel partners",
        "retailers",
        "resellers",
        "sub distributors",
        "marketing programs",

        # Employees / HR
        "employees",
        "team members",
        "mental health",
        "fitness centers",
        "wellness spaces",
        "health clinics",
        "financial education",
        "career",
        "salaries",
        "bonuses",

        # Investor / SEC
        "sec filings",
        "investor events",
        "press releases",
        "earnings releases",
        "notifications of news",

        # ESG
        "donations",
        "volunteering",

        # Warranty
        "warranties",
        "warranty",

        # Customer populations
        "system integrators",
        "cloud providers",
        "tier-1 suppliers",

        # Corporate-event fragments
        "acquisition of",
        "merger with",

        # Market framing
        "end markets:",
        "major end markets",
    )

    if any(
        phrase in lower
        for phrase in blocked_candidate_phrases
    ):
        return False

    words = candidate.split()

    # A single bare token is dangerous unless
    # it is clearly a product noun.
    if len(words) == 1:
        normalized = lower.strip("()[]{}.,;:")

        if normalized not in _SINGLE_TOKEN_OFFERING_NOUNS:
            # Keep recognizable acronyms/product forms.
            if not (
                re.fullmatch(
                    r"[A-Z0-9-]{2,12}",
                    candidate,
                )
                or normalized.endswith(
                    (
                        "ware",
                        "chip",
                        "chips",
                        "sensor",
                        "sensors",
                        "module",
                        "modules",
                    )
                )
            ):
                return False
    if not _semantic_offering_guard(
        candidate
    ):
        return False
    return True

def _split_offering_phrase(
    value: str,
) -> list[str]:
    value = _strip_offering_tail(
        _clean_offering_phrase(
            value
        )
    )

    value = value.replace(
        ";",
        ",",
    )

    value = re.sub(
        r"\s+as well as\s+",
        ", ",
        value,
        flags=re.IGNORECASE,
    )

    raw_parts = [
        part.strip()
        for part in value.split(",")
        if part.strip()
    ]

    # Preserve adjective chains:
    #
    # high-speed,
    # high-bandwidth,
    # low-latency networking solutions
    #
    if _looks_like_descriptor_chain(
        raw_parts
    ):
        combined = re.sub(
            r"\s+",
            " ",
            ", ".join(raw_parts),
        ).strip()

        return (
            [combined]
            if _offering_candidate_allowed(
                combined
            )
            else []
        )

    # Only normalize the final conjunction when
    # this is already clearly a comma-separated list.
    normalized_parts = []

    for raw in raw_parts:
        subparts = re.split(
            r"\s+(?:and|or)\s+",
            raw,
            maxsplit=1,
            flags=re.IGNORECASE,
        )

        if (
            len(raw_parts) > 1
            and len(subparts) == 2
            and all(
                len(part.split()) <= 8
                for part in subparts
            )
        ):
            normalized_parts.extend(
                subparts
            )
        else:
            normalized_parts.append(
                raw
            )

    output = []

    for raw in normalized_parts:
        candidate = re.sub(
            r"^(?:"
            r"including|"
            r"such as|"
            r"and|"
            r"or"
            r")\s+",
            "",
            raw.strip(),
            flags=re.IGNORECASE,
        )

        candidate = _strip_offering_tail(
            candidate
        )

        if not _offering_candidate_allowed(
            candidate
        ):
            continue

        output.append(
            candidate
        )

    return _dedupe(
        output
    )


def _extract_generic_offerings(
    text: str,
) -> tuple[
    list[str],
    list[str],
]:
    """
    V2.6.2.1 Generic Offering Extraction
    with Offering Context Gate.

    Precision-first:
    - require commercial/product context
    - reject HR / IR / distribution / warranty / ESG
    - preserve filing-native wording
    """

    values: list[str] = []
    evidence: list[str] = []

    patterns = [
        # Explicit product/service lists.
        r"\bour products and services include\s+(.+?)(?:\.|;)",
        r"\bour products include\s+(.+?)(?:\.|;)",
        r"\bour services include\s+(.+?)(?:\.|;)",
        r"\bour solutions include\s+(.+?)(?:\.|;)",
        r"\bour offerings include\s+(.+?)(?:\.|;)",
        r"\bour product offerings include\s+(.+?)(?:\.|;)",
        r"\bour portfolio includes\s+(.+?)(?:\.|;)",
        r"\bour product portfolio includes\s+(.+?)(?:\.|;)",
        r"\bprincipal products include\s+(.+?)(?:\.|;)",
        r"\bprincipal products are\s+(.+?)(?:\.|;)",

        # Commercial verbs.
        r"\bwe offer\s+(.+?)(?:\.|;)",
        r"\bwe provide\s+(.+?)(?:\.|;)",
        r"\bwe sell\s+(.+?)(?:\.|;)",
        r"\bwe market\s+(.+?)(?:\.|;)",
        r"\bwe manufacture and sell\s+(.+?)(?:\.|;)",
        r"\bwe develop and sell\s+(.+?)(?:\.|;)",
        r"\bwe design and sell\s+(.+?)(?:\.|;)",
        r"\bwe design, develop and sell\s+(.+?)(?:\.|;)",
        r"\bwe design, manufacture and sell\s+(.+?)(?:\.|;)",
        r"\bwe design, develop, manufacture and sell\s+(.+?)(?:\.|;)",

        # Platform/system structures.
        r"\bour platform consists of\s+(.+?)(?:\.|;)",
        r"\bour platform includes\s+(.+?)(?:\.|;)",
        r"\bour platforms include\s+(.+?)(?:\.|;)",
        r"\bour systems include\s+(.+?)(?:\.|;)",

        # Generic product line wording.
        r"\bour product lines include\s+(.+?)(?:\.|;)",
        r"\bour product families include\s+(.+?)(?:\.|;)",
        r"\bwe offer a range of\s+(.+?)(?:\.|;)",
        r"\bwe provide a range of\s+(.+?)(?:\.|;)",
    ]

    # Sentence-level scan.
    for sentence in _sentences(
        text
    ):
        if not _offering_context_allowed(
            sentence
        ):
            continue

        for pattern in patterns:
            for match in re.finditer(
                pattern,
                sentence,
                flags=re.IGNORECASE,
            ):
                phrase = (
                    match.group(1)
                )

                candidates = (
                    _split_offering_phrase(
                        phrase
                    )
                )

                if not candidates:
                    continue

                values.extend(
                    candidates
                )

                evidence.append(
                    re.sub(
                        r"\s+",
                        " ",
                        match.group(0),
                    ).strip()
                )

    # Section-level scan, but still guarded.
    heading_pattern = re.compile(
        r"(?:^|\n)"
        r"(?:Our )?"
        r"(?:Products(?: and Services)?|"
        r"Products & Services|"
        r"Services|"
        r"Solutions|"
        r"Product Portfolio|"
        r"Product Offerings)"
        r"\s*\n"
        r"(.{20,2200}?)"
        r"(?=\n[A-Z][^\n]{0,80}\n|\Z)",
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    for match in (
        heading_pattern.finditer(
            text
        )
    ):
        section = (
            match.group(1)
        )

        for sentence in (
            _sentences(
                section
            )[:10]
        ):
            if not _offering_context_allowed(
                sentence
            ):
                continue

            for pattern in patterns:
                sub_match = re.search(
                    pattern,
                    sentence,
                    flags=re.IGNORECASE,
                )

                if not sub_match:
                    continue

                candidates = (
                    _split_offering_phrase(
                        sub_match.group(1)
                    )
                )

                if candidates:
                    values.extend(
                        candidates
                    )

                    evidence.append(
                        sentence
                    )

    return (
        _dedupe(values),
        _dedupe(evidence),
    )

def _extract_product_stack(
    text: str,
) -> tuple[
    list[str],
    list[str],
]:
    values: list[str] = []
    evidence: list[str] = []

    # ---------------------------------
    # V2.6.2 generic filing-native
    # offering extraction.
    # ---------------------------------

    (
        generic_values,
        generic_evidence,
    ) = _extract_generic_offerings(
        text
    )

    values.extend(
        generic_values
    )

    evidence.extend(
        generic_evidence
    )

    # ---------------------------------
    # Preserve validated V2.3 special
    # patterns used by AAOI/reference
    # companies.
    # ---------------------------------

    patterns = [
        (
            r"levels? of integration,"
            r"\s*from\s+(.+?)\."
        ),
        (
            r"design and manufacture "
            r"a range of [^.]+?"
            r"from\s+(.+?)\."
        ),
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            raw = (
                match.group(1)
            )

            raw = re.sub(
                r"\bmodules\s+to\s+"
                r"complete\s+",
                "modules, complete ",
                raw,
                flags=re.IGNORECASE,
            )

            values.extend(
                _split_list_phrase(
                    raw
                )
            )

            evidence.append(
                match.group(0)
            )

    building_blocks = re.search(
        r"fundamental building "
        r"blocks of\s+([^.]+)",
        text,
        flags=re.IGNORECASE,
    )

    if building_blocks:
        values = (
            _split_list_phrase(
                building_blocks.group(1)
            )
            + values
        )

        evidence.append(
            building_blocks.group(0)
        )

    blocked_exact = {
        "we design",
        "assembly",
        "laser design",
        (
            "fabrication optical "
            "system design"
        ),
    }

    replacements = {
        (
            "complete turn-key "
            "equipment"
        ):
            "turn-key equipment",

        (
            "complete turnkey "
            "equipment"
        ):
            "turn-key equipment",
    }

    cleaned = []

    for value in _dedupe(
        values
    ):
        value = (
            _clean_offering_phrase(
                value
            )
        )

        lower = (
            value.lower()
        )

        if (
            lower
            in blocked_exact
        ):
            continue

        if (
            len(
                value.split()
            )
            > 10
        ):
            continue

        if any(
            phrase in lower
            for phrase in (
                "foundational products",
                "from these",
                "we design",
            )
        ):
            continue

        value = replacements.get(
            lower,
            value,
        )

        if not _valid_offering(
            value
        ):
            continue

        cleaned.append(
            value
        )

    return (
        _dedupe(cleaned),
        _dedupe(evidence),
    )



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
        r"\bsales of\s+(.+?)\s+have contributed",
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

    blocked_phrases = (
        "rapid product development",
        "fast response",
        "greater control",
        "manufacturing costs",
        "backhaul of cellular",
        "oil",
        "gas exploration",
        "aerospace",
        "defense",
        "industrial robotics",
    )

    cleaned = []

    for product in _dedupe(products):
        lower = product.lower()

        if any(
            phrase in lower
            for phrase in blocked_phrases
        ):
            continue

        if len(product.split()) > 7:
            continue

        cleaned.append(product)

    return cleaned


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

            if not any(
                alias in lowered
                for alias in aliases
            ):
                continue

            # Keep only paragraphs that explicitly describe products, offerings,
            # or customers for the market. This reduces cross-market pollution.
            if any(
                token in lowered
                for token in (
                    "we supply",
                    "our products",
                    "products for",
                    "offerings include",
                    "customers in this market",
                    "customers in this segment",
                    "platform consists of",
                    "systems include",
                    "networking offerings include",
                    "sales of",
                )
            ):
                matched_paragraphs.append(paragraph)

        products = []

        for paragraph in matched_paragraphs:
            products.extend(
                _extract_products_from_paragraph(
                    paragraph
                )
            )

        filtered = []

        for product in _dedupe(products):
            lower = product.lower()

            # 5G references in AAOI describe telecom demand rather than products
            # sold into the data-center/CATV/FTTH markets.
            if (
                market.lower()
                in {
                    "internet data center",
                    "catv",
                    "ftth",
                }
                and "5g" in lower
            ):
                continue

            filtered.append(product)

        key = _slug(market)

        if filtered:
            output[key] = _dedupe(filtered)
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

    blocked_acronyms = {
        "5G",
        "PRC",
        "US",
        "U.S",
    }

    for match in acronym_pattern.finditer(text):
        acronym = match.group(2).upper()

        if acronym in blocked_acronyms:
            continue

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

        # Definitions of customer/device categories can contain a technology
        # acronym near words such as "manufacturing" without asserting that
        # the technology belongs to the reporting company.
        if re.match(
            r"^(?:types?|kinds?|categories?)\s+of\b.*\b(?:include|includes)\b",
            expansion,
            flags=re.IGNORECASE,
        ):
            continue

        direct_tail = text[match.end():min(len(text), match.end() + 90)]
        organization_head = re.search(
            r"\b(?:Corporation|Company|Consortium|Association|Organization|"
            r"Alliance|Council|Society|Institute|Foundation)\b",
            expansion,
            flags=re.IGNORECASE,
        )
        organization_appositive = re.match(
            r"\s*,?\s*(?:our|an?|the)\s+(?:industry\s+)?"
            r"(?:organization|association|consortium|alliance|council|society|"
            r"institute|foundation)\b",
            direct_tail,
            flags=re.IGNORECASE,
        )
        membership_role = re.search(
            r"\b(?:member|membership|founding\s+member)\s+of\s+(?:the\s+)?$",
            text[max(0, match.start() - 45):match.start()],
            flags=re.IGNORECASE,
        )

        regulatory_or_framework_context = re.search(
            r"\b(?:frameworks?\s*,?\s+such\s+as|data\s+(?:privacy|protection)|"
            r"regulations?|compliance\s+requirements?|laws?\s+in)\b",
            context,
            flags=re.IGNORECASE,
        )

        if (
            organization_head
            or organization_appositive
            or membership_role
            or regulatory_or_framework_context
        ):
            continue

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

    non_geography_candidate = re.compile(
        r"^(?:"
        r"(?:semiconductor|microelectronics?|electronics?|automotive|medical|"
        r"aerospace|industrial|advanced)"
        r"|"
        r"(?:electric|autonomous)\s+vehicles?"
        r"|"
        r"(?:battery|solar\s+cell|flat\s+panel\s+display)\s+production"
        r"|"
        r"(?:microelectronics?\s+)?fabrication"
        r"|"
        r"(?:metal\s+)?cutting"
        r"|"
        r"welding"
        r"|"
        r"(?:advanced\s+)?manufacturing"
        r")$",
        flags=re.IGNORECASE,
    )

    non_location_outcome = re.compile(
        r"\b(?:"
        r"aligned\s+to\s+business\s+conditions|"
        r"inventory\s+levels?|reduced\s+sales|"
        r"underestimate\s+the\s+demand|production\s+costs?|"
        r"operating\s+expenses?|business\s+conditions"
        r")\b",
        flags=re.IGNORECASE,
    )

    for pattern in location_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        raw = match.group(1)
        raw = re.split(
            r",\s+to\s+(?:manufacture|produce|assemble)\b",
            raw,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
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
            normalized = re.sub(
                r"^(?:one|two|three|four|five|six|seven|eight|nine|ten|"
                r"eleven|twelve|\d+)\s+(?=(?:United States|China|Japan|"
                r"Vietnam|Mexico|India|Malaysia|Singapore|Taiwan|Korea)\b)",
                "",
                normalized,
                flags=re.IGNORECASE,
            )

            if (
                len(normalized.split()) <= 5
                and not non_geography_candidate.fullmatch(normalized)
                and not non_location_outcome.search(normalized)
                and not re.search(
                    r"\b(?:accessories|consumables|tools?|product\s+categories|"
                    r"technologies|workflows?|components?)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            ):
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

    # Normalize only customer types explicitly present in filing text.
    # These are evidence-surface aliases, not ontology classifications.
    literal_customer_patterns = [
        (
            r'hyperscale[^.]{0,40}?data center operators',
            "hyperscale data center operators",
        ),
        (
            r'CATV multiple system operators',
            "CATV MSOs",
        ),
        (
            r'\bMSO customers\b',
            "CATV MSOs",
        ),
        (
            r'network equipment manufacturers',
            "network equipment manufacturers",
        ),
        (
            r'manufacturers of optical transceivers',
            "optical transceiver manufacturers",
        ),
        (
            r'CATV equipment vendors',
            "CATV equipment vendors",
        ),
        (
            r'cloud providers',
            "cloud providers",
        ),
        (
            r'AI model makers',
            "AI model makers",
        ),
        (
            r'original equipment manufacturers',
            "OEMs",
        ),
        (
            r'original device manufacturers',
            "ODMs",
        ),
        (
            r'system integrators',
            "system integrators",
        ),
    ]

    for pattern, label in literal_customer_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            customers.append(label)
            evidence.append(match.group(0))

    return _dedupe(customers), evidence

def _extract_ai_exposure(
    text: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    candidates = []

    for sentence in _sentences(text):
        lower = sentence.lower()

        if (
            (
                "artificial intelligence" in lower
                or re.search(r"\bAI\b", sentence)
            )
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

    # SEC extraction may concatenate the next bullet heading to the sentence.
    # Keep only the AI-related statement.
    summary = re.split(
        r"\s+[‑–—-]\s+Trends in the ",
        summary,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()

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
    }, [summary]

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

    # SEC text uses several bullet characters. Split on all common forms.
    parts = re.split(
        r"(?:^|\n)\s*[‑–—•-]\s*",
        section,
    )

    strengths = []

    for part in parts:
        part = part.strip()

        if not part:
            continue

        if part.lower().startswith(
            "our key competitive strengths include"
        ):
            continue

        sentences = _sentences(part)

        if not sentences:
            continue

        first = sentences[0].strip()

        # Filing bullets often use "Heading. Explanation...".
        # Keep the heading rather than the whole explanatory paragraph.
        heading_match = re.match(
            r"^([^.!?]{5,140})\.\s+",
            first,
        )

        if heading_match:
            strengths.append(
                heading_match.group(1).strip()
            )
        elif len(first) <= 280:
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

    profile = {
        "schema_version":
            "axiom-company-profile.v2.3",
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

    profile["value_provenance"] = (
        build_value_provenance(
            profile=profile,
            raw_text=str(
                evidence["text"]
            ),
            evidence=evidence,
        )
    )

    return profile
