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



_PRODUCT_SECTION_HEADINGS = (
    "products and services",
    "our products",
    "printing systems",
    "fdm printers",
    "polyjet printers",
    "stereolithography printers",
    "origin p3 printers",
    "saf printers",
    "consumable materials",
    "fdm materials",
    "polyjet materials",
    "stereolithography materials",
    "software",
    "our services",
    "range of technologies and differentiating factors",
    "range of solutions",
)

_PRODUCT_SECTION_TERMINATORS = (
    "customers",
    "marketing",
    "sales distribution methods",
    "manufacturing and suppliers",
    "research and development",
    "intellectual property",
    "competition",
    "seasonality",
    "global operations",
    "employees",
    "government regulation",
    "environmental, social, and governance",
)

_MODEL_TOKEN_RE = re.compile(
    r"\b(?:"
    r"[A-Z]{1,8}\d{1,4}[A-Z0-9+-]*"
    r"|[A-Z]{1,6}\d{2,5}[a-z]{0,3}"
    r"|[A-Z][A-Za-z]{1,15}\s+\d{1,4}[A-Za-z0-9+-]*"
    r")\b"
)

_PRODUCT_FAMILY_HEAD_RE = re.compile(
    r"\b(?:"
    r"FDM|PolyJet|P3|SAF|SLA|stereolithography|"
    r"retimer|retimers|controller|controllers|switch|switches|"
    r"processor|processors|accelerator|accelerators|"
    r"FPGA|FPGAs|SoC|SoCs|GPU|GPUs|CPU|CPUs|NIC|NICs|DPU|DPUs|"
    r"printer|printers|printing system|printing systems|"
    r"software platform|software suite|materials platform"
    r")\b",
    flags=re.IGNORECASE,
)


def _section_lines(
    text: str,
) -> list[str]:
    return [
        re.sub(
            r"\s+",
            " ",
            line,
        ).strip()
        for line in str(text or "").splitlines()
        if re.sub(
            r"\s+",
            " ",
            line,
        ).strip()
    ]


def _is_heading_like(
    line: str,
) -> bool:
    value = line.strip()

    if not value:
        return False

    lower = value.casefold().rstrip(".:")

    if lower in _PRODUCT_SECTION_HEADINGS:
        return True

    if lower in _PRODUCT_SECTION_TERMINATORS:
        return True

    if len(value) > 90:
        return False

    words = value.split()

    if len(words) > 10:
        return False

    # SEC filing section headings are commonly short title-like lines.
    alpha_words = [
        word
        for word in words
        if re.search(
            r"[A-Za-z]",
            word,
        )
    ]

    if not alpha_words:
        return False

    title_like = sum(
        bool(
            re.match(
                r"^[A-Z][A-Za-z0-9/&()+.-]*$",
                word,
            )
        )
        for word in alpha_words
    )

    return (
        title_like
        >= max(
            1,
            len(alpha_words) - 1,
        )
    )


def _product_section_blocks(
    text: str,
) -> list[str]:
    lines = _section_lines(
        text
    )

    blocks = []
    active = False
    buffer: list[str] = []

    for line in lines:
        lower = (
            line.casefold()
            .rstrip(".:")
        )

        if lower in _PRODUCT_SECTION_HEADINGS:
            if buffer:
                blocks.append(
                    " ".join(
                        buffer
                    )
                )
                buffer = []

            active = True
            buffer.append(
                line
            )
            continue

        if (
            active
            and lower
            in _PRODUCT_SECTION_TERMINATORS
        ):
            if buffer:
                blocks.append(
                    " ".join(
                        buffer
                    )
                )

            buffer = []
            active = False
            continue

        if active:
            buffer.append(
                line
            )

    if buffer:
        blocks.append(
            " ".join(
                buffer
            )
        )

    return [
        block
        for block
        in blocks
        if len(block) >= 80
    ]



_PRODUCT_DATE_FRAGMENT_RE = re.compile(
    r"^(?:(?:In|Throughout|During|Since|As of)\s+)?"
    r"(?:(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+)?"
    r"(?:19|20)\d{2}$",
    flags=re.IGNORECASE,
)

_PRODUCT_BASED_DESCRIPTOR_RE = re.compile(
    r"^[A-Za-z0-9®™+.-]+-based$",
    flags=re.IGNORECASE,
)

