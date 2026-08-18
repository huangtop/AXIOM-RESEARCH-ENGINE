#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CENSUS = Path("data/generated/company_profile_v2/full_market_census.json")
BUSINESS_EVIDENCE_ROOT = Path("data/generated/canonical_business_evidence")
DEFAULT_OUTPUT = Path("data/generated/company_profile_v2/market_recall_census_v2632.json")
SUPPORTED_BUSINESS_SECTIONS = {"item_1_business", "item_4_company_information"}

PATTERN_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("explicit_end_market", (
        r"\bend[- ]markets?\b", r"\btarget markets?\b", r"\bserved markets?\b",
        r"\bmarkets? we serve\b", r"\bprimary markets?\b", r"\bprincipal markets?\b",
    )),
    ("serve_industry_market", (
        r"\bwe serve\b.{0,160}\b(?:market|markets|industry|industries|sector|sectors|vertical|verticals)\b",
        r"\bserve(?:s|d|ing)?\b.{0,120}\b(?:industry|industries|sector|sectors|vertical|verticals)\b",
        r"\bindustries we serve\b", r"\bverticals we serve\b",
    )),
    ("customer_industry_context", (
        r"\bcustomers?\b.{0,160}\b(?:industry|industries|sector|sectors|market|markets)\b",
        r"\bcustomers? in\b.{0,140}\b(?:industry|industries|sector|sectors)\b",
        r"\bcustomer base\b.{0,160}\b(?:industry|industries|sector|sectors|market|markets)\b",
    )),
    ("application_context", (
        r"\bused in\b.{0,160}\bapplications?\b", r"\bused for\b.{0,160}\bapplications?\b",
        r"\bapplications? include\b", r"\bapplications? such as\b", r"\bapplication markets?\b",
    )),
    ("sold_into_deployed", (
        r"\bsold into\b", r"\bsell into\b", r"\bsells into\b", r"\bdeployed in\b",
        r"\bdeployed across\b", r"\bused across\b", r"\butilized in\b",
    )),
    ("participate_operate", (
        r"\bwe participate in\b.{0,160}\bmarkets?\b",
        r"\bwe operate in\b.{0,160}\bmarkets?\b",
        r"\boperate(?:s|d|ing)? in\b.{0,140}\b(?:industry|industries|sector|sectors|markets?)\b",
    )),
    ("address_focus", (
        r"\baddress(?:es|ed|ing)?\b.{0,140}\bmarkets?\b",
        r"\bfocus(?:es|ed|ing)? on\b.{0,140}\b(?:markets?|industries|sectors|verticals)\b",
        r"\btarget(?:s|ed|ing)?\b.{0,140}\b(?:markets?|industries|sectors|verticals)\b",
    )),
    ("industry_list", (
        r"\bindustries include\b", r"\bindustries such as\b", r"\bindustry sectors? include\b",
        r"\bsectors? include\b", r"\bverticals? include\b",
    )),
    ("market_list", (
        r"\bmarkets? include\b", r"\bmarkets? such as\b", r"\bmarket segments? include\b",
        r"\bmarket sectors? include\b",
    )),
)

RISK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("geography", r"\b(?:geographic|geography|country|countries|region|regions)\b"),
    ("demand", r"\b(?:demand|growth|investment|bandwidth|artificial intelligence|AI)\b"),
    ("distribution", r"\b(?:distributors?|retailers?|resellers?|sales representatives?|channel partners?)\b"),
    ("employee", r"\b(?:employees?|workforce|benefits?|compensation)\b"),
    ("product_heavy", r"\b(?:cpu|cpus|gpu|gpus|cuda|dram|nand|hbm|dimm|dimms|module|modules|software|hardware|processor|processors|chip|chips|chipset|chipsets|semiconductor|semiconductors)\b"),
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def sentences(text: str) -> list[str]:
    compact = normalize_space(text)
    if not compact:
        return []
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", compact)
        if len(item.strip()) >= 20
    ]


def classify_market_sentence(sentence: str) -> list[str]:
    matches: list[str] = []
    for family, patterns in PATTERN_FAMILIES:
        if any(re.search(pattern, sentence, flags=re.IGNORECASE) for pattern in patterns):
            matches.append(family)
    return matches


