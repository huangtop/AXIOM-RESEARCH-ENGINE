#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(
        0,
        str(ROOT / "src"),
    )


from axiom_engine.company_profile_v2.batch import (  # noqa: E402
    CompanyProfileBatchError,
    build_company_profile_batch,
    write_company_profile_batch,
)
from axiom_engine.company_profile_v2.display_zh_tw import (  # noqa: E402
    build_company_profile_display_zh_tw,
)
from axiom_engine.company_profile_v2.enrichment import (  # noqa: E402
    enrich_company_profile_display,
)


TRANSLATION_CENSUS = (
    ROOT
    / "data/generated/company_profile_v2"
    / "translation_universe_census_v2640.json"
)

BUSINESS_EVIDENCE_ROOT = (
    ROOT
    / "data/generated/canonical_business_evidence"
)

SUPPORTED_BUSINESS_SECTIONS = {
    "item_1_business",
    "item_4_company_information",
}

# These terms identify filing sentences/lines that are genuinely describing
# commercial products. They are intentionally generic and company-agnostic.
_PRODUCT_CONTEXT_TERMS = (
    " product",
    " products",
    " product brand",
    " product brands",
    " product family",
    " product families",
    " portfolio",
    " cpu",
    " cpus",
    " gpu",
    " gpus",
    " processor",
    " processors",
    " accelerator",
    " accelerators",
    " fpga",
    " fpgas",
    " soc",
    " socs",
    " chipset",
    " chipsets",
    " nic",
    " nics",
    " dpu",
    " dpus",
    " networking",
    " graphics",
    " retimer",
    " retimers",
    " controller",
    " controllers",
    " switch",
    " switches",
    " module",
    " modules",
    " software suite",
    " software platform",
    " design suite",
    " system-on-module",
)

_PRODUCT_HEAD_TERMS = (
    "processor",
    "processors",
    "cpu",
    "cpus",
    "gpu",
    "gpus",
    "accelerator",
    "accelerators",
    "nic",
    "nics",
    "dpu",
    "dpus",
    "fpga",
    "fpgas",
    "soc",
    "socs",
    "graphics",
    "chipset",
    "chipsets",
    "retimer",
    "retimers",
    "cable module",
    "cable modules",
    "module",
    "modules",
    "controller",
    "controllers",
    "switch",
    "switches",
    "software",
    "suite",
    "platform",
    "board",
    "boards",
    "card",
    "cards",
    "semiconductor",
    "semiconductors",
    "ic",
    "ics",
    "memory",
    "storage",
    "transceiver",
    "transceivers",
    "sensor",
    "sensors",
)

# Non-commercial filing contexts that must never create product names.
_BLOCKED_PRODUCT_CONTEXT = (
    "air pollut",
    "air emission",
    "greenhouse gas",
    "wastewater",
    "hazardous waste",
    "hazardous material",
    "environmental law",
    "environmental regulation",
    "environmental compliance",
    "climate-related",
    "climate related",
    "human rights",
    "modern slavery",
    "employee benefit",
    "employee benefits",
    "health benefits",
    "compensation",
    "workforce",
    "our employees",
    "prospectus",
    "securities under",
    "sec filing",
    "risk factors",
    "stock-based compensation",
    "shareholder",
    "dividend",
    "repurchase program",
    "workstation-as-a-service",
    "cloud gaming",
)

_BLOCKED_PRODUCT_CANDIDATES = (
    "air pollut",
    "wastewater",
    "hazardous",
    "emission",
    "prospectus",
    "securities under",
    "employee benefit",
    "compensation",
    "shareholder",
    "stock-based",
    "revenue",
    "gross margin",
    "operating expense",
    "customer demand",
    "market demand",
    "bottleneck",
    "bottlenecks",
    "inherent in",
    "vendors)",
    "various form factors including",
    "workstation-as-a-service",
    "cloud gaming",
)

_GENERIC_PRODUCT_EXACT = {
    "products",
    "product",
    "services",
    "service",
    "solutions",
    "solution",
    "offerings",
    "offering",
    "technology",
    "technologies",
    "capabilities",
    "business",
    "operations",
    "customers",
    "markets",
    "shipping millions of devices across leading hyperscalers",
}


def _load_json(
    path: Path,
) -> Any:
    return json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )


def _public_report(
    report: dict,
) -> dict:
    return {
        key: value
        for key, value
        in report.items()
        if not str(key).startswith(
            "_"
        )
    }


def _strategic_symbols() -> list[str]:
    if not TRANSLATION_CENSUS.is_file():
        raise CompanyProfileBatchError(
            "strategic translation census not found: "
            f"{TRANSLATION_CENSUS.relative_to(ROOT)}"
        )

    payload = _load_json(
        TRANSLATION_CENSUS
    )

    rows = payload.get(
        "translation_candidates"
    ) or []

    symbols = sorted(
        {
            str(
                row.get("symbol")
                or ""
            ).strip().upper()
            for row in rows
            if isinstance(
                row,
                dict,
            )
            and row.get("symbol")
        }
    )

    if not symbols:
        raise CompanyProfileBatchError(
            "translation census contains no translation_candidates"
        )

    return symbols