_PRODUCT_DANGLING_FRAGMENT_RE = re.compile(
    r"^(?:Printer|Printers|Series\s+3D|One\s+3D|Prime\s+3D|"
    r"Pro\s+3D|Stratasys\s+3D|PolyJet\s+3D|FDM\s+3D|"
    r"Industry\s+\d+(?:\.\d+)?)$",
    flags=re.IGNORECASE,
)


def _is_precision_noise_product(
    value: str,
) -> bool:
    text = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip(" ,;:.")

    if not text:
        return True

    return bool(
        _PRODUCT_DATE_FRAGMENT_RE.fullmatch(text)
        or _PRODUCT_BASED_DESCRIPTOR_RE.fullmatch(text)
        or _PRODUCT_DANGLING_FRAGMENT_RE.fullmatch(text)
    )


def _precision_clean_products(
    values: list[str],
) -> list[str]:
    cleaned = []

    for value in values:
        text = _normalize_product_candidate(
            str(value)
        )

        if not text:
            continue

        if _is_precision_noise_product(text):
            continue

        if _LOCATION_PRODUCT_RE.fullmatch(text):
            continue

        cleaned.append(text)

    # Keep family + named members. Only remove existing semantic duplicates.
    return _semantic_dedupe_products(cleaned)


def _extract_inline_model_products(
    text: str,
) -> tuple[
    list[str],
    list[str],
]:
    products: list[str] = []
    evidence: list[str] = []

    for sentence in _sentences(
        text
    ):
        if _blocked_product_context(
            sentence
        ):
            continue

        lower = sentence.casefold()

        if not (
            _PRODUCT_FAMILY_HEAD_RE.search(
                sentence
            )
            or any(
                token in lower
                for token in (
                    "models",
                    "series",
                    "printers",
                    "platform",
                    "software",
                    "systems",
                )
            )
        ):
            continue

        # Pull obvious trademarked/title-case product names and model tokens.
        candidates = []

        for match in re.finditer(
            r"\b(?:"
            r"[A-Z][A-Za-z0-9+.-]*"
            r"(?:\s+[A-Z][A-Za-z0-9+.-]*){0,4}"
            r")"
            r"(?:™|®)?"
            r"\b",
            sentence,
        ):
            value = match.group(0).strip()

            if (
                len(value) >= 2
                and (
                    _MODEL_TOKEN_RE.search(
                        value
                    )
                    or _PRODUCT_FAMILY_HEAD_RE.search(
                        value
                    )
                    or "™" in value
                    or "®" in value
                )
            ):
                candidates.append(
                    value
                )

        # Also collect compact model tokens from list-style sentences.
        for match in _MODEL_TOKEN_RE.finditer(
            sentence
        ):
            candidates.append(
                match.group(0)
            )

        for candidate in candidates:
            candidate = (
                _normalize_product_candidate(
                    candidate
                )
            )

            if (
                candidate
                and len(
                    candidate.split()
                )
                <= 8
                and not _blocked_product_context(
                    candidate
                )
            ):
                products.append(
                    candidate
                )
                evidence.append(
                    sentence
                )

    return (
        _semantic_dedupe_products(
            products
        ),
        _dedupe(
            evidence
        ),
    )



_SUBJECT_GATED_ALLOWED_SUBJECT_RE = re.compile(
    r"(?:"
    r"products?|product lines?|product portfolio|portfolio of products|"
    r"components?|semiconductors?|passive components?|"
    r"mosfets? product line|diodes? business|diodes? products?|"
    r"software products?|software offerings?|"
    r"systems?|printing systems?|printers?|"
    r"materials?|consumables?|services?"
    r")",
    flags=re.IGNORECASE,
)

_SUBJECT_GATED_BLOCKED_SUBJECT_RE = re.compile(
    r"(?:"
    r"applications?|projects?|competitors?|competition|customers?|"
    r"markets?|facilities?|manufacturing|capacity|capacities|"
    r"acquisitions?|suppliers?|employees?|workforce|sites?|"
    r"factories?|operations?|segments?|channels?|"
    r"research and development|r&d|strategies?|initiatives?"
    r")",
    flags=re.IGNORECASE,
)

_SUBJECT_GATED_CUE_RE = re.compile(
    r"\b(?:"
    r"include|includes|including|"
    r"consist of|consists of|"
    r"comprise|comprises|"
    r"offer|offers|offering"
    r")\b",
    flags=re.IGNORECASE,
)

