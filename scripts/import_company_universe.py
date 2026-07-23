from __future__ import annotations

import argparse
import json

from axiom_engine.company_registry import import_company_universe


def main() -> None:
    parser = argparse.ArgumentParser(description="Import independent company universe metadata")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-dir", default="data/company_registry")
    parser.add_argument("--write", action="store_true", help="Write registry output; default is dry-run")
    args = parser.parse_args()
    report = import_company_universe(args.source, output_dir=args.output_dir, dry_run=not args.write)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