def classify_risks(sentence: str) -> list[str]:
    return [
        label
        for label, pattern in RISK_PATTERNS
        if re.search(pattern, sentence, flags=re.IGNORECASE)
    ]


def latest_business_evidence(rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        row for row in rows
        if row.get("section_type") in SUPPORTED_BUSINESS_SECTIONS
        and isinstance(row.get("text"), str)
        and row["text"].strip()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: str(row.get("filing_date") or ""))


def missing_market_records(census: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in census.get("records") or []:
        coverage = row.get("coverage") or {}
        if coverage.get("frontend_markets"):
            continue
        rows.append({
            "symbol": str(row.get("symbol") or "").upper(),
            "company_id": str(row.get("company_id") or ""),
            "readiness_reasons": list(row.get("readiness_reasons") or []),
        })
    return rows


def analyze_company(*, symbol: str, company_id: str, evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest = latest_business_evidence(evidence_rows)
    if latest is None:
        return {
            "symbol": symbol,
            "company_id": company_id,
            "status": "no_supported_business_evidence",
            "pattern_families": [],
            "candidate_sentence_count": 0,
            "candidate_sentences": [],
        }

    candidate_sentences = []
    family_set = set()
    for sentence in sentences(str(latest.get("text") or "")):
        families = classify_market_sentence(sentence)
        if not families:
            continue
        family_set.update(families)
        candidate_sentences.append({
            "sentence": sentence,
            "pattern_families": families,
            "risk_flags": classify_risks(sentence),
        })

    return {
        "symbol": symbol,
        "company_id": company_id,
        "status": "market_like_evidence_found" if candidate_sentences else "no_market_like_evidence_found",
        "filing_date": latest.get("filing_date"),
        "form": latest.get("form"),
        "section_type": latest.get("section_type"),
        "business_evidence_id": latest.get("business_evidence_id"),
        "pattern_families": sorted(family_set),
        "candidate_sentence_count": len(candidate_sentences),
        "candidate_sentences": candidate_sentences,
    }


def build_report(
    root: Path,
    *,
    census_path: Path,
    symbols: set[str] | None = None,
    limit: int | None = None,
    examples_per_pattern: int = 8,
    progress_every: int = 100,
) -> dict[str, Any]:
    census = load_json(census_path)
    all_missing_records = missing_market_records(census)
    records = list(all_missing_records)

    if symbols:
        records = [row for row in records if row["symbol"] in symbols]
    if limit is not None:
        records = records[:max(int(limit), 0)]

    evidence_index = load_json(root / BUSINESS_EVIDENCE_ROOT / "index.json")
    company_to_file = evidence_index.get("company_id_to_file") or {}

    companies: list[dict[str, Any]] = []
    pattern_company_counts: Counter[str] = Counter()
    pattern_sentence_counts: Counter[str] = Counter()
    risk_sentence_counts: Counter[str] = Counter()
    global_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    total = len(records)
    for position, row in enumerate(records, start=1):
        symbol = row["symbol"]
        company_id = row["company_id"]
        rel = company_to_file.get(company_id)

        if not rel:
            result = {
                "symbol": symbol,
                "company_id": company_id,
                "status": "missing_evidence_index_mapping",
                "pattern_families": [],
                "candidate_sentence_count": 0,
                "candidate_sentences": [],
            }
        else:
            evidence_rows = load_json(root / BUSINESS_EVIDENCE_ROOT / rel)
            result = analyze_company(
                symbol=symbol,
                company_id=company_id,
                evidence_rows=evidence_rows,
            )

        companies.append(result)
        seen_families = set()
        for candidate in result.get("candidate_sentences") or []:
            for family in candidate.get("pattern_families") or []:
                pattern_sentence_counts[family] += 1
                seen_families.add(family)
                if len(global_examples[family]) < examples_per_pattern:
                    global_examples[family].append({
                        "symbol": symbol,
                        "company_id": company_id,
                        "sentence": candidate["sentence"],
                        "risk_flags": candidate.get("risk_flags") or [],
                    })
            for risk in candidate.get("risk_flags") or []:
                risk_sentence_counts[risk] += 1
        for family in seen_families:
            pattern_company_counts[family] += 1

        if position == 1 or position == total or (progress_every > 0 and position % progress_every == 0):
            found = sum(item.get("status") == "market_like_evidence_found" for item in companies)
            print(
                "[V2.6.3.2 market recall census] "
                f"{position}/{total} symbol={symbol} market_like={found}",
                flush=True,
            )

    with_signal = [row for row in companies if row.get("status") == "market_like_evidence_found"]
    without_signal = [row for row in companies if row.get("status") == "no_market_like_evidence_found"]
    unavailable = [
        row for row in companies
        if row.get("status") not in {"market_like_evidence_found", "no_market_like_evidence_found"}
    ]

    pattern_rows = [
        {
            "pattern_family": family,
            "company_count": pattern_company_counts[family],
            "sentence_count": pattern_sentence_counts[family],
            "examples": global_examples.get(family, []),
        }
        for family in pattern_company_counts
    ]
    pattern_rows.sort(key=lambda row: (-row["company_count"], -row["sentence_count"], row["pattern_family"]))

    summary = census.get("summary") or {}
    return {
        "schema_version": "axiom-company-profile-market-recall-census.v2.6.3.2",
        "generation_mode": "diagnostic_only_no_profile_mutation",
        "source_census": str(census_path.relative_to(root)),
        "summary": {
            "full_evidence_company_count": summary.get("evidence_company_count"),
            "full_missing_frontend_market_count": len(all_missing_records),
            "analyzed_company_count": len(companies),
            "market_like_evidence_company_count": len(with_signal),
            "no_market_like_evidence_company_count": len(without_signal),
            "unavailable_evidence_company_count": len(unavailable),
            "market_like_evidence_rate": len(with_signal) / len(companies) if companies else 0.0,
        },
        "pattern_families": pattern_rows,
        "risk_sentence_counts": dict(sorted(risk_sentence_counts.items(), key=lambda item: (-item[1], item[0]))),
        "market_like_symbols": [row["symbol"] for row in with_signal],
        "no_market_like_symbols": [row["symbol"] for row in without_signal],
        "unavailable_symbols": [row["symbol"] for row in unavailable],
        "companies": companies,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "V2.6.3.2 diagnostic census over companies still missing frontend markets. "
            "Find recurring filing wording without changing production extraction rules."
        )
    )
    parser.add_argument("--census", default=str(DEFAULT_CENSUS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--examples-per-pattern", type=int, default=8)
    parser.add_argument("--progress-every", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    census_path = ROOT / Path(args.census)
    output_path = ROOT / Path(args.output)
    symbols = (
        {str(symbol).strip().upper() for symbol in args.symbols if str(symbol).strip()}
        if args.symbols else None
    )

    report = build_report(
        ROOT,
        census_path=census_path,
        symbols=symbols,
        limit=args.limit,
        examples_per_pattern=max(int(args.examples_per_pattern), 1),
        progress_every=max(int(args.progress_every), 0),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = report["summary"]
    print()
    print("=== V2.6.3.2 Market Recall Census ===")
    print("Full evidence companies:       ", summary["full_evidence_company_count"])
    print("Full missing frontend markets: ", summary["full_missing_frontend_market_count"])
    print("Analyzed:                      ", summary["analyzed_company_count"])
    print("Market-like evidence found:    ", summary["market_like_evidence_company_count"])
    print("No market-like evidence found: ", summary["no_market_like_evidence_company_count"])
    print("Unavailable evidence:          ", summary["unavailable_evidence_company_count"])
    print("Market-like evidence rate:     ", f"{summary['market_like_evidence_rate'] * 100:.1f}%")
    print()
    print("Top pattern families:")
    for row in report["pattern_families"][:12]:
        print(
            f"  {row['pattern_family']:28s} "
            f"companies={row['company_count']:4d} "
            f"sentences={row['sentence_count']:5d}"
        )
    print()
    print("Risk sentence counts:", json.dumps(report["risk_sentence_counts"], ensure_ascii=False, sort_keys=True))
    print()
    print("Report:", output_path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())