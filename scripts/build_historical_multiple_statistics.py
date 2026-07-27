#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from axiom_engine.historical_multiple_statistics import (
    HistoricalMultipleStatisticsError,
    build_historical_multiple_statistics,
    write_historical_multiple_statistics,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build historical multiple statistics")
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="config/historical_multiple_statistics.v030.13.2.json")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    config = json.loads((root / args.config).read_text(encoding="utf-8"))
    try:
        report = build_historical_multiple_statistics(
            root,
            dataset_path=config["dataset_input"],
            windows=config["windows"],
            minimum_ready_observations=int(config["minimum_ready_observations"]),
            outlier_iqr_multiplier=float(config["outlier_iqr_multiplier"]),
        )
    except HistoricalMultipleStatisticsError as exc:
        print(f"ERROR: {exc}")
        return 2
    summary = report["summary"]
    print(f"Companies: {summary['company_count']}")
    print(f"Methods: {summary['method_count']}")
    print(f"Series: {summary['series_count']}")
    print(f"Ready series: {summary['ready_series_count']}")
    print(f"Insufficient series: {summary['insufficient_series_count']}")
    print(f"Ready windows: {summary['ready_window_count']}")
    print(f"Insufficient windows: {summary['insufficient_window_count']}")
    print(f"Rejected observations: {summary['rejected_observation_count']}")
    for method, count in summary["method_series_counts"].items():
        print(f"{method}: series={count}")
    if args.write:
        output = root / config["statistics_output"]
        diagnostic = root / config["diagnostic_output"]
        write_historical_multiple_statistics(report, output, diagnostic)
        print(f"Output: {output.relative_to(root)}")
        print(f"Diagnostic: {diagnostic.relative_to(root)}")
    if args.strict and summary["rejected_observation_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
