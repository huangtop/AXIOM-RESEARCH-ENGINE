from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .types import SEMANTIC_ELIGIBLE_LAYERS, SemanticClassification, SemanticType

_FIXTURE_PATH_TERMS = ("/test/", "/tests/", "fixture", "sample", "demo", "example", "mock")
_TEMPLATE_PATH_TERMS = ("template", "blank", "skeleton")
_RESEARCH_PATH_TERMS = ("research", "report", "note", "narrative", "news", "diagnostic")
_VALUATION_PATH_TERMS = ("valuation_snapshot", "valuation_snapshots", "valuation_result", "valuation_results", "valuation_book")

_FINANCIAL_KEYS = {
    "revenue", "sales", "ebitda", "ebit", "operating_income", "net_income",
    "assets", "liabilities", "equity", "book_value", "cash_flow", "free_cash_flow",
    "gross_profit", "eps", "diluted_eps", "period_end", "fiscal_year",
}
_MARKET_KEYS = {
    "price", "last_price", "close", "open", "high", "low", "volume", "market_cap",
    "shares_outstanding", "enterprise_value", "trade_date", "quote_time", "as_of",
}
_ESTIMATE_KEYS = {
    "forward_eps", "forward_revenue", "eps_estimate", "revenue_estimate", "consensus",
    "target_price", "analyst_count", "forecast_period", "estimate_date", "growth_estimate",
}
_VALUATION_KEYS = {
    "fair_value", "intrinsic_value", "valuation_date", "valuation_method", "valuation_model",
    "implied_upside", "price_target", "scenario_value", "terminal_value", "discount_rate",
    "wacc", "dcf_value", "multiple_value", "valuation_status",
}
_RESEARCH_KEYS = {
    "thesis", "summary", "analysis", "conclusion", "research_note", "headline",
    "article_url", "source_url", "sentiment", "catalyst", "risk_factors",
}
_IDENTITY_KEYS = {"company_id", "security_id", "entity_id", "issuer_id", "ticker", "symbol", "cik"}


def _normalise_path(path: Path | str) -> str:
    return "/" + str(path).replace("\\", "/").lower().strip("/")


def _sample_keys(rows: Iterable[dict[str, Any]], limit: int = 100) -> set[str]:
    keys: set[str] = set()
    for index, row in enumerate(rows):
        if index >= limit:
            break
        keys.update(str(key).strip().lower() for key in row)
    return keys


def _non_empty_ratio(rows: list[dict[str, Any]], keys: set[str], limit: int = 100) -> float:
    sampled = rows[:limit]
    if not sampled or not keys:
        return 0.0
    populated = 0
    possible = 0
    for row in sampled:
        for key in keys:
            if key not in row:
                continue
            possible += 1
            value = row.get(key)
            if value not in (None, "", [], {}):
                populated += 1
    return populated / possible if possible else 0.0


def _result(kind: SemanticType, confidence: float, evidence: list[str]) -> SemanticClassification:
    return SemanticClassification(
        semantic_type=kind,
        confidence=max(0.0, min(1.0, confidence)),
        eligible_layers=SEMANTIC_ELIGIBLE_LAYERS[kind],
        evidence=tuple(dict.fromkeys(evidence)),
    )


def classify_semantic_type(path: Path | str, rows: list[dict[str, Any]]) -> SemanticClassification:
    """Classify a source by semantic purpose before population-layer scoring.

    Identity fields such as ticker/company_id are deliberately excluded from type scoring.
    A valuation output therefore cannot become a market source merely because it contains
    current price or security identifiers.
    """
    low_path = _normalise_path(path)
    keys = _sample_keys(rows)
    evidence: list[str] = []

    if any(term in low_path for term in _FIXTURE_PATH_TERMS):
        return _result(SemanticType.FIXTURE, 0.99, ["path:fixture"])
    if any(term in low_path for term in _TEMPLATE_PATH_TERMS):
        return _result(SemanticType.TEMPLATE, 0.99, ["path:template"])

    valuation_hits = sorted(keys & _VALUATION_KEYS)
    if any(term in low_path for term in _VALUATION_PATH_TERMS) or len(valuation_hits) >= 2:
        if any(term in low_path for term in _VALUATION_PATH_TERMS):
            evidence.append("path:valuation_result")
        evidence.extend(f"key:{key}" for key in valuation_hits[:8])
        return _result(SemanticType.VALUATION_RESULT, 0.98 if valuation_hits else 0.9, evidence)

    research_hits = sorted(keys & _RESEARCH_KEYS)
    if any(term in low_path for term in _RESEARCH_PATH_TERMS) and research_hits:
        return _result(
            SemanticType.RESEARCH_OUTPUT,
            0.9,
            ["path:research_output", *(f"key:{key}" for key in research_hits[:8])],
        )

    families = {
        SemanticType.FINANCIAL_FACT: keys & _FINANCIAL_KEYS,
        SemanticType.MARKET_FACT: keys & _MARKET_KEYS,
        SemanticType.ESTIMATE_FACT: keys & _ESTIMATE_KEYS,
    }
    weighted: Counter[SemanticType] = Counter()
    for kind, hits in families.items():
        weighted[kind] = len(hits)

    best = weighted.most_common()
    if best and best[0][1] > 0:
        best_kind, best_count = best[0]
        second_count = best[1][1] if len(best) > 1 else 0
        specific_hits = families[best_kind]
        populated_ratio = _non_empty_ratio(rows, specific_hits)
        margin = best_count - second_count
        confidence = 0.55 + min(0.25, best_count * 0.06) + min(0.12, margin * 0.04) + min(0.08, populated_ratio * 0.08)
        evidence = [*(f"key:{key}" for key in sorted(specific_hits)[:10])]
        if keys & _IDENTITY_KEYS:
            evidence.append("identity_linkage_present")
        return _result(best_kind, confidence, evidence)

    if "/generated/" in low_path:
        return _result(SemanticType.GENERATED_ARTIFACT, 0.7, ["path:generated_artifact"])
    return _result(SemanticType.UNKNOWN, 0.25, ["no_semantic_evidence"])
