#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(
        0,
        str(ROOT / "src"),
    )


from axiom_engine.company_profile_v2 import (  # noqa: E402
    build_company_profile_v2,
)

from axiom_engine.company_profile_v2.display_zh_tw import (  # noqa: E402
    build_company_profile_display_zh_tw,
)


OUTPUT_ROOT = (
    ROOT
    / "data/generated/company_profile_display_zh_tw"
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


def _filename(
    company_id: str,
) -> str:
    return (
        quote(
            company_id,
            safe="",
        )
        + ".json"
    )


def _load_index() -> dict:
    path = OUTPUT_ROOT / "index.json"

    if not path.exists():
        return {
            "schema_version":
                "axiom-company-profile-display-index.zh-tw.v2.4",
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
        "axiom-company-profile-display-index.zh-tw.v2.4"
    )

    return payload


def _write_payload(
    payload: dict,
) -> Path:
    company_id = str(
        payload["company_id"]
    )

    symbol = str(
        payload["symbol"]
    ).upper()

    relative_path = (
        Path("per-company")
        / _filename(company_id)
    )

    output_path = (
        OUTPUT_ROOT
        / relative_path
    )

    _write_json(
        output_path,
        payload,
    )

    index = _load_index()

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
            "Build zh-TW display payload from "
            "Company Profile V2.3."
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
            "Write per-company zh-TW display JSON "
            "and update its index."
        ),
    )

    args = parser.parse_args()

    profile = build_company_profile_v2(
        ROOT,
        symbol=args.symbol,
    )

    payload = (
        build_company_profile_display_zh_tw(
            ROOT,
            profile=profile,
        )
    )

    if args.write:
        output_path = _write_payload(
            payload
        )

        print(
            json.dumps(
                {
                    "status":
                        "written",
                    "symbol":
                        payload["symbol"],
                    "company_id":
                        payload["company_id"],
                    "schema_version":
                        payload[
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
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())