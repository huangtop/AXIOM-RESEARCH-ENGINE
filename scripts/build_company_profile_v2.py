#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


try:
    from axiom_engine.company_profile_v2 import build_company_profile_v2  # noqa: E402
except Exception:
    # Fallback: load module directly from src/axiom_engine/company_profile_v2.py
    import importlib.util

    module_path = ROOT / "src" / "axiom_engine" / "company_profile_v2.py"
    if not module_path.exists():
        raise

    spec = importlib.util.spec_from_file_location("axiom_engine.company_profile_v2", str(module_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    build_company_profile_v2 = getattr(module, "build_company_profile_v2")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build evidence-first Company Profile V2."
    )
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()

    profile = build_company_profile_v2(
        ROOT,
        symbol=args.symbol,
    )

    print(
        json.dumps(
            profile,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())