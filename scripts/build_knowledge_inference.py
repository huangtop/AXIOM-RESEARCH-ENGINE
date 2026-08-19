#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
from pathlib import Path

from axiom_engine.knowledge_inference import (
    build_knowledge_inference,
    write_knowledge_inference,
)


def _print_signals_only_diagnostics(report: dict) -> None:
    all_signal_counts: Counter[str] = Counter()
    product_signal_counts: Counter[str] = Counter()
    company_dimension_patterns: Counter[str] = Counter()

    for row in report.get("records") or []:
        if row.get("status") != "signals_only":
            continue

        knowledge = list(row.get("knowledge") or [])

        observed = [
            item
            for item in knowledge
            if item.get("derivation_type") == "observed_signal"
        ]

        dimensions = sorted(
            {
                str(item.get("dimension") or "")
                for item in observed
                if item.get("dimension")
            }
        )

        company_dimension_patterns[
            "+".join(dimensions) if dimensions else "(none)"
        ] += 1

        for item in observed:
            signal_id = str(item.get("knowledge_id") or "")
            dimension = str(item.get("dimension") or "")

            if not signal_id:
                continue

            all_signal_counts[signal_id] += 1

            if dimension == "product":
                product_signal_counts[signal_id] += 1

    print()
    print("=== Signals-Only Diagnostics ===")
    print(
        "Signals-only companies:            "
        f"{sum(company_dimension_patterns.values())}"
    )

    print()
    print("Top observed signals in signals-only companies:")
    for signal_id, count in all_signal_counts.most_common(30):
        print(f"  {signal_id:<52} {count:>5}")

    print()
    print("Top PRODUCT signals without inference:")
    if not product_signal_counts:
        print("  (none)")
    else:
        for signal_id, count in product_signal_counts.most_common(30):
            print(f"  {signal_id:<52} {count:>5}")

    print()
    print("Top signals-only dimension patterns:")
    for pattern, count in company_dimension_patterns.most_common(20):
        print(f"  {pattern:<52} {count:>5}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]

    report = build_knowledge_inference(root)

    write_knowledge_inference(
        report,
        root
        / "data/generated/knowledge_inference/"
        "knowledge_inference.json",
    )

    print(report["summary"])
    _print_signals_only_diagnostics(report)


if __name__ == "__main__":
    main()