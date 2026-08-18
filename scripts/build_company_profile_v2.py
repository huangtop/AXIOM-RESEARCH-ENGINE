#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


from axiom_engine.company_profile_v2 import build_company_profile_v2  # noqa: E402


OUTPUT_ROOT = (
    ROOT
    / "data/generated/company_profile_v2"
)


def _write_json(
    path: Path,
    payload: object,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _output_filename(
    company_id: str,
) -> str:
    return (
        quote(
            company_id,
            safe="",
        )
        + ".json"
    )


def _load_existing_index() -> dict:
    path = OUTPUT_ROOT / "index.json"

    if not path.exists():
        return {
            "schema_version":
                "axiom-company-profile-index.v2.3",
            "symbol_to_file": {},
            "company_id_to_file": {},
        }

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return {
            "schema_version":
                "axiom-company-profile-index.v2.3",
            "symbol_to_file": {},
            "company_id_to_file": {},
        }

    if not isinstance(payload, dict):
        payload = {}

    payload.setdefault(
        "symbol_to_file",
        {},
    )

    payload.setdefault(
        "company_id_to_file",
        {},
    )

    payload[
        "schema_version"
    ] = (
        "axiom-company-profile-index.v2.3"
    )

    return payload


def _write_profile(
    profile: dict,
) -> Path:
    company_id = str(
        profile["company_id"]
    )

    symbol = str(
        profile["symbol"]
    ).upper()

    filename = _output_filename(
        company_id
    )

    relative_path = (
        Path("per-company")
        / filename
    )

    output_path = (
        OUTPUT_ROOT
        / relative_path
    )

    _write_json(
        output_path,
        profile,
    )

    index = _load_existing_index()

    index[
        "symbol_to_file"
    ][symbol] = str(
        relative_path
    )

    index[
        "company_id_to_file"
    ][company_id] = str(
        relative_path
    )

    index[
        "symbols"
    ] = sorted(
        index[
            "symbol_to_file"
        ]
    )

    index[
        "company_count"
    ] = len(
        index[
            "company_id_to_file"
        ]
    )

    _write_json(
        OUTPUT_ROOT
        / "index.json",
        index,
    )

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build production evidence-first "
            "Company Profile V2."
        )
    )

    parser.add_argument(
        "--symbol",
        required=True,
        help="Ticker symbol, e.g. AAOI",
    )

    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Write per-company JSON and "
            "update company_profile_v2 index."
        ),
    )

    args = parser.parse_args()

    profile = build_company_profile_v2(
        ROOT,
        symbol=args.symbol,
    )

    if args.write:
        output_path = _write_profile(
            profile
        )

        print(
            json.dumps(
                {
                    "status": "written",
                    "symbol":
                        profile["symbol"],
                    "company_id":
                        profile["company_id"],
                    "schema_version":
                        profile[
                            "schema_version"
                        ],
                    "output":
                        str(
                            output_path.relative_to(
                                ROOT
                            )
                        ),
                },
                ensure_ascii=False,
            )
        )

        return 0

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