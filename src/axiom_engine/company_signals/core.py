from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class CompanySignalsError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanySignalsError(f"cannot read {path}: {exc}") from exc


def _pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias.strip()).replace(r"\ ", r"[\s\-/]+")
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


def _context(text: str, start: int, end: int, maximum: int) -> dict[str, Any]:
    half = max(0, maximum // 2)
    left = max(0, start - half)
    right = min(len(text), end + half)
    return {
        "start_character": start,
        "end_character": end,
        "matched_text": text[start:end],
        "context": " ".join(text[left:right].split()),
    }


def _validate_policy(policy: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if policy.get("schema_version") != "company-signal-rules.v031c.2":
        raise CompanySignalsError("unsupported company signal policy")
    signals = policy.get("signals")
    if not isinstance(signals, list):
        raise CompanySignalsError("company signal policy signals must be an array")
    ids: set[str] = set()
    forbidden_membership_keys = {"ticker", "tickers", "symbol", "symbols", "company_id", "company_ids"}
    for signal in signals:
        signal_id = str(signal.get("signal_id") or "")
        aliases = signal.get("aliases")
        if not signal_id or signal_id in ids or not isinstance(aliases, list) or not aliases:
            raise CompanySignalsError(f"invalid or duplicate signal rule: {signal_id}")
        if forbidden_membership_keys.intersection(signal):
            raise CompanySignalsError(f"ticker/company membership is forbidden in signal rules: {signal_id}")
        ids.add(signal_id)
    return signals


def build_company_signals(
    root: Path,
    *,
    rules_path: str = "config/company_signal_rules.v031c.2.json",
    companies_path: str = "data/universe/companies.json",
    evidence_path: str = "data/generated/canonical_business_evidence/business_evidence.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    policy = _load(root / rules_path)
    companies = _load(root / companies_path)
    evidence = _load(root / evidence_path)
    rules = _validate_policy(policy)
    if not isinstance(companies, list) or not isinstance(evidence, list):
        raise CompanySignalsError("company and evidence inputs must be arrays")

    evidence_by_company: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in evidence:
        if row.get("company_id") and row.get("text") and row.get("business_evidence_id"):
            evidence_by_company[str(row["company_id"])].append(row)

    maximum_locations = int(policy["matching"]["maximum_locations_per_signal"])
    maximum_context = int(policy["matching"]["maximum_context_characters"])
    minimum_occurrences = int(policy["matching"]["minimum_occurrences"])
    compiled_rules = [
        (rule, [(str(alias), _pattern(str(alias))) for alias in rule["aliases"]])
        for rule in rules
    ]
    records: list[dict[str, Any]] = []
    signal_counts: Counter[str] = Counter()
    dimension_counts: Counter[str] = Counter()

    for company in sorted(companies, key=lambda row: str(row.get("company_id") or "")):
        company_id = str(company.get("company_id") or "")
        source_rows = sorted(
            evidence_by_company.get(company_id, []),
            key=lambda row: (str(row.get("filing_date") or ""), str(row.get("business_evidence_id") or "")),
            reverse=True,
        )
        extracted: list[dict[str, Any]] = []
        for rule, compiled_aliases in compiled_rules:
            occurrences: list[dict[str, Any]] = []
            aliases_hit: set[str] = set()
            source_ids: set[str] = set()
            count = 0
            for source in source_rows:
                text = str(source["text"])
                for alias, pattern in compiled_aliases:
                    for match in pattern.finditer(text):
                        count += 1
                        aliases_hit.add(alias)
                        source_ids.add(str(source["business_evidence_id"]))
                        if len(occurrences) < maximum_locations:
                            occurrences.append({
                                "business_evidence_id": source["business_evidence_id"],
                                "provenance_id": source.get("provenance_id"),
                                "accession_number": source.get("accession_number"),
                                **_context(text, match.start(), match.end(), maximum_context),
                            })
            if count < minimum_occurrences:
                continue
            confidence = round(min(0.95, 0.55 + 0.08 * min(count - 1, 3) + 0.04 * min(len(aliases_hit) - 1, 2)), 4)
            extracted.append({
                "signal_id": rule["signal_id"],
                "dimension": rule["dimension"],
                "canonical_name": rule["canonical_name"],
                "confidence": confidence,
                "occurrence_count": count,
                "matched_aliases": sorted(aliases_hit),
                "source_business_evidence_ids": sorted(source_ids),
                "locations": occurrences,
            })
            signal_counts[str(rule["signal_id"])] += 1
            dimension_counts[str(rule["dimension"])] += 1
        extracted.sort(key=lambda row: (row["dimension"], -row["confidence"], row["signal_id"]))
        records.append({
            "company_id": company_id,
            "status": "signals_available" if extracted else "no_signals_detected" if source_rows else "business_evidence_unavailable",
            "source_business_evidence_ids": [str(row["business_evidence_id"]) for row in source_rows],
            "signals": extracted,
        })

    return {
        "schema_version": "company-signals.v031c.2",
        "version": "V031C.2",
        "generated_at": current.isoformat(),
        "summary": {
            "company_count": len(records),
            "business_evidence_company_count": sum(bool(row["source_business_evidence_ids"]) for row in records),
            "signals_available_company_count": sum(row["status"] == "signals_available" for row in records),
            "no_signals_detected_company_count": sum(row["status"] == "no_signals_detected" for row in records),
            "business_evidence_unavailable_company_count": sum(row["status"] == "business_evidence_unavailable" for row in records),
            "signal_company_counts": dict(sorted(signal_counts.items())),
            "dimension_signal_counts": dict(sorted(dimension_counts.items())),
        },
        "policy": {"rules_path": rules_path, "contains_ticker_membership": False},
        "records": records,
        "indexes": {"company_id_to_position": {row["company_id"]: index for index, row in enumerate(records)}},
    }


def write_company_signals(report: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
