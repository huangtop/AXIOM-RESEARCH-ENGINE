from __future__ import annotations

import argparse
import json
from pathlib import Path

from axiom_engine.historical_multiples import (
    HistoricalMultipleDatasetError,
    build_historical_multiple_dataset,
    write_historical_multiple_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the V030.13.1 historical multiple dataset")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--engine", default="data/generated/valuation_engine/valuation_snapshot.json")
    parser.add_argument("--existing", default="data/generated/historical_multiples/historical_multiple_dataset.json")
    parser.add_argument("--output", default="data/generated/historical_multiples/historical_multiple_dataset.json")
    parser.add_argument("--diagnostic", default="data/generated/historical_multiples/historical_multiple_diagnostic.json")
    parser.add_argument("--minimum-ready-observations", type=int, default=20)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = Path(args.repository_root).resolve()
    try:
        report = build_historical_multiple_dataset(
            root,
            engine_path=args.engine,
            existing_dataset_path=args.existing,
            minimum_ready_observations=args.minimum_ready_observations,
        )
    except HistoricalMultipleDatasetError as exc:
        parser.error(str(exc))

    summary = report["summary"]
    print(f"Companies: {summary['company_count']}")
    print(f"Methods: {summary['method_count']}")
    print(f"Observations: {summary['observation_count']}")
    print(f"Series: {summary['series_count']}")
    print(f"Ready series: {summary['ready_series_count']}")
    print(f"Collecting series: {summary['collecting_series_count']}")
    print(f"Added observations: {summary['added_observation_count']}")
    print(f"Replaced observations: {summary['replaced_observation_count']}")
    print(f"Skipped method records: {summary['skipped_method_record_count']}")
    for method, count in summary["method_observation_counts"].items():
        print(f"{method}: observations={count}")

    if args.strict and summary["skipped_method_record_count"] and not summary["observation_count"]:
        parser.error("strict mode requires at least one valid observation")
    if args.write:
        output = root / args.output
        diagnostic = root / args.diagnostic
        write_historical_multiple_dataset(report, output, diagnostic)
        print(f"Output: {args.output}")
        print(f"Diagnostic: {args.diagnostic}")
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