def _latest_business_evidence(
    company_id: str,
) -> dict[str, Any] | None:
    index_path = (
        BUSINESS_EVIDENCE_ROOT
        / "index.json"
    )

    if not index_path.is_file():
        return None

    index = _load_json(
        index_path
    )

    rel = (
        index.get(
            "company_id_to_file",
            {},
        ).get(
            company_id
        )
    )

    if not rel:
        return None

    path = (
        BUSINESS_EVIDENCE_ROOT
        / str(rel)
    )

    if not path.is_file():
        return None

    rows = _load_json(
        path
    )

    if not isinstance(
        rows,
        list,
    ):
        return None

    candidates = [
        row
        for row in rows
        if isinstance(
            row,
            dict,
        )
        and row.get(
            "section_type"
        )
        in SUPPORTED_BUSINESS_SECTIONS
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
            row.get(
                "filing_date"
            )
            or ""
        ),
    )


def _clean_text(
    value: str,
) -> str:
    value = (
        str(value or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00a0", " ")
        .replace("\ufeff", "")
    )

    value = re.sub(
        r"[ \t]+",
        " ",
        value,
    )

    return value.strip()


def _sentences(
    text: str,
) -> list[str]:
    compact = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return [
        row.strip()
        for row in re.split(
            r"(?<=[.!?])\s+(?=[A-Z0-9])",
            compact,
        )
        if len(
            row.strip()
        )
        >= 15
    ]


def _dedupe(
    values: list[str],
) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()

    for raw in values:
        value = re.sub(
            r"\s+",
            " ",
            str(raw or ""),
        ).strip(
            " ,.;:-"
        )

        if not value:
            continue

        key = (
            value
            .replace("™", "")
            .replace("®", "")
            .casefold()
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        output.append(
            value
        )

    return output


def _blocked_product_context(
    text: str,
) -> bool:
    lower = (
        " "
        + re.sub(
            r"\s+",
            " ",
            str(text or ""),
        ).casefold()
        + " "
    )

    return any(
        term in lower
        for term
        in _BLOCKED_PRODUCT_CONTEXT
    )


def _has_brand_signal(
    value: str,
) -> bool:
    # Trademarked product names, model-number tokens, or a multiword
    # title-case/uppercase brand phrase are strong filing-native signals.
    if (
        "™" in value
        or "®" in value
    ):
        return True

    if re.search(
        r"\b[A-Z]{1,8}[A-Z0-9-]*\d[A-Z0-9-]*\b",
        value,
    ):
        return True

    tokens = re.findall(
        r"[A-Za-z0-9+.-]+",
        value,
    )

    capitalized = sum(
        bool(
            re.match(
                r"^[A-Z][A-Za-z0-9+.-]*$",
                token,
            )
        )
        for token in tokens
    )

    return (
        len(tokens) >= 2
        and capitalized >= 2
    )



def _normalize_product_candidate(
    value: str,
) -> str:
    value = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip(
        " ,.;:-"
    )

    # Remove leading filing grammar / table-of-contents residue that is
    # not part of the product name.
    value = re.sub(
        r"^(?:contents\s+|table of contents\s+)+",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^(?:the|our)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )

    # Collapse filing-native descriptive wrappers when the actual branded
    # family is already explicit in the phrase.
    value = re.sub(
        r"^products?\s+in\s+the\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"\s+families$",
        " Series",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"\s+brand$",
        "",
        value,
        flags=re.IGNORECASE,
    )

    # Product-brand disclosure:
    #   AMD Embedded Radeon graphics is our product brand for ...
    # becomes:
    #   AMD Embedded Radeon graphics
    value = re.sub(
        r"\s+is\s+(?:our|the)\s+product brand\b.*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip(
        " ,.;:-"
    )

    # Cut descriptive sentence tails that escaped the list parser.
    value = re.sub(
        r"\s+(?:that|which)\s+(?:"
        r"are|is|were|was|enable|enables|provide|provides|"
        r"support|supports|address|addresses|help|helps"
        r")\b.*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip(
        " ,.;:-"
    )

    # Remove unmatched closing punctuation left by SEC parenthetical captures.
    if value.endswith(")") and value.count("(") < value.count(")"):
        value = value.rstrip(")").strip()

    return value


def _product_candidate_allowed(
    value: str,
) -> bool:
    candidate = _normalize_product_candidate(
        value
    )

    if not candidate:
        return False

    lower = (
        candidate
        .replace("™", "")
        .replace("®", "")
        .casefold()
    )

    if lower in _GENERIC_PRODUCT_EXACT:
        return False

    if any(
        term in lower
        for term
        in _BLOCKED_PRODUCT_CANDIDATES
    ):
        return False

    if len(
        candidate.split()
    ) > 16:
        return False

    if re.match(
        r"^(?:"
        r"shipping|designed|intended|used|using|"
        r"based|providing|enabling|allowing|"
        r"discharge|increase|decrease|growth"
        r")\b",
        lower,
    ):
        return False

    if re.search(
        r"\b(?:that|which|who)\s+(?:"
        r"are|is|were|was|enable|enables|provide|provides|"
        r"support|supports|address|addresses"
        r")\b",
        lower,
    ):
        return False

    if re.search(
        r"\b(?:"
        r"customers?|hyperscalers?|oems?|odms?|"
        r"distributors?|employees?|suppliers?|vendors?"
        r")\b",
        lower,
    ) and not any(
        head in lower
        for head in (
            "customer software",
            "customer platform",
        )
    ):
        return False

    has_product_head = any(
        re.search(
            rf"\b{re.escape(head)}\b",
            lower,
        )
        for head
        in _PRODUCT_HEAD_TERMS
    )

    if (
        not has_product_head
        and not _has_brand_signal(
            candidate
        )
    ):
        return False

    return True


def _split_named_product_phrase(
    value: str,
) -> list[str]:
    value = re.sub(
        r"\([^)]{0,100}\)",
        lambda match: (
            match.group(0)
            if re.search(
                r"\b(?:PCIe|CXL|IC|GPU|CPU|NIC|DPU|FPGA|SoC)\b",
                match.group(0),
                flags=re.IGNORECASE,
            )
            else ""
        ),
        str(value or ""),
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

    # Split conjunctions only when they look like list separators. This
    # preserves phrases such as "compute and network acceleration boards".
    value = re.sub(
        r",\s+and\s+",
        ", ",
        value,
        flags=re.IGNORECASE,
    )

    raw_parts = [
        row.strip()
        for row in value.split(
            ","
        )
        if row.strip()
    ]

    output: list[str] = []

    for raw in raw_parts:
        pieces = [
            raw
        ]

        if re.search(
            r"\s+and\s+",
            raw,
            flags=re.IGNORECASE,
        ):
            candidate_parts = re.split(
                r"\s+and\s+",
                raw,
                flags=re.IGNORECASE,
            )

            if all(
                len(
                    part.split()
                )
                <= 10
                for part
                in candidate_parts
            ) and all(
                _product_candidate_allowed(
                    part
                )
                for part
                in candidate_parts
            ):
                pieces = (
                    candidate_parts
                )

        for piece in pieces:
            piece = re.sub(
                r"^(?:"
                r"including|"
                r"such as|"
                r"and|"
                r"or"
                r")\s+",
                "",
                piece,
                flags=re.IGNORECASE,
            ).strip(
                " ,.;:-"
            )

            piece = _normalize_product_candidate(
                piece
            )

            if _product_candidate_allowed(
                piece
            ):
                output.append(
                    piece
                )

    return _dedupe(
        output
    )


def _inherit_model_family(
    products: list[str],
) -> list[str]:
    # Filing lists often write:
    #   AMD Instinct MI200, MI300, MI325 series
    # The later items are shorthand. Generic prefix inheritance restores
    # the disclosed family without hard-coding any company/product name.
    output: list[str] = []
    active_prefix: str | None = None

    for product in products:
        value = product.strip()

        model = re.search(
            r"\b([A-Z]{1,8}\d[A-Z0-9-]*)\b",
            value,
        )

        if model:
            before = (
                value[
                    :model.start()
                ].strip()
            )

            if (
                before
                and len(
                    before.split()
                )
                <= 5
                and _has_brand_signal(
                    before
                    + " "
                    + model.group(1)
                )
            ):
                active_prefix = (
                    before
                )

            elif (
                active_prefix
                and re.match(
                    r"^[A-Z]{1,8}\d",
                    value,
                )
            ):
                value = (
                    active_prefix
                    + " "
                    + value
                )

        output.append(
            value
        )

    return _dedupe(
        output
    )


def _extract_named_products(
    text: str,
) -> tuple[
    list[str],
    list[str],
]:
    text = _clean_text(
        text
    )

    products: list[str] = []
    evidence: list[str] = []

    patterns = [
        # Astera-style:
        # Our products, which include Aries..., Taurus..., Leo..., Scorpio...
        r"\bour products?\s*,?\s*which include\s+(.+?)"
        r"(?=,\s*(?:are|is)\b|\.\s+[A-Z]|\.$)",

        # Product/portfolio lists with arbitrary filing-native head nouns.
        r"\bour\s+[^.]{0,100}?\b(?:products?|portfolio|cpus?|gpus?|"
        r"processors?|accelerators?|fpgas?|adaptive socs?|networking solutions?)"
        r"[^.]{0,60}?\b(?:include|includes|including)\s+(.+?)"
        r"(?=,\s*(?:are|is|which)\b|\.\s+[A-Z]|\.$)",

        # Explicit brand disclosures.
        r"\bour product brands?\s+for\s+[^.]{1,100}?\s+"
        r"(?:is|are|include|includes)\s+(.+?)(?:\.|;)",

        r"\bour product brand\s+for\s+[^.]{1,100}?\s+"
        r"(?:is|are)\s+(.+?)(?:\.|;)",

        # AMD-style category declarations.
        r"\bour\s+(?:fpga|adaptive soc|embedded|client|server|data center|"
        r"professional graphics|consumer graphics)[^.]{0,80}?\bproducts?"
        r"\s+(?:are|include|includes)\s+(.+?)(?:\.|;)",

        # Software / system-on-module product disclosures.
        r"\bthe software tools?\s+for\s+[^.]{1,120}?\s+are\s+(.+?)(?:\.|;)",
        r"\bour system-on-module\s+\(?(?:som)?\)?\s*product\s+is\s+(.+?)(?:\.|;)",
        r"\bour compute and network acceleration board products?\s+"
        r"are sold under\s+(.+?)\s+brands?(?:\.|;)",
    ]

    for sentence in _sentences(
        text
    ):
        lower = (
            " "
            + sentence.casefold()
            + " "
        )

        if _blocked_product_context(
            sentence
        ):
            continue

        if not any(
            term in lower
            for term
            in _PRODUCT_CONTEXT_TERMS
        ):
            continue

        for pattern in patterns:
            for match in re.finditer(
                pattern,
                sentence,
                flags=re.IGNORECASE,
            ):
                found = (
                    _split_named_product_phrase(
                        match.group(1)
                    )
                )

                if found:
                    products.extend(
                        found
                    )

                    evidence.append(
                        sentence
                    )

    # Product-heading extraction for filings that describe each family under
    # "Our Products and Solutions". This catches filing-native headings like:
    #   Taurus Ethernet Smart Cable Modules™.
    #   Leo CXL Memory Connectivity Controllers.
    #   COSMOS Software Suite.
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    heading_re = re.compile(
        r"^(?P<name>"
        r"[A-Z][A-Za-z0-9™®+/.-]*(?:\s+[A-Za-z0-9™®+/().-]+){0,11}\s+"
        r"(?:"
        r"Retimers?|Cable Modules?|Modules?|Controllers?|Switches?|"
        r"Processors?|GPUs?|Accelerators?|NICs?|DPUs?|FPGAs?|SoCs?|"
        r"Graphics|Software Suite|Software Platform|Design Suite|"
        r"Platform Solution"
        r")"
        r")[.:]?$"
    )

    for index, line in enumerate(
        lines
    ):
        match = heading_re.match(
            line
        )

        if not match:
            continue

        context = " ".join(
            lines[
                index:
                index + 3
            ]
        )

        if _blocked_product_context(
            context
        ):
            continue

        name = match.group(
            "name"
        )

        if _product_candidate_allowed(
            name
        ):
            products.append(
                name
            )

            evidence.append(
                context
            )

    # Inline title-style product names embedded in prose/HTML-normalized lines.
    # Requires a strong product head, so this remains generic and precision-first.
    inline_named_re = re.compile(
        r"\b("
        r"[A-Z][A-Za-z0-9™®+/.-]*(?:\s+[A-Z][A-Za-z0-9™®+/().-]*){0,5}\s+"
        r"(?:Smart\s+)?(?:Fabric\s+)?"
        r"(?:Retimers?|Cable Modules?|Controllers?|Switches?|"
        r"Processors?|Accelerators?|NICs?|DPUs?|FPGAs?|SoCs?|"
        r"Software Suite|Software Platform|Design Suite)"
        r")\b"
    )

    for sentence in _sentences(
        text
    ):
        if _blocked_product_context(
            sentence
        ):
            continue

        for match in inline_named_re.finditer(
            sentence
        ):
            name = _normalize_product_candidate(
                match.group(1)
            )

            if _product_candidate_allowed(
                name
            ):
                products.append(
                    name
                )
                evidence.append(
                    sentence
                )

    return (
        _inherit_model_family(
            _dedupe(
                products
            )
        ),
        _dedupe(
            evidence
        ),
    )



_GENERIC_CATEGORY_PATTERNS = (
    r"^(?:micro)?processors?\s*\(?(?:cpus?)?\)?$",
    r"^cpus?$",
    r"^gpus?$",
    r"^discrete gpus?$",
    r"^gpu accelerators?$",
    r"^ai accelerators?$",
    r"^dpus?$",
    r"^ai nics?$",
    r"^network interface cards?$",
    r"^fpgas?$",
    r"^field programmable gate arrays?(?:\s*\(fpgas?\))?$",
    r"^adaptive socs?$",
    r"^soc(?:s)?$",
    r"^embedded software$",
    r"^boards?$",
    r"^modules?$",
    r"^ics?$",
    r"^integrated circuits?$",
    r"^semiconductors?$",
    r"^graphics$",
    r"^storage$",
    r"^memory$",
)

_CATEGORY_SIGNAL_MAP = {
    "cpu": ("cpu", "processor", "epyc", "ryzen", "threadripper"),
    "gpu": ("gpu", "radeon", "instinct", "graphics"),
    "dpu": ("dpu", "pensando", "salina"),
    "nic": ("nic", "pollara", "solarflare"),
    "fpga": ("fpga", "virtex", "kintex", "artix", "spartan"),
    "soc": ("soc", "zynq", "versal", "kria"),
    "module": ("module", "retimer", "controller", "switch", "cable"),
}


def _canonical_product_key(
    value: str,
) -> str:
    value = _normalize_product_candidate(
        value
    )

    value = (
        value
        .replace("™", "")
        .replace("®", "")
        .casefold()
    )

    value = re.sub(
        r"\b(?:the|our|series|product|products|family|families|brand)\b",
        " ",
        value,
    )

    value = re.sub(
        r"[^a-z0-9+]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def _is_generic_category_product(
    value: str,
) -> bool:
    lower = (
        _normalize_product_candidate(
            value
        )
        .replace("™", "")
        .replace("®", "")
        .casefold()
    )

    return any(
        re.fullmatch(
            pattern,
            lower,
            flags=re.IGNORECASE,
        )
        is not None
        for pattern
        in _GENERIC_CATEGORY_PATTERNS
    )


def _has_specific_category_peer(
    value: str,
    values: list[str],
) -> bool:
    lower = (
        _normalize_product_candidate(
            value
        )
        .replace("™", "")
        .replace("®", "")
        .casefold()
    )

    matched_category = None

    for category, signals in _CATEGORY_SIGNAL_MAP.items():
        if any(
            signal in lower
            for signal
            in signals
        ):
            matched_category = category
            break

    if matched_category is None:
        return False

    signals = _CATEGORY_SIGNAL_MAP[
        matched_category
    ]

    for peer in values:
        if peer == value:
            continue

        peer_norm = (
            _normalize_product_candidate(
                peer
            )
            .replace("™", "")
            .replace("®", "")
            .casefold()
        )

        if (
            not _is_generic_category_product(
                peer
            )
            and any(
                signal in peer_norm
                for signal
                in signals
            )
        ):
            return True

    return False


def _semantic_dedupe_products(
    values: list[str],
) -> list[str]:
    normalized = _dedupe(
        [
            _normalize_product_candidate(
                value
            )
            for value
            in values
            if _normalize_product_candidate(
                value
            )
        ]
    )

    # When a company has specific named products for a category, remove
    # category-only placeholders from that same category. This preserves
    # generic categories for companies that disclose no named products.
    filtered = []

    for value in normalized:
        if (
            _is_generic_category_product(
                value
            )
            and _has_specific_category_peer(
                value,
                normalized,
            )
        ):
            continue

        filtered.append(
            value
        )

    # Near-duplicate suppression. Prefer the more specific filing-native
    # phrase when canonical keys overlap strongly.
    output: list[str] = []

    for value in filtered:
        key = _canonical_product_key(
            value
        )

        if not key:
            continue

        replaced = False
        skip = False

        for index, existing in enumerate(
            output
        ):
            existing_key = (
                _canonical_product_key(
                    existing
                )
            )

            if key == existing_key:
                # Keep the richer visible label.
                if len(value) > len(existing):
                    output[index] = value
                skip = True
                break

            if (
                key in existing_key
                or existing_key in key
            ):
                shorter = min(
                    len(key),
                    len(existing_key),
                )
                longer = max(
                    len(key),
                    len(existing_key),
                )

                if (
                    shorter >= 8
                    and shorter / longer >= 0.72
                ):
                    # Prefer branded / model-rich / trademarked form.
                    value_score = (
                        3 * int(_has_brand_signal(value))
                        + 2 * int(bool(re.search(r"\d", value)))
                        + int("™" in value or "®" in value)
                        + len(value) / 200.0
                    )
                    existing_score = (
                        3 * int(_has_brand_signal(existing))
                        + 2 * int(bool(re.search(r"\d", existing)))
                        + int("™" in existing or "®" in existing)
                        + len(existing) / 200.0
                    )

                    if value_score > existing_score:
                        output[index] = value
                        replaced = True
                    else:
                        skip = True
                    break

        if skip or replaced:
            continue

        output.append(
            value
        )

    return _dedupe(
        output
    )


def _clean_existing_product_stack(
    values: Any,
) -> list[str]:
    output = []

    for value in (
        values
        or []
    ):
        text = _normalize_product_candidate(
            str(value or "")
        )

        if _product_candidate_allowed(
            text
        ):
            output.append(
                text
            )

    return _semantic_dedupe_products(
        output
    )


def _clean_market_products(
    mapping: Any,
) -> dict[str, list[str]]:
    if not isinstance(
        mapping,
        dict,
    ):
        return {}

    output: dict[str, list[str]] = {}

    for market, values in (
        mapping.items()
    ):
        cleaned = (
            _clean_existing_product_stack(
                values
            )
        )

        cleaned = (
            _semantic_dedupe_products(
                _inherit_model_family(
                    cleaned
                )
            )
        )

        if cleaned:
            output[
                str(market)
            ] = cleaned

    return output


def _enrich_profile_product_recall(
    profile: dict[str, Any],
) -> dict[str, Any]:
    company_id = str(
        profile.get(
            "company_id"
        )
        or ""
    )

    evidence = (
        _latest_business_evidence(
            company_id
        )
    )

    if evidence is None:
        return profile

    raw_text = str(
        evidence.get("text")
        or ""
    )

    discovered, discovered_evidence = (
        _extract_named_products(
            raw_text
        )
    )

    existing = (
        _clean_existing_product_stack(
            profile.get(
                "product_stack"
            )
        )
    )

    merged = _semantic_dedupe_products(
        discovered
        + existing
    )

    profile[
        "product_stack"
    ] = merged

    profile[
        "market_products"
    ] = (
        _clean_market_products(
            profile.get(
                "market_products"
            )
        )
    )

    field_evidence = dict(
        profile.get(
            "field_evidence"
        )
        or {}
    )

    current_product_evidence = list(
        field_evidence.get(
            "product_stack"
        )
        or []
    )

    field_evidence[
        "product_stack"
    ] = _dedupe(
        discovered_evidence
        + current_product_evidence
    )

    profile[
        "field_evidence"
    ] = field_evidence

    profile[
        "product_recall_enrichment"
    ] = {
        "version": "v2.6.4.9",
        "mode": (
            "generic_filing_native_named_product_recovery"
        ),
        "discovered_product_count": len(
            discovered
        ),
        "final_product_count": len(
            merged
        ),
        "removed_market_product_pollution": True,
    }

    return profile


def _rebuild_display_profiles(
    report: dict[str, Any],
) -> None:
    rebuilt = []

    for profile in (
        report.get(
            "_canonical_profiles"
        )
        or []
    ):
        display = (
            build_company_profile_display_zh_tw(
                ROOT,
                profile=profile,
            )
        )

        display = (
            enrich_company_profile_display(
                ROOT,
                profile=profile,
                display_payload=display,
            )
        )

        rebuilt.append(
            display
        )

    report[
        "_display_profiles"
    ] = rebuilt


def _apply_product_recall(
    report: dict[str, Any],
) -> None:
    profiles = list(
        report.get(
            "_canonical_profiles"
        )
        or []
    )

    by_symbol = {}

    for profile in profiles:
        _enrich_profile_product_recall(
            profile
        )

        symbol = str(
            profile.get(
                "symbol"
            )
            or ""
        ).upper()

        if symbol:
            by_symbol[
                symbol
            ] = profile

    for row in (
        report.get(
            "records"
        )
        or []
    ):
        symbol = str(
            row.get(
                "symbol"
            )
            or ""
        ).upper()

        profile = (
            by_symbol.get(
                symbol
            )
        )

        if profile is None:
            continue

        products = list(
            profile.get(
                "product_stack"
            )
            or []
        )

        row[
            "product_stack_count"
        ] = len(
            products
        )

        row[
            "product_stack_preview"
        ] = products[:40]

        row[
            "product_stack_full"
        ] = products

        row[
            "generic_product_count"
        ] = sum(
            _is_generic_category_product(
                value
            )
            for value
            in products
        )

    _rebuild_display_profiles(
        report
    )



_LOCATION_PRODUCT_RE = re.compile(
    r"^(?:"
    r"United States|United Kingdom|North Carolina|South Carolina|"
    r"California|Texas|New York|Mainland China|China|Europe|Asia|"
    r"North America|South America|Middle East|Africa"
    r")$",
    flags=re.IGNORECASE,
)

_ORG_PRODUCT_RE = re.compile(
    r"\b(?:"
    r"Sales Organization|General Services Administration|"
    r"government agency|regulatory agency"
    r")\b",
    flags=re.IGNORECASE,
)

_FRAGMENT_PRODUCT_RE = re.compile(
    r"^(?:"
    r"combined with|as described below|use of|covering|"
    r"monitoring within|actual software|own branded products|"
    r"software or other intellectual property licensed|"
    r"receiver components and associated software to support"
    r")\b",
    flags=re.IGNORECASE,
)


def _record_products(
    row: dict,
) -> list[str]:
    values = row.get(
        "product_stack_full"
    )

    if not isinstance(
        values,
        list,
    ):
        values = row.get(
            "product_stack_preview"
        )

    if not isinstance(
        values,
        list,
    ):
        return []

    return [
        str(value).strip()
        for value
        in values
        if str(value).strip()
    ]


def _product_quality_flags(
    row: dict,
) -> list[dict]:
    symbol = str(
        row.get("symbol") or ""
    )
    products = _record_products(
        row
    )
    flags: list[dict] = []

    if not products:
        flags.append(
            {
                "type": "EMPTY_PRODUCT_STACK",
                "symbol": symbol,
                "value": "",
            }
        )
        return flags

    for value in products:
        if _LOCATION_PRODUCT_RE.search(
            value
        ):
            flags.append(
                {
                    "type": "LOCATION_POLLUTION",
                    "symbol": symbol,
                    "value": value,
                }
            )
            continue

        if _ORG_PRODUCT_RE.search(
            value
        ):
            flags.append(
                {
                    "type": "ORG_POLLUTION",
                    "symbol": symbol,
                    "value": value,
                }
            )
            continue

        if _FRAGMENT_PRODUCT_RE.search(
            value
        ):
            flags.append(
                {
                    "type": "SENTENCE_FRAGMENT",
                    "symbol": symbol,
                    "value": value,
                }
            )

    return flags


def _percentile_nearest_rank(
    values: list[int],
    percentile: float,
) -> int:
    if not values:
        return 0

    ordered = sorted(
        values
    )
    index = max(
        0,
        min(
            len(ordered) - 1,
            int(
                (len(ordered) * percentile)
                + 0.999999
            ) - 1,
        ),
    )

    return ordered[
        index
    ]


def _compact_census_report(
    report: dict,
    *,
    sample_limit: int = 12,
    worst_limit: int = 20,
) -> dict:
    records = report.get(
        "records"
    ) or []

    failures = report.get(
        "failures"
    ) or []

    counts = [
        len(
            _record_products(
                row
            )
        )
        for row
        in records
    ]

    diagnostics: dict[
        str,
        list[dict],
    ] = {
        "EMPTY_PRODUCT_STACK": [],
        "LOCATION_POLLUTION": [],
        "ORG_POLLUTION": [],
        "SENTENCE_FRAGMENT": [],
    }

    row_flag_counts: dict[
        str,
        int,
    ] = {}

    for row in records:
        symbol = str(
            row.get("symbol") or ""
        )

        row_flags = (
            _product_quality_flags(
                row
            )
        )

        row_flag_counts[
            symbol
        ] = len(
            row_flags
        )

        for flag in row_flags:
            diagnostics[
                flag["type"]
            ].append(
                flag
            )

    non_empty_count = sum(
        count > 0
        for count
        in counts
    )
    empty_count = (
        len(records)
        - non_empty_count
    )

    suspected_symbols = {
        item["symbol"]
        for key, items
        in diagnostics.items()
        if key != "EMPTY_PRODUCT_STACK"
        for item
        in items
    }

    generic_only_count = 0

    for row in records:
        products = _record_products(
            row
        )

        if (
            products
            and int(
                row.get(
                    "generic_product_count"
                )
                or 0
            )
            >= len(products)
        ):
            generic_only_count += 1

    production_ready_count = sum(
        bool(
            row.get(
                "production_ready"
            )
        )
        for row
        in records
    )

    worst_rows = sorted(
        records,
        key=lambda row: (
            row_flag_counts.get(
                str(
                    row.get(
                        "symbol"
                    )
                    or ""
                ),
                0,
            ),
            int(
                row.get(
                    "generic_product_count"
                )
                or 0
            ),
            len(
                _record_products(
                    row
                )
            ),
        ),
        reverse=True,
    )

    worst = []

    for row in worst_rows:
        symbol = str(
            row.get("symbol") or ""
        )
        flag_count = (
            row_flag_counts.get(
                symbol,
                0,
            )
        )
        generic_count = int(
            row.get(
                "generic_product_count"
            )
            or 0
        )

        if (
            flag_count == 0
            and generic_count == 0
        ):
            continue

        worst.append(
            {
                "symbol": symbol,
                "product_stack_count": len(
                    _record_products(
                        row
                    )
                ),
                "generic_product_count": generic_count,
                "quality_flag_count": flag_count,
                "flags": [
                    flag["type"]
                    for flag
                    in _product_quality_flags(
                        row
                    )
                ],
                "preview": _record_products(
                    row
                )[:5],
            }
        )

        if len(worst) >= worst_limit:
            break

    return {
        "schema_version": (
            "axiom-company-profile-product-census.v2.6.4.9"
        ),
        "scope": (
            "strategic"
            if report.get(
                "_requested_scope"
            ) == "strategic"
            else report.get(
                "scope"
            )
        ),
        "summary": {
            "target_company_count": (
                report.get(
                    "summary",
                    {},
                ).get(
                    "target_company_count",
                    len(records)
                    + len(failures),
                )
            ),
            "generated_company_count": len(
                records
            ),
            "failed_company_count": len(
                failures
            ),
            "production_ready_count": (
                production_ready_count
            ),
            "not_ready_count": (
                len(records)
                - production_ready_count
            ),
            "complete": (
                report.get(
                    "summary",
                    {},
                ).get(
                    "complete",
                    not failures,
                )
            ),
        },
        "product_stack": {
            "non_empty_count": non_empty_count,
            "empty_count": empty_count,
            "suspected_pollution_company_count": len(
                suspected_symbols
            ),
            "generic_only_company_count": (
                generic_only_count
            ),
        },
        "product_count_distribution": {
            "median": (
                _percentile_nearest_rank(
                    counts,
                    0.50,
                )
            ),
            "p90": (
                _percentile_nearest_rank(
                    counts,
                    0.90,
                )
            ),
            "max": (
                max(counts)
                if counts
                else 0
            ),
        },
        "diagnostics": {
            key: {
                "count": len(
                    items
                ),
                "samples": items[
                    :sample_limit
                ],
            }
            for key, items
            in diagnostics.items()
        },
        "worst_records": worst,
        "failure_samples": failures[
            :sample_limit
        ],
        "product_recall_policy": (
            report.get(
                "product_recall_policy"
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build production Company Profile V2.6.4.5 "
            "with generic filing-native product recall recovery, hygiene, and semantic dedupe."
        )
    )

    parser.add_argument(
        "--scope",
        choices=(
            "published",
            "strategic",
        ),
        default="strategic",
        help=(
            "published: current production cohort; "
            "strategic: translation-eligible strategic census cohort "
            "from translation_universe_census_v2640.json."
        ),
    )

    parser.add_argument(
        "--symbol",
        action="append",
        default=[],
        help=(
            "Optional explicit symbol. Repeat for "
            "multiple symbols. Overrides --scope."
        ),
    )

    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Atomically replace the generated V2 profile "
            "indexes after the entire target cohort builds."
        ),
    )

    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Allow writing successfully generated companies "
            "even when some targets fail. Do not use for "
            "production migration."
        ),
    )

    parser.add_argument(
        "--full-report",
        action="store_true",
        help=(
            "Print the legacy full batch report. "
            "By default dry-run prints only compact "
            "census summary and diagnostic samples."
        ),
    )

    parser.add_argument(
        "--diagnostic-limit",
        type=int,
        default=12,
        help=(
            "Maximum samples per diagnostic class "
            "in compact dry-run output."
        ),
    )

    parser.add_argument(
        "--worst-limit",
        type=int,
        default=20,
        help=(
            "Maximum worst records shown in compact "
            "dry-run output."
        ),
    )

    args = parser.parse_args()

    explicit_symbols = [
        str(
            symbol
        ).strip().upper()
        for symbol in args.symbol
        if str(
            symbol
        ).strip()
    ]

    batch_scope = (
        "published"
        if args.scope == "published"
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

    public = _public_report(
        report
    )

    product_recall_policy = {
        "version": "v2.6.4.9",
        "principles": [
            "filing_native_named_products_only",
            "no_company_specific_product_dictionary",
            "preserve_product_families_and_brands",
            "reject_environmental_hr_sec_pollution",
            "clean_market_products_before_publish",
            "strip_sentence_fragments_from_product_stack",
            "preserve_complete_named_product_families",
            "drop_generic_category_when_specific_named_peer_exists",
            "semantic_near_duplicate_suppression",
        ],
    }

    report[
        "product_recall_policy"
    ] = product_recall_policy

    public[
        "product_recall_policy"
    ] = product_recall_policy

    if args.write:
        try:
            outputs = (
                write_company_profile_batch(
                    ROOT,
                    report,
                    allow_partial=(
                        args.allow_partial
                    ),
                )
            )
        except CompanyProfileBatchError as exc:
            public[
                "write_status"
            ] = "blocked"

            public[
                "write_error"
            ] = str(exc)

            print(
                json.dumps(
                    public,
                    ensure_ascii=False,
                    indent=2,
                )
            )

            return 2

        public[
            "write_status"
        ] = "written"

        public[
            "outputs"
        ] = outputs

    output = public

    if (
        not args.write
        and not args.full_report
    ):
        output = _compact_census_report(
            report,
            sample_limit=max(
                1,
                args.diagnostic_limit,
            ),
            worst_limit=max(
                1,
                args.worst_limit,
            ),
        )

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


if __name__ == "__main__":
    raise SystemExit(main())