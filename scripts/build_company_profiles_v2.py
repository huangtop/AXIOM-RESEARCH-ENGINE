#!/usr/bin/env python3
"""
V2.6.6.2b — Product Stack Production Sanitizer + Diagnostics + Company Summary Semantic Selector

This file intentionally freezes the V2.6.5.7 extractor implementation at the
known-good repository commit fa9f64c341eda97e457c4178686b6409b12dae33 and
overlays promotion-only quality logic.

Important:
- extractor semantics are not changed here;
- extractor product_stack is never rewritten; production writes pass through a deterministic sanitizer;
- PROMOTE / REVIEW / FAIL controls production promotion only;
- OpenAI is not used by this script.

The frozen source is loaded from the repository's own Git object database.
That keeps this handoff file small while making the extractor freeze explicit
and reproducible.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from urllib.parse import quote
from pathlib import Path
from typing import Any

from axiom_engine.company_profile_v2.core import (
    _clean_text as _core_clean_text,
    _latest_business_evidence as _core_latest_business_evidence,
    _load_business_evidence as _core_load_business_evidence,
)
from axiom_engine.company_profile_v2.provenance import (
    build_value_provenance as _core_build_value_provenance,
)


ROOT = Path(__file__).resolve().parents[1]

FROZEN_V2657_COMMIT = (
    "fa9f64c341eda97e457c4178686b6409b12dae33"
)
FROZEN_SCRIPT_PATH = (
    "scripts/build_company_profiles_v2.py"
)

CANONICAL_ROOT = (
    ROOT / "data/generated/company_profile_v2"
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


# The frozen extractor remains the production recall path.  Tighten its
# candidate promotion gate in-place so actor/entity roles and corporate job
# titles never become products, including during cleanup and recall merging.
_frozen_product_candidate_allowed = _V2657[
    "_product_candidate_allowed"
]

_PRODUCT_ACTOR_ROLE_RE = re.compile(
    r"^(?:[A-Za-z0-9/&+.-]+\s+){0,5}"
    r"(?:providers?|customers?|distributors?|suppliers?|operators?|"
    r"integrators?|employees?|personnel|vendors?|partners?)$",
    flags=re.IGNORECASE,
)

_PRODUCT_ROLE_SAFE_HEAD_RE = re.compile(
    r"\b(?:products?|platforms?|accelerators?|software|systems?|solutions?|"
    r"devices?|modules?|components?|equipment)\b",
    flags=re.IGNORECASE,
)

_CORPORATE_JOB_TITLE_RE = re.compile(
    r"^(?:(?:Executive|Senior|Assistant|Associate|Interim|Corporate|Division|"
    r"Regional|Global|Group)\s+)*(?:Vice President|President|Controller|"
    r"Chief (?:Executive|Financial|Operating|Technology|Accounting) Officer)$",
    flags=re.IGNORECASE,
)


def _product_candidate_allowed(
    value: str,
) -> bool:
    candidate = _V2657[
        "_normalize_product_candidate"
    ](value)

    if _CORPORATE_JOB_TITLE_RE.fullmatch(candidate):
        return False

    if (
        _PRODUCT_ACTOR_ROLE_RE.fullmatch(candidate)
        and not _PRODUCT_ROLE_SAFE_HEAD_RE.search(candidate)
    ):
        return False

    return _frozen_product_candidate_allowed(candidate)


_V2657[
    "_product_candidate_allowed"
] = _product_candidate_allowed

_frozen_enrich_profile_product_recall = _V2657[
    "_enrich_profile_product_recall"
]


def _enrich_profile_product_recall(
    profile: dict[str, Any],
) -> dict[str, Any]:
    enriched = _frozen_enrich_profile_product_recall(profile)
    enriched["product_stack"] = [
        value
        for value in enriched.get("product_stack") or []
        if not (
            _PRODUCT_ACTOR_ROLE_RE.fullmatch(str(value).strip())
            and not _PRODUCT_ROLE_SAFE_HEAD_RE.search(str(value))
        )
        and not _CORPORATE_JOB_TITLE_RE.fullmatch(str(value).strip())
    ]
    return enriched


_V2657[
    "_enrich_profile_product_recall"
] = _enrich_profile_product_recall


# === V2.6.6.0 COMPANY SUMMARY SEMANTIC SELECTOR ===========================

SUMMARY_SELECTOR_VERSION = "v2.6.6.1c"

_SUMMARY_HEADING_PREFIX_RE = re.compile(
    r"^(?:"
    r"BUSINESS\s+|"
    r"ITEM\s+1\.?\s+BUSINESS\s+|"
    r"COMPANY\s+OVERVIEW(?:,\s*STRATEGY\s+AND\s+MISSION)?\s+|"
    r"OVERVIEW\s+|"
    r"OUR\s+BUSINESS\s+"
    r")+",
    flags=re.IGNORECASE,
)

_SUMMARY_STRONG_IDENTITY_RE = re.compile(
    r"\b(?:"
    r"we\s+(?:are|design|develop|manufacture|market|provide|offer|supply|deliver|operate|sell)|"
    r"the\s+company\s+(?:is|designs|develops|manufactures|markets|provides|offers|supplies|delivers|operates|sells)|"
    r"[A-Z][A-Za-z0-9&.' -]{1,80}\s+(?:"
    r"is\s+(?:a|an)\s+|"
    r"designs?|develops?|manufactures?|markets?|provides?|offers?|supplies|delivers?|operates?|sells"
    r")"
    r")",
    flags=re.IGNORECASE,
)

_SUMMARY_BUSINESS_NOUN_RE = re.compile(
    r"\b(?:"
    r"semiconductor|software|hardware|platform|products?|services?|solutions?|"
    r"systems?|infrastructure|technology|technologies|memory|storage|network|"
    r"networking|equipment|devices?|processors?|manufacturing|foundry|cloud|"
    r"data\s+center|artificial\s+intelligence|AI|electronics|connectivity"
    r")\b",
    flags=re.IGNORECASE,
)

_SUMMARY_BAD_PATTERNS = (
    (
        "INCORPORATION_OR_HEADQUARTERS",
        re.compile(
            r"\b(?:"
            r"incorporated\s+in|"
            r"Delaware\s+corporation|"
            r"headquartered\s+in|"
            r"headquarters?\s+(?:is|are|in)"
            r")\b",
            flags=re.IGNORECASE,
        ),
        -90,
    ),
    (
        "COMPETITIVE_ADVANTAGE",
        re.compile(
            r"\b(?:"
            r"competitive\s+advantage|"
            r"we\s+believe\s+that\s+our\s+(?:scale|capacity|technology|position)|"
            r"differentiating\s+its\s+business"
            r")\b",
            flags=re.IGNORECASE,
        ),
        -100,
    ),
    (
        "IP_OR_PERSONNEL",
        re.compile(
            r"\b(?:"
            r"intellectual\s+property|patents?|trademarks?|"
            r"innovative\s+skills|technical\s+competence|"
            r"marketing\s+abilities\s+of\s+(?:its|our)\s+personnel"
            r")\b",
            flags=re.IGNORECASE,
        ),
        -100,
    ),
    (
        "FOUNDERS_LETTER",
        re.compile(
            r"\b(?:"
            r"founders?'?\s+letter|"
            r"our\s+founders?|"
            r"not\s+a\s+conventional\s+company"
            r")\b",
            flags=re.IGNORECASE,
        ),
        -100,
    ),
    (
        "SEGMENT_ONLY",
        re.compile(
            r"\bour\s+[A-Z0-9][A-Za-z0-9& -]{0,40}\s+segment\b",
            flags=re.IGNORECASE,
        ),
        -85,
    ),
    (
        "STRATEGY_ONLY",
        re.compile(
            r"\b(?:"
            r"our\s+.+?\s+strategy\s+is|"
            r"strategic\s+priority|"
            r"fundamental\s+pivot"
            r")\b",
            flags=re.IGNORECASE,
        ),
        -65,
    ),
    (
        "MISSION_ONLY",
        re.compile(
            r"^\s*(?:our\s+)?mission\s+is\b",
            flags=re.IGNORECASE,
        ),
        -25,
    ),
    (
        "LEGAL_OR_FINANCIAL",
        re.compile(
            r"\b(?:"
            r"form\s+10-k|fiscal\s+year|net\s+sales|revenue|"
            r"securities|litigation|risk\s+factors?"
            r")\b",
            flags=re.IGNORECASE,
        ),
        -55,
    ),
)


def _strip_summary_heading(
    value: str,
) -> str:
    text = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()

    previous = None

    while (
        text
        and text != previous
    ):
        previous = text
        text = _SUMMARY_HEADING_PREFIX_RE.sub(
            "",
            text,
            count=1,
        ).strip(" :-—")

    return text


def _summary_sentences(
    text: str,
) -> list[str]:
    clean = re.sub(
        r"\s+",
        " ",
        str(text or ""),
    ).strip()

    if not clean:
        return []

    clean = re.sub(
        r'([.!?])(["”’\'])\s+(?=[A-Z0-9])',
        r"\1\2\n",
        clean,
    )

    raw_sentences = []

    for chunk in clean.splitlines():
        raw_sentences.extend(
            re.split(
                r"(?<=[.!?])\s+(?=[A-Z0-9])",
                chunk,
            )
        )

    output = []

    for raw in raw_sentences:
        sentence = _strip_summary_heading(
            raw
        )

        sentence = sentence.strip()

        if not sentence:
            continue

        output.append(
            sentence
        )

    return output


def _summary_sentence_score(
    sentence: str,
    *,
    position: int,
) -> tuple[int, list[str]]:
    text = _strip_summary_heading(
        sentence
    )

    words = text.split()

    if len(words) < 7:
        return (
            -999,
            ["TOO_SHORT"],
        )

    if len(words) > 90:
        return (
            -999,
            ["TOO_LONG"],
        )

    score = 0
    reasons = []

    if _SUMMARY_STRONG_IDENTITY_RE.search(
        text
    ):
        score += 80
        reasons.append(
            "BUSINESS_IDENTITY"
        )

    business_terms = len(
        {
            match.group(0).casefold()
            for match in _SUMMARY_BUSINESS_NOUN_RE.finditer(
                text
            )
        }
    )

    if business_terms:
        score += min(
            35,
            business_terms * 7,
        )
        reasons.append(
            "BUSINESS_TERMS"
        )

    if re.search(
        r"\b(?:"
        r"leader|leading|provider|supplier|developer|manufacturer|"
        r"designs?|develops?|manufactures?|markets?|provides?|offers?|"
        r"supplies|delivers?|operates?|sells"
        r")\b",
        text,
        flags=re.IGNORECASE,
    ):
        score += 20
        reasons.append(
            "OPERATING_VERB"
        )

    if position < 20:
        score += max(
            0,
            12 - position // 2,
        )

    for (
        reason,
        pattern,
        penalty,
    ) in _SUMMARY_BAD_PATTERNS:
        if pattern.search(
            text
        ):
            score += penalty
            reasons.append(
                reason
            )

    if re.search(
        r"^\s*(?:although|while|because|however|therefore)\b",
        text,
        flags=re.IGNORECASE,
    ):
        score -= 25
        reasons.append(
            "DEPENDENT_OR_TRANSITIONAL"
        )

    return (
        score,
        reasons,
    )


_SUMMARY_HARD_BAD_REASONS = {
    "INCORPORATION_OR_HEADQUARTERS",
    "COMPETITIVE_ADVANTAGE",
    "FOUNDERS_LETTER",
    "SEGMENT_ONLY",
    "LEGAL_OR_FINANCIAL",
}

# These reasons describe a sentence that may be useful evidence, but is not
# eligible to become the one-line company identity on its own.  In V2.6.6.1a
# a weak incumbent can open a challenge, but it cannot waive this floor.
_SUMMARY_CHALLENGER_DISQUALIFIERS = {
    "COMPANY_HISTORY",
    "CUSTOMER_DESCRIPTION",
    "PRODUCT_OR_APPLICATION_DETAIL",
    "PILLAR_OR_SECTION_DETAIL",
    "SEGMENT_DETAIL",
    "SEGMENT_ONLY",
    "LEGAL_OR_FINANCIAL",
    "INCORPORATION_OR_HEADQUARTERS",
    "COMPETITIVE_ADVANTAGE",
    "FOUNDERS_LETTER",
}

_SUMMARY_DETAIL_PATTERNS = (
    (
        "COMPANY_HISTORY",
        re.compile(
            r"\b(?:"
            r"over\s+the\s+next\s+decade|"
            r"expanded\s+through\s+acquisitions?|"
            r"founded\s+in|"
            r"formerly\s+known\s+as"
            r")\b",
            flags=re.IGNORECASE,
        ),
        -95,
    ),
    (
        "CUSTOMER_DESCRIPTION",
        re.compile(
            r"^\s*(?:"
            r"our\s+customer\s+base\s+includes|"
            r"our\s+customers?\s+include"
            r")\b",
            flags=re.IGNORECASE,
        ),
        -55,
    ),
    (
        "PRODUCT_OR_APPLICATION_DETAIL",
        re.compile(
            r"\b(?:"
            r"our\s+key\s+product\s+lines\s+include|"
            r"our\s+solutions\s+are\s+deployed\s+in|"
            r"our\s+offerings\s+include|"
            r"applications?\s+such\s+as|"
            r"for\s+both\s+premium\s+and\s+mainstream\s+product\s+applications|"
            r"provides?\s+customers?\s+with\s+comprehensive\s+specialty\s+technologies"
            r")\b",
            flags=re.IGNORECASE,
        ),
        -45,
    ),
    (
        "PILLAR_OR_SECTION_DETAIL",
        re.compile(
            r"^\s*(?:"
            r"design\s+excellence:|"
            r"system\s+innovation:|"
            r"core\s+EDA\b|"
            r"products?\s+by\s+business\s+unit\b|"
            r"custom\s+ASICs\b|"
            r"processors?\b"
            r")",
            flags=re.IGNORECASE,
        ),
        -75,
    ),
    (
        "SEGMENT_DETAIL",
        re.compile(
            r"\b(?:"
            r"AGS\s+segment|"
            r"semiconductor\s+systems\s+segment|"
            r"reportable\s+segments?"
            r")\b",
            flags=re.IGNORECASE,
        ),
        -80,
    ),
)

_SUMMARY_COMPANY_LEVEL_RE = re.compile(
    r"\b(?:"
    r"global\s+(?:technology|semiconductor|industry|infrastructure)\s+leader|"
    r"leading\s+supplier|"
    r"global\s+supplier|"
    r"provider\s+of\s+(?:total\s+IT|critical\s+digital|technology|semiconductor)|"
    r"leader\s+in\s+the\s+global\s+technology\s+industry|"
    r"industry\s+leader\s+in|"
    r"we\s+are\s+(?:an?\s+)?(?:global\s+)?(?:leader|provider|supplier)|"
    r"is\s+(?:a|an)\s+(?:global\s+)?(?:leader|provider|supplier)"
    r")\b",
    flags=re.IGNORECASE,
)

_SUMMARY_PLATFORM_OR_BUSINESS_MODEL_RE = re.compile(
    r"\b(?:"
    r"full-stack\s+approach|"
    r"platform\s+(?:delivers|provides|enables|supports)|"
    r"AI-optimized\s+infrastructure|"
    r"critical\s+digital\s+infrastructure|"
    r"data\s+infrastructure\s+semiconductor\s+solutions|"
    r"memory\s+and\s+storage\s+solutions|"
    r"network-as-a-service|"
    r"materials\s+engineering\s+solutions|"
    r"wafer\s+fabrication\s+equipment\s+and\s+services"
    r")\b",
    flags=re.IGNORECASE,
)


def _summary_quality_score(
    sentence: str,
    *,
    position: int = 0,
) -> dict:
    score, reasons = _summary_sentence_score(
        sentence,
        position=position,
    )

    text = _strip_summary_heading(
        sentence
    )

    detail_reasons = []

    for (
        reason,
        pattern,
        penalty,
    ) in _SUMMARY_DETAIL_PATTERNS:
        if pattern.search(text):
            score += penalty
            reasons.append(reason)
            detail_reasons.append(reason)

    if _SUMMARY_COMPANY_LEVEL_RE.search(text):
        score += 45
        reasons.append("COMPANY_LEVEL_SCOPE")

    if _SUMMARY_PLATFORM_OR_BUSINESS_MODEL_RE.search(text):
        score += 30
        reasons.append("BUSINESS_MODEL_OR_PLATFORM")

    hard_bad = bool(
        _SUMMARY_HARD_BAD_REASONS
        & set(reasons)
    )

    return {
        "sentence": text,
        "score": score,
        "reasons": reasons,
        "hard_bad": hard_bad,
        "detail_reasons": detail_reasons,
    }


def _summary_challenger_eligibility(
    evaluation: dict,
) -> dict:
    reasons = set(
        evaluation.get("reasons")
        or []
    )

    blockers = sorted(
        reasons
        & _SUMMARY_CHALLENGER_DISQUALIFIERS
    )

    has_identity = (
        "BUSINESS_IDENTITY" in reasons
    )
    has_business_terms = (
        "BUSINESS_TERMS" in reasons
    )
    has_operating_verb = (
        "OPERATING_VERB" in reasons
    )
    has_company_scope = (
        "COMPANY_LEVEL_SCOPE" in reasons
        or "BUSINESS_MODEL_OR_PLATFORM" in reasons
    )

    semantic_floor = (
        has_identity
        and has_business_terms
        and has_operating_verb
    ) or (
        has_company_scope
        and has_business_terms
        and has_operating_verb
    )

    eligible = (
        not blockers
        and not evaluation.get("hard_bad")
        and semantic_floor
    )

    if blockers:
        reason = "DETAIL_OR_BOILERPLATE"
    elif evaluation.get("hard_bad"):
        reason = "HARD_BAD"
    elif not semantic_floor:
        reason = "NO_COMPANY_LEVEL_SEMANTIC_FLOOR"
    else:
        reason = "ELIGIBLE"

    return {
        "eligible": eligible,
        "reason": reason,
        "blockers": blockers,
        "semantic_floor": semantic_floor,
    }


_SUMMARY_GOOD_EXISTING_MIN_SCORE = 80
_SUMMARY_GOOD_EXISTING_DELTA = 70

_SUMMARY_CANDIDATE_FILING_PROSE_RE = re.compile(
    r"(?:"
    r"^\s*(?:these|those|this|such)\s+(?:include|includes|are)\b|"
    r"•|"
    r"\b(?:"
    r"as\s+part\s+of\s+our\s+evolution|"
    r"designed\s+to\s+support|"
    r"applications?\s+such\s+as"
    r")\b"
    r")",
    flags=re.IGNORECASE,
)


def _candidate_summary_eligibility(
    candidate_eval: dict,
) -> dict:
    reasons = list(
        candidate_eval.get("reasons")
        or []
    )

    blockers = []

    blocker_reasons = {
        "COMPANY_HISTORY",
        "CUSTOMER_DESCRIPTION",
        "PRODUCT_OR_APPLICATION_DETAIL",
        "PILLAR_OR_SECTION_DETAIL",
        "SEGMENT_DETAIL",
    }

    for reason in reasons:
        if reason in blocker_reasons:
            blockers.append(reason)

    sentence = str(
        candidate_eval.get("sentence")
        or ""
    )

    if _SUMMARY_CANDIDATE_FILING_PROSE_RE.search(
        sentence
    ):
        blockers.append(
            "FILING_PROSE_OR_BULLET"
        )

    if candidate_eval.get("hard_bad"):
        blockers.append(
            "HARD_BAD_CANDIDATE"
        )

    blockers = sorted(
        set(blockers)
    )

    company_level = (
        "COMPANY_LEVEL_SCOPE" in reasons
        or "BUSINESS_MODEL_OR_PLATFORM" in reasons
    )

    if blockers:
        return {
            "eligible": False,
            "reason": "BLOCKED_DETAIL_OR_FILING_PROSE",
            "blockers": blockers,
            "company_level": company_level,
        }

    if not (
        "BUSINESS_IDENTITY" in reasons
        and (
            "OPERATING_VERB" in reasons
            or company_level
        )
    ):
        return {
            "eligible": False,
            "reason": "INSUFFICIENT_COMPANY_LEVEL_IDENTITY",
            "blockers": [
                "INSUFFICIENT_COMPANY_LEVEL_IDENTITY"
            ],
            "company_level": company_level,
        }

    return {
        "eligible": True,
        "reason": "ELIGIBLE",
        "blockers": [],
        "company_level": company_level,
    }


def _good_existing_summary(
    existing_eval: dict,
) -> bool:
    reasons = set(
        existing_eval.get("reasons")
        or []
    )

    if existing_eval.get("hard_bad"):
        return False

    if (
        existing_eval.get("score", -999)
        < _SUMMARY_GOOD_EXISTING_MIN_SCORE
    ):
        return False

    return (
        "COMPANY_LEVEL_SCOPE" in reasons
        or "BUSINESS_MODEL_OR_PLATFORM" in reasons
    )


def _select_company_summary(
    text: str,
) -> dict:
    candidates = []

    for position, sentence in enumerate(
        _summary_sentences(
            text
        )
    ):
        score, reasons = (
            _summary_sentence_score(
                sentence,
                position=position,
            )
        )

        candidates.append(
            {
                "sentence": sentence,
                "score": score,
                "position": position,
                "reasons": reasons,
            }
        )

    hard_block_reasons = {
        "INCORPORATION_OR_HEADQUARTERS",
        "COMPETITIVE_ADVANTAGE",
        "IP_OR_PERSONNEL",
        "FOUNDERS_LETTER",
        "SEGMENT_ONLY",
        "LEGAL_OR_FINANCIAL",
    }

    eligible = [
        row
        for row in candidates
        if row["score"] > 0
        and not (
            hard_block_reasons
            & set(row["reasons"])
        )
        and (
            "BUSINESS_IDENTITY"
            in row["reasons"]
            or (
                "OPERATING_VERB"
                in row["reasons"]
                and "BUSINESS_TERMS"
                in row["reasons"]
            )
        )
    ]

    if not eligible:
        return {
            "selected": None,
            "score": None,
            "position": None,
            "reasons": [
                "NO_SEMANTIC_SUMMARY_CANDIDATE"
            ],
            "top_candidates": sorted(
                candidates,
                key=lambda row: (
                    -row["score"],
                    row["position"],
                ),
            )[:5],
        }

    selected = max(
        eligible,
        key=lambda row: (
            row["score"],
            -row["position"],
        ),
    )

    return {
        "selected":
            selected["sentence"],
        "score":
            selected["score"],
        "position":
            selected["position"],
        "reasons":
            selected["reasons"],
        "top_candidates":
            sorted(
                candidates,
                key=lambda row: (
                    -row["score"],
                    row["position"],
                ),
            )[:5],
    }


def _challenge_company_summary(
    *,
    existing_summary: str,
    text: str,
) -> dict:
    existing_clean = _strip_summary_heading(
        existing_summary
    )

    existing_eval = _summary_quality_score(
        existing_clean,
        position=0,
    )

    selection = _select_company_summary(
        text
    )

    candidate = selection.get("selected")

    if not candidate:
        decision = (
            "CLEAN"
            if (
                existing_clean
                and existing_clean != existing_summary
            )
            else (
                "KEEP"
                if existing_clean
                else "REVIEW"
            )
        )

        return {
            "decision": decision,
            "selected_summary": (
                existing_clean
                if decision in {"KEEP", "CLEAN"}
                else None
            ),
            "existing_score": existing_eval["score"],
            "candidate_score": None,
            "score_delta": None,
            "existing_reasons": existing_eval["reasons"],
            "candidate_reasons": [],
            "candidate_eligible": False,
            "candidate_eligibility_reason": "NO_CANDIDATE",
            "candidate_blockers": ["NO_CANDIDATE"],
            "good_existing": _good_existing_summary(
                existing_eval
            ),
            "top_candidates": (
                selection.get("top_candidates")
                or []
            ),
        }

    candidate_eval = _summary_quality_score(
        candidate,
        position=int(
            selection.get("position")
            or 0
        ),
    )

    eligibility = _candidate_summary_eligibility(
        candidate_eval
    )

    delta = (
        candidate_eval["score"]
        - existing_eval["score"]
    )

    good_existing = _good_existing_summary(
        existing_eval
    )

    if existing_eval["hard_bad"]:
        decision = (
            "REPLACE"
            if eligibility["eligible"]
            else "REVIEW"
        )
    elif (
        existing_clean != existing_summary
        and (
            good_existing
            or not eligibility["eligible"]
            or delta < _SUMMARY_GOOD_EXISTING_DELTA
        )
    ):
        decision = "CLEAN"
    elif good_existing:
        decision = (
            "REPLACE"
            if (
                eligibility["eligible"]
                and delta >= _SUMMARY_GOOD_EXISTING_DELTA
            )
            else "KEEP"
        )
    elif (
        eligibility["eligible"]
        and delta >= 35
    ):
        decision = "REPLACE"
    else:
        decision = (
            "KEEP"
            if existing_clean
            else "REVIEW"
        )

    if decision == "REPLACE":
        selected_summary = candidate_eval["sentence"]
    elif decision in {"KEEP", "CLEAN"}:
        selected_summary = existing_clean
    else:
        selected_summary = None

    return {
        "decision": decision,
        "selected_summary": selected_summary,
        "existing_score": existing_eval["score"],
        "candidate_score": candidate_eval["score"],
        "score_delta": delta,
        "existing_reasons": existing_eval["reasons"],
        "candidate_reasons": candidate_eval["reasons"],
        "candidate_eligible": eligibility["eligible"],
        "candidate_eligibility_reason": eligibility["reason"],
        "candidate_blockers": eligibility["blockers"],
        "good_existing": good_existing,
        "top_candidates": (
            selection.get("top_candidates")
            or []
        ),
    }


def _apply_company_summary_semantic_selector(
    report: dict,
) -> list[dict]:
    diagnostics = []

    profiles = (
        report.get("_canonical_profiles")
        or []
    )

    for profile in profiles:
        symbol = str(
            profile.get("symbol")
            or ""
        ).strip().upper()

        company_id = str(
            profile.get("company_id")
            or ""
        ).strip()

        old_summary = str(
            (
                profile.get("company_summary")
                or {}
            ).get("one_line_business")
            or ""
        ).strip()

        try:
            evidence_rows = _core_load_business_evidence(
                ROOT,
                company_id,
            )

            evidence = _core_latest_business_evidence(
                evidence_rows,
                symbol,
            )

            raw_text = str(
                evidence.get("text")
                or ""
            )

            clean_text = _core_clean_text(
                raw_text
            )

            challenge = _challenge_company_summary(
                existing_summary=old_summary,
                text=clean_text,
            )

        except Exception as exc:
            diagnostics.append(
                {
                    "symbol": symbol,
                    "old_summary": old_summary,
                    "selected_summary": None,
                    "decision": "ERROR",
                    "changed": False,
                    "status": "ERROR",
                    "error": str(exc),
                }
            )
            continue

        decision = challenge["decision"]
        selected = challenge.get(
            "selected_summary"
        )

        changed = bool(
            selected
            and selected != old_summary
        )

        if (
            selected
            and decision in {
                "REPLACE",
                "CLEAN",
                "KEEP",
            }
        ):
            profile.setdefault(
                "company_summary",
                {},
            )["one_line_business"] = selected

            profile.setdefault(
                "field_evidence",
                {},
            )[
                "company_summary.one_line_business"
            ] = [selected]

            profile["value_provenance"] = (
                _core_build_value_provenance(
                    profile=profile,
                    raw_text=raw_text,
                    evidence=evidence,
                )
            )

            profile["company_summary_selector"] = {
                "version": SUMMARY_SELECTOR_VERSION,
                "mode": "conservative_sec_item1_challenger",
                "decision": decision,
                "existing_score": challenge.get("existing_score"),
                "candidate_score": challenge.get("candidate_score"),
                "score_delta": challenge.get("score_delta"),
                "existing_reasons": challenge.get("existing_reasons"),
                "candidate_reasons": challenge.get("candidate_reasons"),
                "candidate_eligible": challenge.get("candidate_eligible"),
                "candidate_eligibility_reason": challenge.get(
                    "candidate_eligibility_reason"
                ),
                "candidate_blockers": challenge.get("candidate_blockers"),
                "good_existing": challenge.get("good_existing"),
            }

        diagnostics.append(
            {
                "symbol": symbol,
                "old_summary": old_summary,
                "selected_summary": selected,
                "decision": decision,
                "changed": changed,
                "status": decision,
                "error": None,
                "existing_score": challenge.get("existing_score"),
                "candidate_score": challenge.get("candidate_score"),
                "score_delta": challenge.get("score_delta"),
                "existing_reasons": challenge.get("existing_reasons"),
                "candidate_reasons": challenge.get("candidate_reasons"),
                "candidate_eligible": challenge.get("candidate_eligible"),
                "candidate_eligibility_reason": challenge.get(
                    "candidate_eligibility_reason"
                ),
                "candidate_blockers": challenge.get("candidate_blockers"),
                "good_existing": challenge.get("good_existing"),
                "top_candidates": challenge.get("top_candidates"),
            }
        )

    report["_summary_selector_diagnostics"] = diagnostics
    return diagnostics


def _summary_diagnostics_payload(
    report: dict,
) -> dict:
    rows = (
        report.get(
            "_summary_selector_diagnostics"
        )
        or []
    )

    decision_counts = {}

    for row in rows:
        decision = str(
            row.get("decision")
            or row.get("status")
            or "UNKNOWN"
        )

        decision_counts[decision] = (
            decision_counts.get(
                decision,
                0,
            )
            + 1
        )

    return {
        "selector_version": SUMMARY_SELECTOR_VERSION,
        "company_count": len(rows),
        "selected_count": sum(
            1
            for row in rows
            if row.get("selected_summary")
        ),
        "changed_count": sum(
            1
            for row in rows
            if row.get("changed")
        ),
        "decision_counts": dict(
            sorted(
                decision_counts.items()
            )
        ),
        "rows": rows,
    }



# === V2.6.6.2 PRODUCT STACK PRODUCTION SANITIZER ==========================

PRODUCT_SANITIZER_VERSION = "v2.6.6.2c-batch1"

_PRODUCT_SANITIZER_EXACT_RE = re.compile(
    r"^(?:"
    r"form\s+10-k|"
    r"geographic\s+information|"
    r"software-defined"
    r")$",
    flags=re.IGNORECASE,
)

_PRODUCT_SANITIZER_FINANCIAL_NOTE_RE = re.compile(
    r"(?:"
    r"\bsee\s+note\s+\d+\b|"
    r"\bnotes?\s+to\s+(?:the\s+)?consolidated\s+financial\s+statements\b|"
    r"\bfinancial\s+statements?\s+contained\s+in\s+part\s+[ivx]+\b|"
    r"\bpart\s+[ivx]+\b.*\bfinancial\s+statements?\b"
    r")",
    flags=re.IGNORECASE,
)

_PRODUCT_SANITIZER_HR_OR_FACILITY_RE = re.compile(
    r"(?:"
    r"\bhealth\s+clinics?\b|"
    r"\bemployee\s+health\b|"
    r"\bworkplace\s+health\b"
    r")",
    flags=re.IGNORECASE,
)

_PRODUCT_SANITIZER_DANGLING_PREFIX_RE = re.compile(
    r"^(?:"
    r"including\s+|"
    r"other\s+software\s+available\s+on\s+commercially\s+reasonable\s+terms$"
    r")",
    flags=re.IGNORECASE,
)

_PRODUCT_SANITIZER_TRUNCATED_RE = re.compile(
    r"(?:"
    r"\bsolutions?\s+that\s+span\s+primary$|"
    r"\bspan\s+primary$"
    r")",
    flags=re.IGNORECASE,
)

_PRODUCT_SANITIZER_SECTION_FRAGMENT_RE = re.compile(
    r"^(?:"
    r"mixed\s+signal\s*[—-]\s*we\s+are\s+|"
    r"products?\s+by\s+business\s+unit\b"
    r")",
    flags=re.IGNORECASE,
)


_PRODUCT_SANITIZER_REGULATORY_RE = re.compile(
    r"(?:"
    r"\b(?:authorization|restriction|registration|evaluation)\s+of\s+chemicals\b|"
    r"\bSVHC\s+Substances\s+Directive\b|"
    r"\bRoHS\b.*\bDirective\b|"
    r"\bREACH\b.*\bDirective\b"
    r")",
    flags=re.IGNORECASE,
)

_PRODUCT_SANITIZER_REVENUE_PROSE_RE = re.compile(
    r"(?:"
    r"^\s*revenue\s+from\s+|"
    r"\blicensing\s+our\s+software\b"
    r")",
    flags=re.IGNORECASE,
)

_PRODUCT_SANITIZER_LOCATION_ONLY_RE = re.compile(
    r"^(?:"
    r"Hong\s+Kong|"
    r"those\s+in\s+the\s+Middle\s+East"
    r")$",
    flags=re.IGNORECASE,
)

_PRODUCT_SANITIZER_GENERIC_NON_PRODUCT_RE = re.compile(
    r"^(?:"
    r"strong\s+third-party\s+software|"
    r"consumer\s+electronics|"
    r"corporate\s+controller"
    r")$",
    flags=re.IGNORECASE,
)


# === V2.6.6.2c PRODUCTION SANITIZER PROMOTION BATCH 1 ====================
#
# Promoted from V2.6.6.2b-hp3 after:
# - targeted stress tests,
# - second-batch 20-company regression,
# - 338-company classification census,
# - 338-company read-only before/after simulation.
#
# These rules are intentionally limited to the seven highest-confidence
# contamination families. Geography section rules, regulatory-compliance
# prose, acquisition/business-context rules, customer/org ambiguity, and
# suspicious fragments remain diagnostics-only.
_PRODUCT_SANITIZER_V2662C_BATCH1_PATTERNS = (
    (
        "TABLE_OF_CONTENTS_OR_SECTION_LEAKAGE",
        re.compile(
            r"(?:\btable\s+of\s+contents\b|"
            r"^\s*(?:research\s*,?\s*)?development\s*[（(]?[\"“”']?R&D|"
            r"\br&d\s+activities?\s+focus\b|"
            r"^\s*(?:total\s+\d+|\([ivx]+\)\s+materialise\b)"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "SEC_OR_REPORT_DOCUMENT_LEAKAGE",
        re.compile(
            r"(?:\bsecurities\s+and\s+exchange\s+commission\b|"
            r"^\s*(?:annual\s+report|sustainability\s+report)\s*$|"
            r"^\s*exchange\s+commission\b)",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "REGULATORY_OR_CHEMICAL_LEAKAGE",
        re.compile(
            r"(?:^\s*(?:drug\s+administration|food\s+and\s+drug\s+administration)\b|"
            r"^\s*polybrominat(?:ed|el)\s+diphenyl\s+ethers?\b|"
            r"\bbis\s*\(2-ethylhexyl\)\s+phthalate\b)",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "STANDARDS_OR_CERTIFICATION_PROSE",
        re.compile(
            r"(?:^\s*designs?\s+tested\s+to\s+meet\b|"
            r"^\s*under\s+(?:both\s+)?the\s+american\s+national\s+standards\s+institute\b|"
            r"^\s*international\s+electrotechnical\s+commission\s*$|"
            r"^\s*(?:ISO\s+(?:9001|14001|45001)|SEMI\s+S[28]|S[28]|Directive\s+2006)\s*$)",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "ACCREDITATION_OR_CERTIFICATION_PROSE",
        re.compile(
            r"(?:"
            r"\baccredited\s+by\b|"
            r"\baccreditation\s+program\b|"
            r"\baccredited\s+test\s+lab(?:oratory)?\b|"
            r"\bproduct\s+tests?\s+(?:are\s+)?accredited\b|"
            r"\btesting\s+(?:is\s+)?accredited\b"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "CORPORATE_TITLE_LEAKAGE",
        re.compile(
            r"^\s*(?:corporate\s+vice\s+president|division\s+controller|corporate\s+controller)\s*$",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "EVENT_OR_INSTITUTION_LEAKAGE",
        re.compile(
            r"(?:\bworld\s+expo\s+\d{4}\b|^\s*smithsonian\s+institute\s*$)",
            flags=re.IGNORECASE,
        ),
    ),
)


def _product_sanitizer_v2662c_batch1_reason(
    text: str,
) -> str | None:
    for reason, pattern in _PRODUCT_SANITIZER_V2662C_BATCH1_PATTERNS:
        if pattern.search(text):
            return reason

    return None


def _product_sanitizer_reason(
    value: object,
) -> str | None:
    text = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()

    if not text:
        return "EMPTY_VALUE"

    if _PRODUCT_SANITIZER_EXACT_RE.fullmatch(
        text
    ):
        return "NON_PRODUCT_DOCUMENT_OR_FRAGMENT"

    if _PRODUCT_SANITIZER_FINANCIAL_NOTE_RE.search(
        text
    ):
        return "FINANCIAL_STATEMENT_NOTE"

    if _PRODUCT_SANITIZER_HR_OR_FACILITY_RE.search(
        text
    ):
        return "HR_OR_FACILITY_TEXT"

    if _PRODUCT_SANITIZER_DANGLING_PREFIX_RE.search(
        text
    ):
        return "DANGLING_CLAUSE"

    if _PRODUCT_SANITIZER_TRUNCATED_RE.search(
        text
    ):
        return "TRUNCATED_FRAGMENT"

    if _PRODUCT_SANITIZER_SECTION_FRAGMENT_RE.search(
        text
    ):
        return "SECTION_PROSE_FRAGMENT"

    if _PRODUCT_SANITIZER_REGULATORY_RE.search(
        text
    ):
        return "REGULATORY_OR_COMPLIANCE_TEXT"

    if _PRODUCT_SANITIZER_REVENUE_PROSE_RE.search(
        text
    ):
        return "REVENUE_OR_LICENSING_PROSE"

    if _PRODUCT_SANITIZER_LOCATION_ONLY_RE.fullmatch(
        text
    ):
        return "GEOGRAPHY_TEXT"

    if _PRODUCT_SANITIZER_GENERIC_NON_PRODUCT_RE.fullmatch(
        text
    ):
        return "GENERIC_NON_PRODUCT_TEXT"

    batch1_reason = (
        _product_sanitizer_v2662c_batch1_reason(
            text
        )
    )

    if batch1_reason:
        return (
            "V2662C_BATCH1_"
            + batch1_reason
        )

    return None


def _sanitize_product_stack_values(
    products: list[object],
) -> dict:
    kept = []
    removed = []
    seen = set()

    for raw_value in products:
        text = re.sub(
            r"\s+",
            " ",
            str(raw_value or ""),
        ).strip()

        reason = _product_sanitizer_reason(
            text
        )

        if reason:
            removed.append(
                {
                    "value": text,
                    "reason": reason,
                }
            )
            continue

        dedupe_key = text.casefold()

        if dedupe_key in seen:
            removed.append(
                {
                    "value": text,
                    "reason": "EXACT_DUPLICATE",
                }
            )
            continue

        seen.add(
            dedupe_key
        )
        kept.append(
            text
        )

    return {
        "kept": kept,
        "removed": removed,
        "before_count": len(products),
        "after_count": len(kept),
        "removed_count": len(removed),
    }


def _sanitize_profile_for_production(
    profile: dict,
) -> tuple[dict, dict]:
    sanitized = json.loads(
        json.dumps(
            profile,
            ensure_ascii=False,
        )
    )

    products = sanitized.get(
        "product_stack"
    )

    if not isinstance(
        products,
        list,
    ):
        products = []

    result = _sanitize_product_stack_values(
        products
    )

    sanitized[
        "product_stack"
    ] = result[
        "kept"
    ]

    sanitized[
        "product_stack_sanitizer"
    ] = {
        "version":
            PRODUCT_SANITIZER_VERSION,
        "mode":
            "deterministic_production_boundary",
        "promotion_batch":
            "V2.6.6.2c-batch1",
        "before_count":
            result[
                "before_count"
            ],
        "after_count":
            result[
                "after_count"
            ],
        "removed_count":
            result[
                "removed_count"
            ],
        "removed":
            result[
                "removed"
            ],
    }

    return (
        sanitized,
        result,
    )


def _product_sanitizer_diagnostics(
    profiles: list[dict],
) -> dict:
    rows = []

    for profile in profiles:
        sanitized, result = (
            _sanitize_profile_for_production(
                profile
            )
        )

        rows.append(
            {
                "symbol":
                    str(
                        profile.get(
                            "symbol"
                        )
                        or ""
                    ).strip().upper(),
                "before_count":
                    result[
                        "before_count"
                    ],
                "after_count":
                    result[
                        "after_count"
                    ],
                "removed_count":
                    result[
                        "removed_count"
                    ],
                "removed":
                    result[
                        "removed"
                    ],
                "blocked_empty_after_sanitize":
                    (
                        result[
                            "before_count"
                        ] > 0
                        and result[
                            "after_count"
                        ] == 0
                    ),
                "status":
                    (
                        "BLOCKED_EMPTY_AFTER_SANITIZE"
                        if (
                            result[
                                "before_count"
                            ] > 0
                            and result[
                                "after_count"
                            ] == 0
                        )
                        else (
                            "CHANGED"
                            if result[
                                "removed_count"
                            ] > 0
                            else "UNCHANGED"
                        )
                    ),
                "final_product_stack":
                    sanitized.get(
                        "product_stack"
                    )
                    or [],
            }
        )

    return {
        "sanitizer_version":
            PRODUCT_SANITIZER_VERSION,
        "company_count":
            len(
                rows
            ),
        "blocked_empty_company_count":
            sum(
                1
                for row in rows
                if row.get(
                    "blocked_empty_after_sanitize"
                )
            ),
        "changed_company_count":
            sum(
                1
                for row in rows
                if row[
                    "removed_count"
                ]
                > 0
            ),
        "removed_item_count":
            sum(
                row[
                    "removed_count"
                ]
                for row in rows
            ),
        "rows":
            rows,
    }



# === V2.6.6.2b PRODUCT STACK CONTAMINATION DIAGNOSTICS ====================

PRODUCT_CONTAMINATION_DIAGNOSTICS_VERSION = "v2.6.6.2c-core7-pr1"

PRODUCT_CONTAMINATION_CLASSIFICATION_VERSION = "v2.6.6.2b-hp3-classification1"

# Diagnostics-only classification layer.
# This does NOT participate in:
# - _product_sanitizer_reason()
# - _sanitize_profile_for_production()
# - canonical writes
# - promotion decisions
# - translation
#
# SAFE_AUTO_REMOVE means the reason family is considered structurally
# high-confidence enough to be a candidate for future production promotion.
# It is NOT automatically removed here.
#
# REVIEW_ONLY means the signal is useful for human review but is intentionally
# too ambiguous to mutate production data automatically.
_PRODUCT_CONTAMINATION_REASON_CLASSIFICATION = {
    "EMPTY_VALUE": "SAFE_AUTO_REMOVE",
    "TABLE_OF_CONTENTS_OR_SECTION_LEAKAGE": "SAFE_AUTO_REMOVE",
    "SEC_OR_REPORT_DOCUMENT_LEAKAGE": "SAFE_AUTO_REMOVE",
    "REGULATORY_OR_CHEMICAL_LEAKAGE": "SAFE_AUTO_REMOVE",
    "REGULATORY_COMPLIANCE_PROSE": "SAFE_AUTO_REMOVE",
    "GEOGRAPHY_LEAKAGE": "SAFE_AUTO_REMOVE",
    "GEOGRAPHY_SECTION_LEAKAGE": "SAFE_AUTO_REMOVE",
    "STANDARDS_OR_CERTIFICATION_PROSE": "SAFE_AUTO_REMOVE",
    "ACCREDITATION_OR_CERTIFICATION_PROSE": "SAFE_AUTO_REMOVE",
    "CORPORATE_TITLE_LEAKAGE": "SAFE_AUTO_REMOVE",
    "EVENT_OR_INSTITUTION_LEAKAGE": "SAFE_AUTO_REMOVE",
    "EXPORT_CONTROL_OR_PROHIBITION_PROSE": "SAFE_AUTO_REMOVE",

    "CUSTOMER_DISTRIBUTOR_OR_ORG_LEAKAGE": "REVIEW_ONLY",
    "OPERATING_SEGMENT_PROSE": "REVIEW_ONLY",
    "ACQUISITION_OR_CORPORATE_PROSE": "REVIEW_ONLY",
    "GENERIC_BUSINESS_CONTEXT": "REVIEW_ONLY",
    "SUSPICIOUS_FRAGMENT": "REVIEW_ONLY",
    "EXTERNAL_COMPANY_OR_ORG_LEAKAGE": "REVIEW_ONLY",
    "EXPORT_CONTROL_PROSE": "REVIEW_ONLY",
    "LICENSING_OR_LEGAL_PROSE": "REVIEW_ONLY",
    "SECTION_OR_ORG_PROSE": "REVIEW_ONLY",
}

def _product_contamination_reason_classification(
    reason: object,
) -> str:
    key = str(
        reason
        or ""
    ).strip()

    return (
        _PRODUCT_CONTAMINATION_REASON_CLASSIFICATION.get(
            key,
            "REVIEW_ONLY",
        )
    )

# Diagnostics only. These rules DO NOT participate in:
# - _product_sanitizer_reason()
# - _sanitize_profile_for_production()
# - canonical writes
# - promotion decisions
# - translation
# Existing V2.6.6.2a production behavior remains unchanged.
_PRODUCT_CONTAMINATION_DIAGNOSTIC_PATTERNS = (
    (
        "TABLE_OF_CONTENTS_OR_SECTION_LEAKAGE",
        re.compile(
            r"(?:\btable\s+of\s+contents\b|"
            r"^\s*(?:research\s*,?\s*)?development\s*[（(]?[\"“”']?R&D|"
            r"\br&d\s+activities?\s+focus\b|"
            r"^\s*(?:total\s+\d+|\([ivx]+\)\s+materialise\b)"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "SEC_OR_REPORT_DOCUMENT_LEAKAGE",
        re.compile(
            r"(?:\bsecurities\s+and\s+exchange\s+commission\b|"
            r"^\s*(?:annual\s+report|sustainability\s+report)\s*$|"
            r"^\s*exchange\s+commission\b)",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "REGULATORY_OR_CHEMICAL_LEAKAGE",
        re.compile(
            r"(?:^\s*(?:drug\s+administration|food\s+and\s+drug\s+administration)\b|"
            r"^\s*polybrominat(?:ed|el)\s+diphenyl\s+ethers?\b|"
            r"\bbis\s*\(2-ethylhexyl\)\s+phthalate\b)",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "REGULATORY_COMPLIANCE_PROSE",
        re.compile(
            r"(?:"
            r"\b(?:european\s+union(?:'s|’s)?\s+)?medical\s+device\s+directive\b|"
            r"\bsubmission\s+demonstrating\s+clinical\s+safety\b|"
            r"\brohs\b.{0,80}\bsubstances?\b|"
            r"\bquality\s+system\s+regulations?\b"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "GEOGRAPHY_LEAKAGE",
        re.compile(
            r"(?:^\s*(?:in\s+)?north\s+america\s*$|"
            r"^\s*(?:in\s+)?(?:latin\s+america|south\s+africa)\s*$|"
            r"^\s*(?:asia\s+pacific)(?:\s+region)?\s*$|"
            r"^\s*north\s+america\s+and\s+europe\s*$|"
            r"^\s*latin\s+america\s+and\s+israel\s*$)",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "GEOGRAPHY_SECTION_LEAKAGE",
        re.compile(
            r"(?:"
            r"^\s*geographies(?:\s+[\u200b\u200c\u200d\ufeff]*)?(?:\s+the\s+company\s+manufactures\b.*)?$|"
            r"^\s*asia[-\s]?pacific(?:\s*\([\"“”']?APAC[\"“”']?\))?\s*(?:region|regions)?\s*$|"
            r"^\s*(?:europe,\s*middle\s+east\s+and\s+africa|africa)(?:\s*\([\"“”']?EMEA[\"“”']?\))?\s*(?:region|regions)?\s*$|"
            r"\bauthorities?\s+located\s+in\s+the\s+united\s+states\b|"
            r"\bmanufacturing\s+services?\s+in\s+north\s+america\b"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "STANDARDS_OR_CERTIFICATION_PROSE",
        re.compile(
            r"(?:^\s*designs?\s+tested\s+to\s+meet\b|"
            r"^\s*under\s+(?:both\s+)?the\s+american\s+national\s+standards\s+institute\b|"
            r"^\s*international\s+electrotechnical\s+commission\s*$|"
            r"^\s*(?:ISO\s+(?:9001|14001|45001)|SEMI\s+S[28]|S[28]|Directive\s+2006)\s*$)",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "ACCREDITATION_OR_CERTIFICATION_PROSE",
        re.compile(
            r"(?:"
            r"\baccredited\s+by\b|"
            r"\baccreditation\s+program\b|"
            r"\baccredited\s+test\s+lab(?:oratory)?\b|"
            r"\bproduct\s+tests?\s+(?:are\s+)?accredited\b|"
            r"\btesting\s+(?:is\s+)?accredited\b"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "CORPORATE_TITLE_LEAKAGE",
        re.compile(
            r"^\s*(?:corporate\s+vice\s+president|division\s+controller|corporate\s+controller)\s*$",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "CUSTOMER_DISTRIBUTOR_OR_ORG_LEAKAGE",
        re.compile(
            r"^\s*(?:AT&T|Ingram\s+Micro|Contract\s+Manufacturers?|independent\s+software\s+vendors?)\s*$",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "OPERATING_SEGMENT_PROSE",
        re.compile(
            r"(?:"
            r"^\s*(?:[A-Za-z0-9&/+\- ]+\s+)?operating\s+segments?\s*$|"
            r"^\s*segment\s+description\b|"
            r"^\s*solutions?\s+described\s+below\s+within\s+our\b|"
            r"^\s*software\s+subject\s+to\s+various\s+open\s+source\s+software\s+licenses?\s*$"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "ACQUISITION_OR_CORPORATE_PROSE",
        re.compile(
            r"(?:"
            r"\bacquisition\s+of\s+[A-Z][A-Za-z0-9&.,'’\- ]{2,80}\b|"
            r"^\s*following\s+the\s+acquisition\s+of\b"
            r")",
        ),
    ),
    (
        "EXTERNAL_COMPANY_OR_ORG_LEAKAGE",
        re.compile(
            r"(?:"
            r"^\s*(?:Broadcom\s+Ltd|Arista\s+Networks|Cisco\s+Systems)\s*$|"
            r"^\s*\d+\s+Marvell\s+Technology\s*$|"
            r"^\s*Inc\.\s+and\s+Astera\s+Labs\s*$"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "EXPORT_CONTROL_PROSE",
        re.compile(
            r"(?:"
            r"^\s*United\s+States\s+export\s+controls?(?:\s+and\s+sanctions\s+laws)?\s*$|"
            r"^\s*any\s+China-specific\s+product\s+designed\s+to\s+comply\s+with\s+U\.?S\.?\s*$"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "LICENSING_OR_LEGAL_PROSE",
        re.compile(
            r"(?:"
            r"^\s*paid\s+licenses?\s+to\s+NVIDIA\s+AI\s+Enterprise\s*$|"
            r"^\s*software\s+or\s+other\s+intellectual\s+property\s+licensed\s+from\s+third\s+parties\s*$"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "SECTION_OR_ORG_PROSE",
        re.compile(
            r"(?:"
            r"^\s*as\s+described\s+below:\s*[•\-]\s*Communication\s+Services\s+Sales\s+Organization\s*$|"
            r"^\s*subscriber\s+retention\s+efforts\s*$|"
            r"^\s*all\s+leveraging\s+the\s+Company(?:'s|’s)\s+PILOT\s+diagnostic\s*$|"
            r"^\s*are\s+operated\s+by\s+Qualcomm\s+Technologies\s*$"
            r")",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "CORPORATE_TITLE_LEAKAGE",
        re.compile(
            r"^\s*assistant\s+controller\s*$",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "GENERIC_BUSINESS_CONTEXT",
        re.compile(
            r"(?:^\s*(?:storage|sell\s+software|as\s+a\s+whole\s+platform\s+offering|"
            r"architecture\s+description|these\s+socs|more\s+platform\s+solutions)\s*$|"
            r"^\s*primarily\s+for\s+the\s+semiconductor\s+device\s+manufacturers\s*$|"
            r"^\s*across\s+almost\s+every\s+major\s+process\s+in\s+semiconductor\s+manufacturing\s+today\s*$|"
            r"^\s*one\s+RF\s+component\s+plant\s+in\s+China\s*$)",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "EVENT_OR_INSTITUTION_LEAKAGE",
        re.compile(
            r"(?:\bworld\s+expo\s+\d{4}\b|^\s*smithsonian\s+institute\s*$)",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "EXPORT_CONTROL_OR_PROHIBITION_PROSE",
        re.compile(
            r"(?:^\s*prohibitions?\s+on\s+(?:their|the)\s+use\b|\bin\s+connection\s+with\s+nuclear\b)",
            flags=re.IGNORECASE,
        ),
    ),
)

_PRODUCT_CONTAMINATION_SUSPICIOUS_FRAGMENT_RE = re.compile(
    r"(?:\b\d+\s+table\s+of\s+contents\b|"
    r"\bfor\s*$|"
    r"^\s*(?:technical|communications)\s*$|"
    r"\bin\s+the\s+U\s*$|"
    r"^\s*passive\s+devices\s*\([^)]*$|"
    r"^\s*integrated\s+electronic\s*$|"
    r"^\s*accuracy\s+of\s+detection\s+sensors\s*\([^)]*$|"
    r"^\s*lattice\s+drive[™]?\s+for\s+advanced\s*$|"
    r"^\s*photonics\s+devices\s*\(\s*including\s+laser\s+diodes\s*$|"
    r"^\s*standard\s+brick\s+products\s+emphasizing\s+[\"“”']mass\s+customization\s*$|"
    r"^\s*each\s+controlled\s+by\s+a\s+series\s+of\s+mass\s+flow\s+controllers\s*$|"
    r"^\s*solutions?\s+described\s+below\s+within\s+our\s+networking\s+platforms\s*$|"
    r"^\s*are\s+based\s+on\s+AMD\s+CDNA[™]?\s+architecture\s*$|"
    r"^\s*functionality\s+of\s+software\s+design\s+tools\s*$|"
    r"^\s*completeness\s+of\s+applicable\s+software\s+solutions\s*$|"
    r"^\s*EV\s+market\s+under\s+the\s+DRIVE\s*$|"
    r"^\s*in\s+addition\s+to\s+\d+\s+discrete\s+filtering\s+products\s*$|"
    r"^\s*strong\s+oceanic\s+coverage\)\s+with\s+greater\s+redundancy\s*$)"
    , flags=re.IGNORECASE,
)



def _product_contamination_new_reason(
    value: object,
) -> str | None:
    text = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()

    if not text:
        return "EMPTY_VALUE"

    for reason, pattern in _PRODUCT_CONTAMINATION_DIAGNOSTIC_PATTERNS:
        if pattern.search(text):
            return reason

    if _PRODUCT_CONTAMINATION_SUSPICIOUS_FRAGMENT_RE.search(text):
        return "SUSPICIOUS_FRAGMENT"

    return None


def _product_contamination_diagnostics(
    profiles: list[dict],
) -> dict:
    rows = []

    for profile in profiles:
        symbol = str(
            profile.get("symbol")
            or ""
        ).strip().upper()

        products = profile.get("product_stack")
        if not isinstance(products, list):
            products = []

        production_flags = []
        new_flags = []
        post_v2662a = []

        for raw_value in products:
            text = re.sub(
                r"\s+",
                " ",
                str(raw_value or ""),
            ).strip()

            production_reason = _product_sanitizer_reason(text)

            if production_reason:
                production_flags.append(
                    {
                        "value": text,
                        "reason": production_reason,
                    }
                )
            else:
                post_v2662a.append(text)

            new_reason = _product_contamination_new_reason(text)

            if new_reason:
                new_flags.append(
                    {
                        "value": text,
                        "reason": new_reason,
                        "classification":
                            _product_contamination_reason_classification(
                                new_reason
                            ),
                    }
                )

        post_new_flags = [
            row
            for row in new_flags
            if row["value"] in post_v2662a
        ]

        blocked_empty_after_sanitize = (
            len(products) > 0
            and len(post_v2662a) == 0
        )

        if blocked_empty_after_sanitize:
            post_status = "BLOCKED_EMPTY_AFTER_SANITIZE"
        elif post_new_flags:
            post_status = "REVIEW"
        else:
            post_status = "CLEAN"

        rows.append(
            {
                "symbol": symbol,
                "product_count": len(products),
                "production_sanitizer_flag_count": len(
                    production_flags
                ),
                "production_sanitizer_flags": production_flags,
                "new_2b_flag_count": len(
                    new_flags
                ),
                "new_2b_flags": new_flags,
                "safe_auto_remove_flag_count": sum(
                    1
                    for row in new_flags
                    if row.get("classification")
                    == "SAFE_AUTO_REMOVE"
                ),
                "review_only_flag_count": sum(
                    1
                    for row in new_flags
                    if row.get("classification")
                    == "REVIEW_ONLY"
                ),
                "post_v2662a_product_count": len(
                    post_v2662a
                ),
                "blocked_empty_after_sanitize":
                    blocked_empty_after_sanitize,
                "post_v2662a_status": post_status,
                "post_v2662a_new_2b_flags": post_new_flags,
                "post_v2662a_product_stack": post_v2662a,
            }
        )

    return {
        "diagnostics_version":
            PRODUCT_CONTAMINATION_DIAGNOSTICS_VERSION,
        "classification_version":
            PRODUCT_CONTAMINATION_CLASSIFICATION_VERSION,
        "mode":
            "diagnostics_only_no_production_mutation",
        "classification_mode":
            "metadata_only_no_auto_remove",
        "company_count":
            len(rows),
        "post_v2662a_blocked_empty_company_count":
            sum(
                1
                for row in rows
                if row["post_v2662a_status"]
                == "BLOCKED_EMPTY_AFTER_SANITIZE"
            ),
        "post_v2662a_review_company_count":
            sum(
                1
                for row in rows
                if row["post_v2662a_status"]
                == "REVIEW"
            ),
        "post_v2662a_clean_company_count":
            sum(
                1
                for row in rows
                if row["post_v2662a_status"]
                == "CLEAN"
            ),
        "production_sanitizer_flagged_item_count":
            sum(
                row["production_sanitizer_flag_count"]
                for row in rows
            ),
        "new_2b_flagged_item_count":
            sum(
                row["new_2b_flag_count"]
                for row in rows
            ),
        "safe_auto_remove_flagged_item_count":
            sum(
                row["safe_auto_remove_flag_count"]
                for row in rows
            ),
        "review_only_flagged_item_count":
            sum(
                row["review_only_flag_count"]
                for row in rows
            ),
        "rows":
            rows,
    }


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

        if _PROMOTION_EMBEDDED_FILING_RE.search(
            text
        ):
            add(
                "PROMOTION_EMBEDDED_FILING_TEXT",
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



def _snapshot_records(payload: dict) -> list[dict]:
    records = payload.get("records")
    if isinstance(records, list):
        valid = [row for row in records if isinstance(row, dict)]
        if valid and all(isinstance(row.get("product_stack_full"), list) for row in valid):
            return valid
    raise ValueError(
        "snapshot has no complete record-level product stacks; "
        "expected records[].product_stack_full"
    )


def _report_from_snapshot(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("census snapshot root must be an object")
    records = _snapshot_records(payload)
    failures = payload.get("failures") or payload.get("failure_samples") or []
    return {
        "scope": "evidence",
        "_requested_scope": "strategic",
        "records": records,
        "failures": failures,
        "summary": {
            "target_company_count": payload.get("summary", {}).get("target_company_count", len(records)+len(failures)),
            "generated_company_count": len(records),
            "failed_company_count": len(failures),
            "complete": not failures,
        },
        "snapshot_source": str(path),
    }



# === V2.6.6.2c 7 CORE CANONICAL TARGETED REPAIR =========================

CORE7_TARGETED_REPAIR_VERSION = "v2.6.6.2c-core7-targeted-repair1"

CORE7_TARGETED_REPAIR_SYMBOLS = (
    "AMD",
    "AVGO",
    "CRDO",
    "LITE",
    "NVDA",
    "QCOM",
    "VSAT",
)

# Exact-value manifest only.
# This is intentionally NOT a global regex sanitizer.
CORE7_TARGETED_REPAIR_REMOVALS = {
    "AMD": (
        "are based on AMD CDNA™ architecture",
        "new Asus ROG Xbox Ally",
        "functionality of software design tools",
        "completeness of applicable software solutions",
    ),
    "AVGO": (
        "inductive charging devices. •RF Semiconductor Devices: Our devices selectively filter",
    ),
    "CRDO": (
        "Broadcom Ltd",
        "14 Marvell Technology",
        "Inc. and Astera Labs",
        "United States export controls and sanctions laws",
        "all leveraging the Company’s PILOT diagnostic",
        "United States export controls",
    ),
    "LITE": (),
    "NVDA": (
        "any China-specific product designed to comply with U.S",
        "Arista Networks",
        "Cisco Systems",
        "paid licenses to NVIDIA AI Enterprise",
        "EV market under the DRIVE",
    ),
    "QCOM": (
        "Qualcomm Dragonwing™ families of highly-integrated",
        "in addition to 8 discrete filtering products",
        "are operated by Qualcomm Technologies",
    ),
    "VSAT": (
        "software or other intellectual property licensed from third parties",
        "Assistant Controller",
        "strong oceanic coverage) with greater redundancy",
        "Latin America",
        "strong oceanic coverage",
        "subscriber retention efforts",
        "as described below: • Communication Services Sales Organization",
    ),
}


def _core7_targeted_repair_candidate(
    profile: dict,
) -> tuple[dict, dict]:
    symbol = str(
        profile.get("symbol")
        or ""
    ).strip().upper()

    if symbol not in CORE7_TARGETED_REPAIR_SYMBOLS:
        raise ValueError(
            f"{symbol or '<missing>'}: not in 7-core targeted repair whitelist"
        )

    sanitized, sanitizer = (
        _sanitize_profile_for_production(
            profile
        )
    )

    products = (
        sanitized.get("product_stack")
        if isinstance(
            sanitized.get("product_stack"),
            list,
        )
        else []
    )

    expected = list(
        CORE7_TARGETED_REPAIR_REMOVALS.get(
            symbol,
            (),
        )
    )

    missing_expected = [
        value
        for value in expected
        if value not in products
    ]

    if missing_expected:
        raise ValueError(
            f"{symbol}: targeted repair manifest mismatch; "
            f"expected removal values not found post-2c: "
            f"{missing_expected}"
        )

    expected_set = set(
        expected
    )

    final_products = [
        value
        for value in products
        if value not in expected_set
    ]

    targeted_removed = [
        value
        for value in products
        if value in expected_set
    ]

    if len(targeted_removed) != len(expected):
        raise ValueError(
            f"{symbol}: targeted repair removal accounting mismatch "
            f"(expected={len(expected)} removed={len(targeted_removed)})"
        )

    if not final_products:
        raise ValueError(
            f"{symbol}: targeted repair refuses empty final product_stack"
        )

    repaired = dict(
        sanitized
    )

    repaired[
        "product_stack"
    ] = final_products

    repaired[
        "core7_targeted_repair"
    ] = {
        "version":
            CORE7_TARGETED_REPAIR_VERSION,
        "mode":
            "exact_value_whitelist_repair",
        "symbol":
            symbol,
        "post_2c_count":
            len(products),
        "targeted_removed_count":
            len(targeted_removed),
        "targeted_removed":
            targeted_removed,
        "final_product_count":
            len(final_products),
    }

    return repaired, {
        "symbol":
            symbol,
        "rebuilt_count":
            len(
                profile.get("product_stack")
                if isinstance(
                    profile.get("product_stack"),
                    list,
                )
                else []
            ),
        "post_2c_count":
            len(products),
        "production_sanitizer_removed_count":
            sanitizer.get(
                "removed_count",
                0,
            ),
        "production_sanitizer_removed":
            sanitizer.get(
                "removed",
                [],
            ),
        "targeted_removed_count":
            len(targeted_removed),
        "targeted_removed":
            targeted_removed,
        "final_product_count":
            len(final_products),
        "final_product_stack":
            final_products,
    }


def _core7_targeted_repair_run(
    write: bool,
) -> dict:
    symbols = list(
        CORE7_TARGETED_REPAIR_SYMBOLS
    )

    report = build_company_profile_batch(
        ROOT,
        scope="evidence",
        symbols=symbols,
    )

    report[
        "_requested_scope"
    ] = "strategic"

    _apply_product_recall(
        report
    )

    _apply_company_summary_semantic_selector(
        report
    )

    profiles_by_symbol = {
        str(
            p.get("symbol")
            or ""
        ).strip().upper(): p
        for p in (
            report.get(
                "_canonical_profiles"
            )
            or []
        )
    }

    missing = [
        symbol
        for symbol in symbols
        if symbol not in profiles_by_symbol
    ]

    extras = sorted(
        set(
            profiles_by_symbol
        )
        - set(
            symbols
        )
    )

    if missing or extras:
        raise ValueError(
            "7-core rebuild invariant failed: "
            f"missing={missing} extras={extras}"
        )

    candidates = []
    rows = []

    for symbol in symbols:
        candidate, row = (
            _core7_targeted_repair_candidate(
                profiles_by_symbol[
                    symbol
                ]
            )
        )

        candidates.append(
            candidate
        )

        rows.append(
            row
        )

    expected_targeted_removals = sum(
        len(
            CORE7_TARGETED_REPAIR_REMOVALS[
                symbol
            ]
        )
        for symbol in symbols
    )

    actual_targeted_removals = sum(
        row[
            "targeted_removed_count"
        ]
        for row in rows
    )

    if (
        actual_targeted_removals
        != expected_targeted_removals
    ):
        raise ValueError(
            "7-core targeted removal total mismatch "
            f"(expected={expected_targeted_removals} "
            f"actual={actual_targeted_removals})"
        )

    result = {
        "repair_version":
            CORE7_TARGETED_REPAIR_VERSION,
        "sanitizer_version":
            PRODUCT_SANITIZER_VERSION,
        "diagnostics_version":
            PRODUCT_CONTAMINATION_DIAGNOSTICS_VERSION,
        "mode":
            "7_core_exact_value_targeted_repair",
        "symbols":
            symbols,
        "company_count":
            len(rows),
        "expected_targeted_removed_item_count":
            expected_targeted_removals,
        "targeted_removed_item_count":
            actual_targeted_removals,
        "all_final_product_stacks_nonempty":
            all(
                row[
                    "final_product_count"
                ] > 0
                for row in rows
            ),
        "write_requested":
            write,
        "rows":
            rows,
    }

    if not write:
        result[
            "write_status"
        ] = "dry_run"

        return result

    write_result = (
        _safe_upsert_canonical_profiles(
            candidates
        )
    )

    if (
        write_result.get(
            "written_count"
        )
        != len(symbols)
    ):
        raise ValueError(
            "7-core canonical write count mismatch "
            f"(expected={len(symbols)} "
            f"actual={write_result.get('written_count')})"
        )

    result[
        "write_status"
    ] = "written"

    result[
        "write_result"
    ] = write_result

    return result


def _resolve_snapshot_path(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
    else:
        path = (CANONICAL_ROOT / "strategic_product_census_v2657.json").resolve()
    if not path.is_file():
        raise ValueError(f"V2.6.5.7 census snapshot not found: {path}")
    return path


def _canonical_index_payload() -> dict:
    path = CANONICAL_ROOT / "index.json"
    if not path.is_file():
        return {"schema_version":"axiom-company-profile-index.v2.3","symbol_to_file":{},"company_id_to_file":{},"symbols":[],"company_count":0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"canonical index is not an object: {path}")
    payload.setdefault("symbol_to_file", {})
    payload.setdefault("company_id_to_file", {})
    return payload


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    tmp.replace(path)


def _safe_upsert_canonical_profiles(
    profiles: list[dict],
) -> dict:
    index = _canonical_index_payload()

    symbol_to_file = dict(
        index.get(
            "symbol_to_file"
        )
        or {}
    )

    company_id_to_file = dict(
        index.get(
            "company_id_to_file"
        )
        or {}
    )

    before_symbols = set(
        symbol_to_file
    )

    before_company_ids = set(
        company_id_to_file
    )

    written = []

    for raw_profile in profiles:
        profile, sanitizer = (
            _sanitize_profile_for_production(
                raw_profile
            )
        )

        symbol = str(
            profile.get(
                "symbol"
            )
            or ""
        ).strip().upper()

        company_id = str(
            profile.get(
                "company_id"
            )
            or ""
        ).strip()

        products = (
            profile.get(
                "product_stack"
            )
            or []
        )

        if not symbol or not company_id:
            raise ValueError(
                "safe promotion profile requires symbol and company_id"
            )

        if (
            not isinstance(
                products,
                list,
            )
            or not products
        ):
            raise ValueError(
                f"{symbol}: product sanitizer refuses empty production product_stack "
                f"(before={sanitizer['before_count']} removed={sanitizer['removed_count']})"
            )

        rel = (
            Path(
                "per-company"
            )
            / (
                quote(
                    company_id,
                    safe="",
                )
                + ".json"
            )
        )

        target = (
            CANONICAL_ROOT
            / rel
        )

        _write_json_atomic(
            target,
            profile,
        )

        readback = json.loads(
            target.read_text(
                encoding="utf-8"
            )
        )

        if (
            readback.get(
                "product_stack"
            )
            != profile.get(
                "product_stack"
            )
        ):
            raise ValueError(
                f"{symbol}: canonical product_stack read-back mismatch"
            )

        readback_sanitizer = (
            readback.get(
                "product_stack_sanitizer"
            )
            or {}
        )

        if (
            readback_sanitizer.get(
                "version"
            )
            != PRODUCT_SANITIZER_VERSION
        ):
            raise ValueError(
                f"{symbol}: product sanitizer metadata read-back mismatch"
            )

        symbol_to_file[
            symbol
        ] = str(
            rel
        )

        company_id_to_file[
            company_id
        ] = str(
            rel
        )

        written.append(
            {
                "symbol":
                    symbol,
                "company_id":
                    company_id,
                "relative_path":
                    str(
                        rel
                    ),
                "product_stack_count":
                    len(
                        products
                    ),
                "sanitizer_removed_count":
                    sanitizer[
                        "removed_count"
                    ],
                "sanitizer_removed":
                    sanitizer[
                        "removed"
                    ],
            }
        )

    if not (
        before_symbols
        <= set(
            symbol_to_file
        )
    ):
        raise ValueError(
            "safe promotion invariant failed: existing symbol index entry lost"
        )

    if not (
        before_company_ids
        <= set(
            company_id_to_file
        )
    ):
        raise ValueError(
            "safe promotion invariant failed: existing company index entry lost"
        )

    index[
        "symbol_to_file"
    ] = dict(
        sorted(
            symbol_to_file.items()
        )
    )

    index[
        "company_id_to_file"
    ] = dict(
        sorted(
            company_id_to_file.items()
        )
    )

    index[
        "symbols"
    ] = sorted(
        symbol_to_file
    )

    index[
        "company_count"
    ] = len(
        company_id_to_file
    )

    _write_json_atomic(
        CANONICAL_ROOT
        / "index.json",
        index,
    )

    return {
        "sanitizer_version":
            PRODUCT_SANITIZER_VERSION,
        "written_count":
            len(
                written
            ),
        "company_count_before":
            len(
                before_company_ids
            ),
        "company_count_after":
            len(
                company_id_to_file
            ),
        "preserved_existing_symbols":
            before_symbols
            <= set(
                index[
                    "symbol_to_file"
                ]
            ),
        "sanitizer_removed_item_count":
            sum(
                row[
                    "sanitizer_removed_count"
                ]
                for row in written
            ),
        "written":
            written,
    }


def _promotion_candidates_from_snapshot(snapshot_path: Path) -> tuple[list[str], dict]:
    report = _report_from_snapshot(snapshot_path)
    gate = _production_promotion_gate(report, sample_limit=12)
    symbols = [row["symbol"] for row in gate.get("rows", []) if row.get("promotion_status") == "PROMOTE"]
    return symbols, gate


def _safe_promotion_run(snapshot_path: Path, write: bool, limit: int | None) -> dict:
    candidates, snapshot_gate = _promotion_candidates_from_snapshot(snapshot_path)
    if limit is not None:
        if limit <= 0: raise ValueError("--promotion-limit must be > 0")
        candidates = candidates[:limit]
    report = build_company_profile_batch(ROOT, scope="evidence", symbols=candidates)
    report["_requested_scope"] = "strategic"
    _apply_product_recall(report)
    rebuild_gate = _production_promotion_gate(report, sample_limit=12)
    status_by_symbol = {row["symbol"]:row["promotion_status"] for row in rebuild_gate.get("rows", [])}
    still_promote = [s for s in candidates if status_by_symbol.get(s) == "PROMOTE"]
    downgraded = [{"symbol":s,"status":status_by_symbol.get(s,"MISSING")} for s in candidates if status_by_symbol.get(s) != "PROMOTE"]
    profiles_by_symbol = {str(p.get("symbol") or "").upper():p for p in report.get("_canonical_profiles", [])}
    result = {
        "gate_version": PROMOTION_GATE_VERSION,
        "mode": "safe_promotion_writer",
        "snapshot": str(snapshot_path),
        "snapshot_promote_count": snapshot_gate["strategic_universe"]["promote"],
        "selected_candidate_count": len(candidates),
        "revalidated_promote_count": len(still_promote),
        "downgraded_count": len(downgraded),
        "downgraded": downgraded,
        "write_requested": write,
    }
    if not write:
        result["write_status"] = "dry_run"
        result["promote_symbols"] = still_promote
        return result
    profiles = [profiles_by_symbol[s] for s in still_promote if s in profiles_by_symbol]
    result["write_status"] = "written"
    result["write_result"] = _safe_upsert_canonical_profiles(profiles)
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="V2.6.5.8 Company Profile promotion gate and safe writer")
    parser.add_argument("--scope", choices=("published","strategic"), default="strategic")
    parser.add_argument("--symbol", action="append", default=[])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--full-report", action="store_true")
    parser.add_argument("--diagnostic-limit", type=int, default=12)
    parser.add_argument("--worst-limit", type=int, default=20)
    parser.add_argument("--one-screen", action="store_true")
    parser.add_argument("--census-snapshot", help="Existing V2.6.5.7 strategic product census JSON")
    parser.add_argument("--promote-from-snapshot", action="store_true", help="Rebuild only snapshot PROMOTE symbols and revalidate")
    parser.add_argument("--promotion-limit", type=int, help="Optional canary limit for safe promotion")
    parser.add_argument(
        "--core7-targeted-repair",
        action="store_true",
        help=(
            "V2.6.6.2c exact-value targeted canonical repair for "
            "AMD/AVGO/CRDO/LITE/NVDA/QCOM/VSAT. "
            "Dry-run unless --write is explicitly supplied."
        ),
    )
    parser.add_argument(
        "--summary-diagnostics",
        action="store_true",
        help=(
            "Print V2.6.6.0 old/new company summary selection diagnostics "
            "for explicitly requested symbols. No write is performed."
        ),
    )

    parser.add_argument(
        "--product-sanitizer-diagnostics",
        action="store_true",
        help=(
            "Print V2.6.6.2 production-boundary product sanitizer diagnostics "
            "for explicitly requested symbols. No write is performed."
        ),
    )

    parser.add_argument(
        "--product-contamination-diagnostics",
        action="store_true",
        help=(
            "Print V2.6.6.2b diagnostics-only contamination review "
            "for explicitly requested symbols. No write is performed and "
            "V2.6.6.2a production sanitizer behavior is unchanged."
        ),
    )

    args = parser.parse_args()

    if args.core7_targeted_repair:
        try:
            result = (
                _core7_targeted_repair_run(
                    args.write
                )
            )
        except (
            ValueError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "repair_version":
                            CORE7_TARGETED_REPAIR_VERSION,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.promote_from_snapshot:
        try:
            snapshot = _resolve_snapshot_path(args.census_snapshot)
            result = _safe_promotion_run(snapshot, args.write, args.promotion_limit)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status":"blocked","gate_version":PROMOTION_GATE_VERSION,"error":str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.write:
        print(json.dumps({"write_status":"blocked","gate_version":PROMOTION_GATE_VERSION,"write_error":"Destructive batch --write is disabled. Use --promote-from-snapshot --write."}, ensure_ascii=False, indent=2))
        return 2

    explicit_symbols = [str(s).strip().upper() for s in args.symbol if str(s).strip()]
    if explicit_symbols:
        report = build_company_profile_batch(
            ROOT,
            scope="evidence",
            symbols=explicit_symbols,
        )
        report["_requested_scope"] = args.scope
        _apply_product_recall(
            report
        )
        _apply_company_summary_semantic_selector(
            report
        )
    elif args.scope == "strategic":
        try:
            report = _report_from_snapshot(_resolve_snapshot_path(args.census_snapshot))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status":"blocked","gate_version":PROMOTION_GATE_VERSION,"error":str(exc)}, ensure_ascii=False, indent=2))
            return 2
    else:
        report = build_company_profile_batch(ROOT, scope="published", symbols=[])
        report["_requested_scope"] = args.scope
        _apply_product_recall(report)

    report["promotion_gate"] = _production_promotion_gate(
        report,
        sample_limit=max(
            1,
            args.diagnostic_limit,
        ),
    )

    if args.product_sanitizer_diagnostics:
        if not explicit_symbols:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "error": (
                            "--product-sanitizer-diagnostics requires "
                            "explicit --symbol values"
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2

        print(
            json.dumps(
                _product_sanitizer_diagnostics(
                    report.get(
                        "_canonical_profiles"
                    )
                    or []
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.product_contamination_diagnostics:
        if not explicit_symbols:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "error": (
                            "--product-contamination-diagnostics requires "
                            "explicit --symbol values"
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2

        print(
            json.dumps(
                _product_contamination_diagnostics(
                    report.get(
                        "_canonical_profiles"
                    )
                    or []
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.summary_diagnostics:
        if not explicit_symbols:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "error": "--summary-diagnostics requires explicit --symbol values",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2

        print(
            json.dumps(
                _summary_diagnostics_payload(
                    report
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.one_screen or (args.scope == "strategic" and not explicit_symbols and not args.full_report):
        print(_one_screen_promotion_summary(report))
    elif args.full_report:
        print(json.dumps(_public_report(report), ensure_ascii=False, indent=2))
    else:
        output = _compact_census_report_v2658(report, sample_limit=max(1,args.diagnostic_limit), worst_limit=max(1,args.worst_limit), expand_symbols=set(explicit_symbols))
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if report.get("summary",{}).get("complete",True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