_SUBJECT_GATED_PRODUCT_HEADS = (
    "mosfet",
    "mosfets",
    "diode",
    "diodes",
    "rectifier",
    "rectifiers",
    "thyristor",
    "thyristors",
    "scr",
    "scrs",
    "resistor",
    "resistors",
    "inductor",
    "inductors",
    "capacitor",
    "capacitors",
    "optoelectronic",
    "infrared",
    "sensor",
    "sensors",
    "photodiode",
    "photodiodes",
    "power module",
    "power modules",
    "power ic",
    "power ics",
    "integrated circuit",
    "integrated circuits",
    "semiconductor",
    "semiconductors",
    "passive component",
    "passive components",
    "printer",
    "printers",
    "software",
    "platform",
    "suite",
    "sdk",
    "retimer",
    "retimers",
    "controller",
    "controllers",
    "switch",
    "switches",
    "accelerator",
    "accelerators",
    "processor",
    "processors",
    "gpu",
    "gpus",
    "cpu",
    "cpus",
    "fpga",
    "fpgas",
    "soc",
    "socs",
    "nic",
    "nics",
    "dpu",
    "dpus",
)


def _subject_before_cue(
    sentence: str,
    cue_start: int,
) -> str:
    prefix = sentence[
        :cue_start
    ]

    # Keep only the most local clause before the cue.
    prefix = re.split(
        r"[.;:]",
        prefix,
    )[-1]

    prefix = re.sub(
        r"\s+",
        " ",
        prefix,
    ).strip()

    return prefix


def _subject_is_product_role(
    subject: str,
) -> bool:
    if not subject:
        return False

    if _SUBJECT_GATED_BLOCKED_SUBJECT_RE.search(
        subject
    ):
        return False

    return (
        _SUBJECT_GATED_ALLOWED_SUBJECT_RE.search(
            subject
        )
        is not None
    )


