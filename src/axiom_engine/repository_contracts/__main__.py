from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit import write_audit_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit AXIOM repository contracts without changing repository data.")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--output", default="data/generated/repository_contracts/repository_contract_audit.json")
    parser.add_argument("--strict", action="store_true", help="Fail only on invalid JSON or multiple canonical path candidates.")
    args = parser.parse_args()

    report = write_audit_report(Path(args.repository_root), Path(args.output))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if args.strict:
        blocking = {
            "invalid_json_detected",
            "multiple_canonical_path_candidates_exist",
        }
        if any(blocking.intersection(contract["findings"]) for contract in report["contracts"]):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
