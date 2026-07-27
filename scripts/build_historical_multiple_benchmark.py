#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from axiom_engine.historical_multiple_benchmark import HistoricalMultipleBenchmarkError, build_historical_multiple_benchmark, write_historical_multiple_benchmark

def main() -> int:
    parser = argparse.ArgumentParser(description="Build historical multiple benchmark payload")
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="config/historical_multiple_benchmark.v030.13.3.json")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    config = json.loads((root / args.config).read_text(encoding="utf-8"))
    try:
        report = build_historical_multiple_benchmark(
            root,
            statistics_path=config["statistics_input"],
            window_preference=config["window_preference"],
            benchmark_statistic=config["benchmark_statistic"],
            lower_bound_statistic=config["lower_bound_statistic"],
            upper_bound_statistic=config["upper_bound_statistic"],
            medium_confidence_observations=int(config["medium_confidence_observations"]),
            high_confidence_observations=int(config["high_confidence_observations"]),
        )
    except HistoricalMultipleBenchmarkError as exc:
        print(f"ERROR: {exc}")
        return 2
    summary = report["summary"]
    print(f"Companies: {summary['company_count']}")
    print(f"Methods: {summary['method_count']}")
    print(f"Benchmark records: {summary['benchmark_record_count']}")
    print(f"Ready benchmarks: {summary['ready_benchmark_count']}")
    print(f"Insufficient benchmarks: {summary['insufficient_benchmark_count']}")
    print(f"Invalid benchmarks: {summary['invalid_benchmark_count']}")
    for method, counts in summary["method_benchmark_counts"].items():
        print(f"{method}: ready={counts['ready']} insufficient={counts['insufficient_history']} invalid={counts['invalid']}")
    if args.write:
        output = root / config["benchmark_output"]
        diagnostic = root / config["diagnostic_output"]
        write_historical_multiple_benchmark(report, output, diagnostic)
        print(f"Output: {output.relative_to(root)}")
        print(f"Diagnostic: {diagnostic.relative_to(root)}")
    if args.strict and summary["invalid_benchmark_count"]:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