def _clean_subject_gated_piece(
    piece: str,
) -> str:
    value = re.sub(
        r"^[\s•·\-–—:]+",
        "",
        str(piece or ""),
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip(
        " ,.;:-"
    )

    # Drop common lead-in determiners/adjectives that are not part of the
    # product noun phrase itself.
    value = re.sub(
        r"^(?:"
        r"our|the|a|an|"
        r"broad range of|wide range of|selection of|portfolio of"
        r")\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )

    # Stop at obvious non-product subordinate clauses.
    value = re.split(
        r"\b(?:"
        r"used for|used in|for use in|serving|targeting|"
        r"which|that|where|with applications in"
        r")\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    return _normalize_product_candidate(
        value
    )


def _subject_gated_piece_allowed(
    value: str,
) -> bool:
    if not value:
        return False

    lower = value.casefold()

    if len(
        value.split()
    ) > 12:
        return False

    if _is_precision_noise_product(
        value
    ):
        return False

    if _LOCATION_PRODUCT_RE.fullmatch(
        value
    ):
        return False

    if any(
        marker in lower
        for marker
        in (
            "competitor",
            "competitors",
            "manufacturing",
            "capacity",
            "capacities",
            "application",
            "applications",
            "site in",
            "factory",
            "customer",
            "customers",
            "market",
            "markets",
        )
    ):
        return False

    # Require an explicit commercial head or a filing-native brand/model
    # signal. This keeps the list extraction precision-first.
    if not (
        any(
            head in lower
            for head
            in _SUBJECT_GATED_PRODUCT_HEADS
        )
        or _has_brand_signal(
            value
        )
    ):
        return False

    return True


def _extract_subject_gated_product_lists(
    text: str,
) -> tuple[
    list[str],
    list[str],
]:
    products: list[str] = []
    evidence: list[str] = []

    for sentence in _sentences(
        text
    ):
        if _blocked_product_context(
            sentence
        ):
            continue

        for cue in _SUBJECT_GATED_CUE_RE.finditer(
            sentence
        ):
            subject = _subject_before_cue(
                sentence,
                cue.start(),
            )

            if not _subject_is_product_role(
                subject
            ):
                continue

            tail = sentence[
                cue.end():
            ].strip()

            if not tail:
                continue

            # Keep the immediate noun-list clause only.
            tail = re.split(
                r"[.;]",
                tail,
                maxsplit=1,
            )[0]

            # Normalize list separators. Parentheses are retained because
            # product acronyms such as MOSFETs / power ICs can matter.
            pieces = re.split(
                r",|;|\band\b",
                tail,
                flags=re.IGNORECASE,
            )

            for piece in pieces:
                value = _clean_subject_gated_piece(
                    piece
                )

                if not _subject_gated_piece_allowed(
                    value
                ):
                    continue

                products.append(
                    value
                )
                evidence.append(
                    sentence
                )

    return (
        _semantic_dedupe_products(
            products
        ),
        _dedupe(
            evidence
        ),
    )


def _extract_section_aware_products(
    text: str,
) -> tuple[
    list[str],
    list[str],
]:
    products: list[str] = []
    evidence: list[str] = []

    for block in _product_section_blocks(
        text
    ):
        # Reuse the existing named product extractor semantics within
        # product-specific filing blocks by applying local sentence scans.
        inline_products, inline_evidence = (
            _extract_inline_model_products(
                block
            )
        )

        products.extend(
            inline_products
        )
        evidence.extend(
            inline_evidence
        )

        # Explicit family/platform names in section prose.
        for sentence in _sentences(
            block
        ):
            if _blocked_product_context(
                sentence
            ):
                continue

            family_patterns = (
                r"\b(FDM(?:®)?(?:\s+printers?|\s+systems?)?)\b",
                r"\b(PolyJet(?:™)?(?:\s+printers?|\s+systems?)?)\b",
                r"\b(P3(?:™)?(?:\s+platform|\s+printers?)?)\b",
                r"\b(SAF(?:™)?(?:\s+technology|\s+printers?)?)\b",
                r"\b(Neo(?:®)?(?:\s+(?:range|series|printers?))?)\b",
                r"\b(Origin(?:®)?(?:\s+(?:One|Two))?)\b",
                r"\b(GrabCAD(?:®)?\s+(?:Print(?:\s+Pro)?|Streamline Pro|IoT Platform|Community|SDK))\b",
            )

            for pattern in family_patterns:
                for match in re.finditer(
                    pattern,
                    sentence,
                    flags=re.IGNORECASE,
                ):
                    value = (
                        _normalize_product_candidate(
                            match.group(1)
                        )
                    )

                    if value:
                        products.append(
                            value
                        )
                        evidence.append(
                            sentence
                        )

    return (
        _semantic_dedupe_products(
            products
        ),
        _dedupe(
            evidence
        ),
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

        if (
            _product_candidate_allowed(
                text
            )
            and not _LOCATION_PRODUCT_RE.fullmatch(
                text
            )
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

    section_products, section_evidence = (
        _extract_section_aware_products(
            raw_text
        )
    )

    subject_products, subject_evidence = (
        _extract_subject_gated_product_lists(
            raw_text
        )
    )

    discovered = (
        _semantic_dedupe_products(
            discovered
            + section_products
            + subject_products
        )
    )

    discovered_evidence = _dedupe(
        discovered_evidence
        + section_evidence
        + subject_evidence
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
        "version": "v2.6.5.7",
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

        products = _precision_clean_products(
            list(
                profile.get(
                    "product_stack"
                )
                or []
            )
        )

        profile[
            "product_stack"
        ] = products

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
    r"North America|South America|Middle East|Africa|"
    r"Europe and Middle East|Asia Pacific|APAC|EMEA"
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



# === V2.6.5.6 STRATEGIC / MAJOR-TECH PRODUCTION GATE ===

CORE_TECH_THEME_IDS = {
    "theme:ai_infrastructure",
    "theme:artificial_intelligence",
    "theme:advanced_semiconductors",
}

MAJOR_TECH_SYMBOLS = (
    "NVDA",
    "AMD",
    "AVGO",
    "QCOM",
    "MRVL",
    "ALAB",
    "ARM",
    "TSM",
    "ASML",
    "MU",
    "ANET",
    "CRDO",
    "VRT",
    "SMCI",
    "DELL",
    "MSFT",
    "GOOGL",
    "GOOG",
    "AMZN",
    "META",
    "ORCL",
    "AAPL",
    "PLTR",
    "SNPS",
    "CDNS",
    "AMAT",
    "LRCX",
    "KLAC",
    "ADI",
    "MCHP",
    "NXPI",
    "INTC",
)

_HARD_NON_PRODUCT_PREFIX_RE = re.compile(
    r"^(?:"
    r"are\s+|is\s+|was\s+|were\s+|"
    r"functionality\s+of\s+|"
    r"completeness\s+of\s+|"
    r"properties\s+listed\s+below|"
    r"following\s+the\s+|"
    r"throughout\s+|"
    r"yet\s+|"
    r"via\s+|"
    r"also\s+the\s+|"
    r"supporting\s+|"
    r"designed\s+to\s+|"
    r"intended\s+to\s+|"
    r"used\s+to\s+|"
    r"used\s+for\s+"
    r")",
    flags=re.IGNORECASE,
)

_HARD_NON_PRODUCT_CONTAINS = (
    " described in the previous sentence",
    " listed below:",
    " location:",
    " employee",
    " employees",
    " competitor",
    " competitors",
    " manufacturing expansion",
    " capacity expansion",
    " applications include ",
)

_SOFT_DESCRIPTOR_CONTAINS = (
    " data bandwidth",
    " lower latency ",
    " interconnectivity between ",
    " software design tools",
    " applicable software solutions",
    " user experience with ",
    " feedback software",
)

_MAJOR_TECH_GATE_PRIORITY = {
    "theme:ai_infrastructure": 0,
    "theme:artificial_intelligence": 0,
    "theme:advanced_semiconductors": 0,
    "theme:advanced_communications": 1,
    "theme:physical_ai": 1,
    "theme:autonomous_vehicles": 1,
    "theme:quantum_computing": 1,
    "theme:robotics": 2,
    "theme:space_economy": 2,
    "theme:clean_energy": 2,
}


def _translation_candidate_metadata() -> dict[str, dict]:
    if not TRANSLATION_CENSUS.is_file():
        return {}

    payload = _load_json(
        TRANSLATION_CENSUS
    )

    rows = payload.get(
        "translation_candidates"
    ) or []

    output = {}

    for row in rows:
        if not isinstance(
            row,
            dict,
        ):
            continue

        symbol = str(
            row.get("symbol")
            or row.get("ticker")
            or ""
        ).strip().upper()

        if not symbol:
            continue

        output[symbol] = {
            "symbol": symbol,
            "company_id": row.get(
                "company_id"
            ),
            "display_name": row.get(
                "display_name"
            ),
            "theme_id": row.get(
                "theme_id"
            ),
            "theme_name": row.get(
                "theme_name"
            ),
            "theme_zh_tw": row.get(
                "theme_zh_tw"
            ),
            "priority": row.get(
                "priority"
            ),
            "classification_authority": bool(
                row.get(
                    "classification_authority"
                )
            ),
            "classification_review_required": bool(
                row.get(
                    "classification_review_required"
                )
            ),
        }

    return output


def _quality_issue_rows(
    row: dict,
) -> list[dict]:
    symbol = str(
        row.get("symbol")
        or ""
    ).upper()

    products = _record_products(
        row
    )

    issues: list[dict] = []

    if not products:
        return [
            {
                "type": "EMPTY_PRODUCT_STACK",
                "severity": "FAIL",
                "symbol": symbol,
                "value": "",
            }
        ]

    # Existing deterministic diagnostics remain authoritative.
    for issue in _product_quality_flags(
        row
    ):
        issues.append(
            {
                **issue,
                "severity": "REVIEW",
            }
        )

    for value in products:
        text = re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip()

        lower = text.casefold()

        if not text:
            continue

        if (
            _HARD_NON_PRODUCT_PREFIX_RE.search(
                text
            )
            or any(
                marker in lower
                for marker
                in _HARD_NON_PRODUCT_CONTAINS
            )
        ):
            issues.append(
                {
                    "type": "NON_PRODUCT_CLAUSE",
                    "severity": "REVIEW",
                    "symbol": symbol,
                    "value": text,
                }
            )
            continue

        if any(
            marker in lower
            for marker
            in _SOFT_DESCRIPTOR_CONTAINS
        ):
            issues.append(
                {
                    "type": "SUSPICIOUS_DESCRIPTOR",
                    "severity": "REVIEW",
                    "symbol": symbol,
                    "value": text,
                }
            )
            continue

        # Long prose-like items are review candidates, not automatic failures.
        if (
            len(
                text.split()
            ) >= 11
            and not _has_brand_signal(
                text
            )
        ):
            issues.append(
                {
                    "type": "SUSPICIOUS_LONG_PHRASE",
                    "severity": "REVIEW",
                    "symbol": symbol,
                    "value": text,
                }
            )

    return issues


def _company_quality_gate(
    row: dict,
) -> dict:
    products = _record_products(
        row
    )

    issues = _quality_issue_rows(
        row
    )

    fail_issues = [
        issue
        for issue
        in issues
        if issue.get(
            "severity"
        ) == "FAIL"
    ]

    review_issues = [
        issue
        for issue
        in issues
        if issue.get(
            "severity"
        ) == "REVIEW"
    ]

    generic_count = int(
        row.get(
            "generic_product_count"
        )
        or 0
    )

    if fail_issues:
        status = "FAIL"
    elif review_issues:
        status = "REVIEW"
    elif (
        products
        and generic_count
        >= len(products)
    ):
        status = "REVIEW"
        issues.append(
            {
                "type": "GENERIC_ONLY",
                "severity": "REVIEW",
                "symbol": str(
                    row.get("symbol")
                    or ""
                ).upper(),
                "value": "",
            }
        )
    else:
        status = "PASS"

    return {
        "status": status,
        "product_stack_count": len(
            products
        ),
        "generic_product_count": generic_count,
        "issue_count": len(
            issues
        ),
        "issue_types": sorted(
            {
                str(
                    issue.get(
                        "type"
                    )
                    or ""
                )
                for issue
                in issues
                if issue.get(
                    "type"
                )
            }
        ),
        "issue_samples": issues[:5],
    }


def _gate_summary(
    rows: list[dict],
) -> dict:
    counts = {
        "PASS": 0,
        "REVIEW": 0,
        "FAIL": 0,
    }

    for row in rows:
        status = str(
            row.get(
                "gate_status"
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

    pass_count = counts[
        "PASS"
    ]

    return {
        "total": total,
        "pass": pass_count,
        "review": counts[
            "REVIEW"
        ],
        "fail": counts[
            "FAIL"
        ],
        "pass_rate": (
            round(
                pass_count
                / total,
                4,
            )
            if total
            else 0.0
        ),
        "usable_rate": (
            round(
                (
                    pass_count
                    + counts[
                        "REVIEW"
                    ]
                )
                / total,
                4,
            )
            if total
            else 0.0
        ),
    }


def _strategic_production_gate(
    report: dict,
    *,
    sample_limit: int = 12,
) -> dict:
    records = report.get(
        "records"
    ) or []

    metadata = (
        _translation_candidate_metadata()
    )

    rows = []

    for row in records:
        symbol = str(
            row.get("symbol")
            or ""
        ).upper()

        meta = metadata.get(
            symbol,
            {}
        )

        gate = _company_quality_gate(
            row
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
                "theme_zh_tw": meta.get(
                    "theme_zh_tw"
                ),
                "priority": meta.get(
                    "priority"
                ),
                "classification_authority": meta.get(
                    "classification_authority",
                    False,
                ),
                "gate_status": gate[
                    "status"
                ],
                "product_stack_count": gate[
                    "product_stack_count"
                ],
                "generic_product_count": gate[
                    "generic_product_count"
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
        row[
            "symbol"
        ]: row
        for row
        in rows
    }

    core_rows = [
        row
        for row
        in rows
        if row.get(
            "theme_id"
        )
        in CORE_TECH_THEME_IDS
    ]

    # Theme-level production readiness for the whole strategic universe.
    theme_rows: dict[
        str,
        list[dict],
    ] = {}

    for row in rows:
        theme_id = str(
            row.get(
                "theme_id"
            )
            or "unclassified"
        )

        theme_rows.setdefault(
            theme_id,
            [],
        ).append(
            row
        )

    theme_summary = []

    for theme_id, members in sorted(
        theme_rows.items(),
        key=lambda item: (
            _MAJOR_TECH_GATE_PRIORITY.get(
                item[0],
                99,
            ),
            item[0],
        ),
    ):
        example = members[0]

        theme_summary.append(
            {
                "theme_id": theme_id,
                "theme_name": example.get(
                    "theme_name"
                ),
                "theme_zh_tw": example.get(
                    "theme_zh_tw"
                ),
                **_gate_summary(
                    members
                ),
            }
        )

    major_rows = []

    for symbol in MAJOR_TECH_SYMBOLS:
        row = by_symbol.get(
            symbol
        )

        if row is None:
            major_rows.append(
                {
                    "symbol": symbol,
                    "gate_status": (
                        "NOT_IN_UNIVERSE"
                    ),
                }
            )
            continue

        major_rows.append(
            {
                "symbol": symbol,
                "theme_id": row.get(
                    "theme_id"
                ),
                "theme_name": row.get(
                    "theme_name"
                ),
                "gate_status": row.get(
                    "gate_status"
                ),
                "product_stack_count": row.get(
                    "product_stack_count"
                ),
                "issue_types": row.get(
                    "issue_types"
                ),
                "issue_samples": row.get(
                    "issue_samples"
                ),
            }
        )

    diagnostic_types = (
        "EMPTY_PRODUCT_STACK",
        "LOCATION_POLLUTION",
        "ORG_POLLUTION",
        "SENTENCE_FRAGMENT",
        "NON_PRODUCT_CLAUSE",
        "SUSPICIOUS_DESCRIPTOR",
        "SUSPICIOUS_LONG_PHRASE",
        "GENERIC_ONLY",
    )

    diagnostic_summary = {}

    for issue_type in diagnostic_types:
        matched = [
            row
            for row
            in rows
            if issue_type
            in row.get(
                "issue_types",
                [],
            )
        ]

        diagnostic_summary[
            issue_type
        ] = {
            "company_count": len(
                matched
            ),
            "samples": [
                {
                    "symbol": row[
                        "symbol"
                    ],
                    "theme_id": row.get(
                        "theme_id"
                    ),
                    "gate_status": row[
                        "gate_status"
                    ],
                    "issue_samples": [
                        issue
                        for issue
                        in row.get(
                            "issue_samples",
                            []
                        )
                        if issue.get(
                            "type"
                        ) == issue_type
                    ][:2],
                }
                for row
                in matched[
                    :sample_limit
                ]
            ],
        }

    # P0 theme rows that need review/fail are the immediate production queue.
    core_attention = [
        {
            "symbol": row[
                "symbol"
            ],
            "theme_id": row.get(
                "theme_id"
            ),
            "gate_status": row[
                "gate_status"
            ],
            "product_stack_count": row[
                "product_stack_count"
            ],
            "issue_types": row[
                "issue_types"
            ],
            "issue_samples": row[
                "issue_samples"
            ],
        }
        for row
        in core_rows
        if row[
            "gate_status"
        ] != "PASS"
    ][
        :max(
            sample_limit,
            30,
        )
    ]

    return {
        "gate_version": "v2.6.5.7",
        "definitions": {
            "core_tech_theme_ids": sorted(
                CORE_TECH_THEME_IDS
            ),
            "PASS": (
                "non-empty product stack with no detected "
                "product-quality issue"
            ),
            "REVIEW": (
                "usable product stack but one or more "
                "quality warnings require review"
            ),
            "FAIL": (
                "empty product stack or hard extraction failure"
            ),
        },
        "strategic_universe": (
            _gate_summary(
                rows
            )
        ),
        "core_tech_subset": (
            _gate_summary(
                core_rows
            )
        ),
        "theme_summary": theme_summary,
        "major_tech_gate": major_rows,
        "core_tech_attention": core_attention,
        "diagnostics": diagnostic_summary,
    }


def _compact_census_report(
    report: dict,
    *,
    sample_limit: int = 12,
    worst_limit: int = 20,
    expand_symbols: set[str] | None = None,
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

    expanded_records = []

    expand_symbols = {
        str(symbol).upper()
        for symbol
        in (
            expand_symbols
            or set()
        )
    }

    if expand_symbols:
        for row in records:
            symbol = str(
                row.get("symbol")
                or ""
            ).upper()

            if symbol not in expand_symbols:
                continue

            expanded_records.append(
                {
                    "symbol": symbol,
                    "product_stack_count": len(
                        _record_products(
                            row
                        )
                    ),
                    "generic_product_count": int(
                        row.get(
                            "generic_product_count"
                        )
                        or 0
                    ),
                    "product_stack_full": _precision_clean_products(
                        _record_products(
                            row
                        )
                    ),
                }
            )

    production_gate = _strategic_production_gate(
        report,
        sample_limit=sample_limit,
    )

    return {
        "schema_version": (
            "axiom-company-profile-product-census.v2.6.5.7"
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
        "production_gate": production_gate,
        "expanded_records": expanded_records,
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



def _pct_text(
    value: float,
) -> str:
    return (
        f"{value * 100:.1f}%"
    )


def _one_screen_gate_summary(
    report: dict,
) -> str:
    gate = _strategic_production_gate(
        report,
        sample_limit=12,
    )

    lines = [
        "=== V2.6.5.7 Major-Tech Production Gate ===",
        "",
    ]

    strategic = gate[
        "strategic_universe"
    ]

    lines.extend(
        [
            "Strategic universe",
            (
                f"  Total {strategic['total']:>6}   "
                f"PASS {strategic['pass']:>6}   "
                f"REVIEW {strategic['review']:>6}   "
                f"FAIL {strategic['fail']:>6}"
            ),
            (
                f"  Pass rate {_pct_text(strategic['pass_rate'])}   "
                f"Usable rate {_pct_text(strategic['usable_rate'])}"
            ),
            "",
        ]
    )

    core = gate[
        "core_tech_subset"
    ]

    lines.extend(
        [
            "Core AI / Tech",
            (
                f"  Total {core['total']:>6}   "
                f"PASS {core['pass']:>6}   "
                f"REVIEW {core['review']:>6}   "
                f"FAIL {core['fail']:>6}"
            ),
            (
                f"  Pass rate {_pct_text(core['pass_rate'])}   "
                f"Usable rate {_pct_text(core['usable_rate'])}"
            ),
            "",
            "Core themes",
        ]
    )

    core_theme_ids = {
        "theme:ai_infrastructure",
        "theme:artificial_intelligence",
        "theme:advanced_semiconductors",
    }

    for row in gate[
        "theme_summary"
    ]:
        if row.get(
            "theme_id"
        ) not in core_theme_ids:
            continue

        name = (
            row.get(
                "theme_name"
            )
            or row.get(
                "theme_id"
            )
            or "unknown"
        )

        lines.append(
            (
                f"  {name[:28]:<28} "
                f"{row['pass']:>4}/{row['total']:<4} PASS   "
                f"{_pct_text(row['pass_rate']):>6}"
            )
        )

    lines.extend(
        [
            "",
            "Major Tech",
        ]
    )

    for row in gate[
        "major_tech_gate"
    ]:
        symbol = row[
            "symbol"
        ]

        status = row[
            "gate_status"
        ]

        if status == "NOT_IN_UNIVERSE":
            lines.append(
                f"  {symbol:<6} NOT_IN_UNIVERSE"
            )
            continue

        issue_types = row.get(
            "issue_types"
        ) or []

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

    lines.extend(
        [
            "",
            "Top blockers",
        ]
    )

    blocker_order = (
        "EMPTY_PRODUCT_STACK",
        "NON_PRODUCT_CLAUSE",
        "SENTENCE_FRAGMENT",
        "SUSPICIOUS_DESCRIPTOR",
        "SUSPICIOUS_LONG_PHRASE",
        "LOCATION_POLLUTION",
        "ORG_POLLUTION",
        "GENERIC_ONLY",
    )

    diagnostics = gate[
        "diagnostics"
    ]

    for issue_type in blocker_order:
        count = (
            diagnostics.get(
                issue_type,
                {},
            ).get(
                "company_count",
                0,
            )
        )

        lines.append(
            f"  {issue_type:<28} {count:>4}"
        )

    attention = gate.get(
        "core_tech_attention"
    ) or []

    if attention:
        lines.extend(
            [
                "",
                "Core-tech attention",
            ]
        )

        for row in attention[
            :20
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
                    f"{row['gate_status']:<7} "
                    f"{issue_types}"
                )
            )

    return "\n".join(
        lines
    )


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

    parser.add_argument(
        "--one-screen",
        action="store_true",
        help=(
            "Print only the compact V2.6.5.7 production-gate summary."
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
        "version": "v2.6.5.7",
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
            "section_aware_product_recall",
            "model_and_platform_recovery",
            "drop_geography_from_product_stack",
            "final_stage_geography_guard",
            "explicit_symbol_full_product_diagnostics",
            "drop_date_fragments",
            "drop_based_descriptors",
            "drop_dangling_product_fragments",
            "preserve_family_member_hierarchy",
            "subject_gated_product_list_recall",
            "block_application_project_competitor_subjects",
            "strategic_universe_quality_gate",
            "core_tech_p0_production_gate",
            "major_tech_frontend_gate",
            "non_product_clause_diagnostics",
            "one_screen_major_tech_gate_summary",
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

    explicit_symbols = {
        str(symbol).strip().upper()
        for symbol
        in args.symbol
        if str(symbol).strip()
    }

    if (
        not args.write
        and not args.full_report
        and (
            args.one_screen
            or (
                args.scope == "strategic"
                and not explicit_symbols
            )
        )
    ):
        print(
            _one_screen_gate_summary(
                report
            )
        )
    else:
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
                expand_symbols=explicit_symbols,
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