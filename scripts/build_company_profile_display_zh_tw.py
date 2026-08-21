#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT / "src") not in sys.path:
    sys.path.insert(
        0,
        str(ROOT / "src"),
    )


from axiom_engine.company_profile_v2.display_zh_tw import (  # noqa: E402
    build_company_profile_display_zh_tw,
)


CANONICAL_ROOT = (
    ROOT
    / "data/generated/company_profile_v2"
)

OUTPUT_ROOT = (
    ROOT
    / "data/generated/company_profile_display_zh_tw"
)

TRANSLATION_CENSUS = (
    CANONICAL_ROOT
    / "translation_universe_census_v2640.json"
)

DEFAULT_MODEL = "gpt-4.1-mini"

OPENAI_CACHE_ROOT = (
    OUTPUT_ROOT / ".openai_cache"
)

AI_THEME_IDS = {
    "theme:ai_infrastructure",
    "theme:artificial_intelligence",
}


class CanonicalHandoffError(RuntimeError):
    """Raised when display/translation cannot prove canonical handoff integrity."""


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


def _load_json(
    path: Path,
) -> object:
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except FileNotFoundError as exc:
        raise CanonicalHandoffError(
            f"canonical handoff file not found: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise CanonicalHandoffError(
            f"canonical handoff file is invalid JSON: {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise CanonicalHandoffError(
            f"cannot read canonical handoff file: {path}: {exc}"
        ) from exc


def _canonical_index() -> dict:
    path = CANONICAL_ROOT / "index.json"
    payload = _load_json(path)

    if not isinstance(payload, dict):
        raise CanonicalHandoffError(
            f"canonical index is not an object: {path}"
        )

    symbol_to_file = payload.get(
        "symbol_to_file"
    )

    if not isinstance(
        symbol_to_file,
        dict,
    ):
        raise CanonicalHandoffError(
            "canonical index has no symbol_to_file mapping"
        )

    return payload


def _load_canonical_profile(
    symbol: str,
) -> dict:
    """Load the already-written production canonical profile.

    This function intentionally has no fallback to build_company_profile_v2().
    Display/translation must consume the same canonical artifact produced by the
    V2.6.5.7 extraction/gate pipeline. Missing or malformed canonical data is a
    hard handoff failure.
    """
    normalized_symbol = (
        str(symbol)
        .strip()
        .upper()
    )

    if not normalized_symbol:
        raise CanonicalHandoffError(
            "canonical handoff requires a symbol"
        )

    index = _canonical_index()
    relative = (
        index.get(
            "symbol_to_file",
            {},
        ).get(
            normalized_symbol
        )
    )

    if not relative:
        raise CanonicalHandoffError(
            "canonical handoff missing symbol "
            f"{normalized_symbol} in "
            f"{CANONICAL_ROOT / 'index.json'}"
        )

    relative_path = Path(
        str(relative)
    )

    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
    ):
        raise CanonicalHandoffError(
            f"unsafe canonical path for {normalized_symbol}: {relative}"
        )

    profile_path = (
        CANONICAL_ROOT
        / relative_path
    )

    payload = _load_json(
        profile_path
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise CanonicalHandoffError(
            f"canonical profile is not an object: {profile_path}"
        )

    actual_symbol = str(
        payload.get("symbol")
        or ""
    ).strip().upper()

    if (
        actual_symbol
        != normalized_symbol
    ):
        raise CanonicalHandoffError(
            "canonical symbol mismatch: "
            f"requested={normalized_symbol} "
            f"loaded={actual_symbol or '<missing>'} "
            f"path={profile_path}"
        )

    company_id = str(
        payload.get("company_id")
        or ""
    ).strip()

    if not company_id:
        raise CanonicalHandoffError(
            f"canonical profile has no company_id: {profile_path}"
        )

    product_stack = (
        payload.get(
            "product_stack"
        )
    )

    if not isinstance(
        product_stack,
        list,
    ):
        raise CanonicalHandoffError(
            "canonical product_stack is not an array: "
            f"{profile_path}"
        )

    return payload


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

    if not isinstance(
        payload,
        dict,
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

    # Match the canonical/display batch convention without importing the
    # extractor/batch layer back into this translation-only CLI.
    from urllib.parse import quote

    relative_path = (
        Path("per-company")
        / (
            quote(
                company_id,
                safe="",
            )
            + ".json"
        )
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


def _load_translation_candidates() -> list[dict]:
    if not TRANSLATION_CENSUS.is_file():
        raise FileNotFoundError(
            f"translation census not found: "
            f"{TRANSLATION_CENSUS.relative_to(ROOT)}"
        )

    payload = json.loads(
        TRANSLATION_CENSUS.read_text(
            encoding="utf-8"
        )
    )

    rows = payload.get(
        "translation_candidates"
    ) or []

    return [
        row
        for row in rows
        if isinstance(row, dict)
    ]


def _resolve_symbols(
    *,
    symbols: list[str] | None,
    ai_only: bool,
) -> list[str]:
    if symbols:
        return sorted(
            {
                str(symbol)
                .strip()
                .upper()
                for symbol in symbols
                if str(symbol).strip()
            }
        )

    if not ai_only:
        return []

    rows = _load_translation_candidates()

    selected = {
        str(row.get("symbol") or "")
        .strip()
        .upper()
        for row in rows
        if row.get("theme_id")
        in AI_THEME_IDS
        and row.get("symbol")
    }

    return sorted(selected)


def _extract_translation_surface(
    profile: dict,
) -> dict:
    summary = str(
        (
            profile.get("company_summary")
            or {}
        ).get(
            "one_line_business"
        )
        or ""
    ).strip()

    product_stack = [
        str(value).strip()
        for value in (
            profile.get("product_stack")
            or []
        )
        if str(value).strip()
    ]

    market_products = {}
    raw_market_products = (
        profile.get("market_products")
        or {}
    )

    if isinstance(
        raw_market_products,
        dict,
    ):
        for key, values in (
            raw_market_products.items()
        ):
            clean = [
                str(value).strip()
                for value in (
                    values
                    or []
                )
                if str(value).strip()
            ]

            if clean:
                market_products[
                    str(key)
                ] = clean

    markets = [
        str(value).strip()
        for value in (
            profile.get("markets")
            or []
        )
        if str(value).strip()
    ]

    customer_types = [
        str(value).strip()
        for value in (
            profile.get("customer_types")
            or []
        )
        if str(value).strip()
    ]

    return {
        "company_summary":
            summary or None,
        "product_stack":
            product_stack,
        "market_products":
            market_products,
        "markets":
            markets,
        "customer_types":
            customer_types,
        "core_technologies":
            profile.get("core_technologies") or [],
        "ai_exposure":
            profile.get("ai_exposure"),
        "demand_drivers":
            profile.get("demand_drivers") or [],
        "strategy_changes":
            profile.get("strategy_changes") or [],
    }


def _assert_product_handoff(
    *,
    profile: dict,
    translation_source: dict,
) -> None:
    canonical_products = [
        str(value).strip()
        for value in (
            profile.get(
                "product_stack"
            )
            or []
        )
        if str(value).strip()
    ]

    source_products = (
        translation_source.get(
            "product_stack"
        )
    )

    if (
        source_products
        != canonical_products
    ):
        raise CanonicalHandoffError(
            "product_stack handoff mismatch: "
            "canonical written product_stack != "
            "translation_source.product_stack"
        )


def _build_translation_prompt(
    *,
    symbol: str,
    source: dict,
) -> str:
    return (
        "你是美股研究資料的繁體中文翻譯器。"
        "請把以下英文 Company Profile 翻成台灣繁體中文。\n"
        "規則：\n"
        "1. 只能翻譯來源已有內容，不得新增、推論、補齊任何公司事實。\n"
        "2. 缺失欄位維持 null、空陣列或空物件，不得自行補內容。\n"
        "3. 保留原本 JSON keys 與資料結構，不得增加或刪除 key。\n"
        "4. 公司名、產品品牌、技術標準、商標可保留英文；"
        "產業與商業描述翻成自然、專業的台灣繁中。\n"
        "5. 不要提供投資建議、估值、評論、摘要、解釋或 Markdown。\n"
        "6. 如果來源 fragment 明顯像 SEC 法律文字、客戶名稱、"
        "競爭者名稱或不完整片段，只忠實翻譯，不要美化成新的產品或市場事實。\n"
        "7. 陣列項目數與順序必須和來源完全一致，不得合併、刪除或新增項目。\n"
        "8. 品牌、產品家族、型號、技術標準與商標必須保留原文拼寫；"
        "例如 Aries、Leo、Scorpio、COSMOS、EPYC、Instinct、Ryzen、Radeon、"
        "Pensando、PCIe、CXL、Ethernet。\n"
        "9. 只回傳 JSON。\n\n"
        f"SYMBOL: {symbol}\n"
        "SOURCE_JSON:\n"
        + json.dumps(
            source,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _translation_cache_key(
    *,
    model: str,
    symbol: str,
    source: dict,
) -> str:
    canonical = json.dumps(
        source,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()[:20]

    safe_model = (
        model.replace("/", "_")
        .replace(":", "_")
    )

    return (
        f"{symbol.upper()}__"
        f"{safe_model}__"
        f"{digest}.json"
    )


def _validate_translation_shape(
    *,
    source: object,
    translated: object,
    path: str = "$",
) -> None:
    """Translation may change strings, never the JSON structure/cardinality."""
    if source is None:
        if translated is not None:
            raise ValueError(
                f"translation shape mismatch at {path}: expected null"
            )
        return

    if isinstance(source, dict):
        if not isinstance(translated, dict):
            raise ValueError(
                f"translation shape mismatch at {path}: expected object"
            )
        if set(translated) != set(source):
            missing = sorted(set(source) - set(translated))
            extra = sorted(set(translated) - set(source))
            raise ValueError(
                f"translation keys mismatch at {path}: "
                f"missing={missing} extra={extra}"
            )
        for key, value in source.items():
            _validate_translation_shape(
                source=value,
                translated=translated[key],
                path=f"{path}.{key}",
            )
        return

    if isinstance(source, list):
        if not isinstance(translated, list):
            raise ValueError(
                f"translation shape mismatch at {path}: expected array"
            )
        if len(translated) != len(source):
            raise ValueError(
                f"translation item-count mismatch at {path}: "
                f"source={len(source)} translated={len(translated)}"
            )
        for index, value in enumerate(source):
            _validate_translation_shape(
                source=value,
                translated=translated[index],
                path=f"{path}[{index}]",
            )
        return

    if isinstance(source, bool):
        if not isinstance(translated, bool):
            raise ValueError(
                f"translation type mismatch at {path}: expected bool"
            )
        return

    if isinstance(source, (int, float)):
        if (
            not isinstance(translated, (int, float))
            or isinstance(translated, bool)
        ):
            raise ValueError(
                f"translation type mismatch at {path}: expected number"
            )
        return

    if not isinstance(translated, str):
        raise ValueError(
            f"translation type mismatch at {path}: expected string"
        )


def _load_translation_cache(
    *,
    model: str,
    symbol: str,
    source: dict,
) -> dict | None:
    path = (
        OPENAI_CACHE_ROOT
        / _translation_cache_key(
            model=model,
            symbol=symbol,
            source=source,
        )
    )

    if not path.is_file():
        return None

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
        return None

    translated = payload.get(
        "translation"
    )

    if not isinstance(
        translated,
        dict,
    ):
        return None

    try:
        _validate_translation_shape(
            source=source,
            translated=translated,
        )
    except ValueError:
        return None

    return translated


def _write_translation_cache(
    *,
    model: str,
    symbol: str,
    source: dict,
    translation: dict,
) -> Path:
    OPENAI_CACHE_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        OPENAI_CACHE_ROOT
        / _translation_cache_key(
            model=model,
            symbol=symbol,
            source=source,
        )
    )

    _write_json(
        path,
        {
            "symbol": symbol.upper(),
            "model": model,
            "source": source,
            "translation": translation,
        },
    )

    return path


def _translate_with_openai(
    *,
    model: str,
    symbol: str,
    source: dict,
) -> tuple[dict, str]:
    cached = _load_translation_cache(
        model=model,
        symbol=symbol,
        source=source,
    )

    if cached is not None:
        return cached, "CACHE"

    if not os.environ.get(
        "OPENAI_API_KEY"
    ):
        raise RuntimeError(
            "OPENAI_API_KEY is not set"
        )

    from openai import OpenAI

    client = OpenAI()

    response = client.responses.create(
        model=model,
        input=_build_translation_prompt(
            symbol=symbol,
            source=source,
        ),
    )

    text = str(
        response.output_text
        or ""
    ).strip()

    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()

    translated = json.loads(
        text
    )

    if not isinstance(
        translated,
        dict,
    ):
        raise ValueError(
            "OpenAI output is not a JSON object"
        )

    _validate_translation_shape(
        source=source,
        translated=translated,
    )

    _write_translation_cache(
        model=model,
        symbol=symbol,
        source=source,
        translation=translated,
    )

    return translated, "API"


def _build_payload_from_canonical(
    *,
    symbol: str,
) -> tuple[dict, dict, dict]:
    profile = _load_canonical_profile(
        symbol
    )

    source = (
        _extract_translation_surface(
            profile
        )
    )

    _assert_product_handoff(
        profile=profile,
        translation_source=source,
    )

    payload = dict(
        build_company_profile_display_zh_tw(
            ROOT,
            profile=profile,
        )
    )

    return (
        profile,
        source,
        payload,
    )


def _build_openai_payload(
    *,
    symbol: str,
    model: str,
) -> dict:
    profile, source, payload = (
        _build_payload_from_canonical(
            symbol=symbol,
        )
    )

    # Important ordering:
    # canonical read-back + product handoff invariant must pass before any
    # OpenAI cache/API access. A broken handoff therefore costs $0.
    _assert_product_handoff(
        profile=profile,
        translation_source=source,
    )

    translated, translation_source = (
        _translate_with_openai(
            model=model,
            symbol=symbol,
            source=source,
        )
    )

    payload[
        "translation_engine"
    ] = {
        "provider": "openai",
        "model": model,
        "mode": "company_profile_translation_only",
        "result_source": translation_source,
        "validation": "exact_json_shape_and_array_cardinality",
        "canonical_handoff": "read_back_verified",
    }

    payload[
        "translation_source"
    ] = source

    payload[
        "translation_zh_tw"
    ] = translated

    return payload


def _run_one(
    *,
    symbol: str,
    use_openai: bool,
    model: str,
    write: bool,
) -> dict:
    if use_openai:
        payload = (
            _build_openai_payload(
                symbol=symbol,
                model=model,
            )
        )
    else:
        _, source, payload = (
            _build_payload_from_canonical(
                symbol=symbol,
            )
        )

        # Expose the exact source even in non-OpenAI preview mode so the
        # canonical -> display/translation handoff can be inspected without
        # spending API money.
        payload = dict(
            payload
        )
        payload[
            "translation_source"
        ] = source
        payload[
            "canonical_handoff"
        ] = "read_back_verified"

    result = {
        "symbol":
            str(
                payload["symbol"]
            ).upper(),
        "company_id":
            payload["company_id"],
        "schema_version":
            payload["schema_version"],
        "payload":
            payload,
    }

    if write:
        output_path = (
            _write_payload(
                payload
            )
        )

        result[
            "status"
        ] = "written"

        result[
            "output"
        ] = str(
            output_path.relative_to(
                ROOT
            )
        )
    else:
        result[
            "status"
        ] = "preview"

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build zh-TW display payload from the already-written "
            "Company Profile V2 canonical artifact; optionally use "
            "OpenAI for translation-only handoff."
        )
    )

    parser.add_argument(
        "--symbol",
        help=(
            "Single ticker symbol, e.g. NVDA. "
            "Backward-compatible with the original CLI."
        ),
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        help=(
            "Multiple ticker symbols, e.g. "
            "--symbols NVDA AMD ALAB"
        ),
    )

    parser.add_argument(
        "--ai-only",
        action="store_true",
        help=(
            "Use all translation-eligible companies "
            "from AI Infrastructure and Artificial Intelligence "
            "in translation_universe_census_v2640.json."
        ),
    )

    parser.add_argument(
        "--openai",
        action="store_true",
        help=(
            "Translate Company Profile fields with OpenAI. "
            "Canonical read-back invariant is checked first."
        ),
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            f"OpenAI model. Default: {DEFAULT_MODEL}"
        ),
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

    explicit_symbols = []

    if args.symbol:
        explicit_symbols.append(
            args.symbol
        )

    if args.symbols:
        explicit_symbols.extend(
            args.symbols
        )

    symbols = _resolve_symbols(
        symbols=(
            explicit_symbols
            or None
        ),
        ai_only=args.ai_only,
    )

    if not symbols:
        parser.error(
            "provide --symbol, --symbols, or --ai-only"
        )

    results = []

    for symbol in symbols:
        result = _run_one(
            symbol=symbol,
            use_openai=args.openai,
            model=args.model,
            write=args.write,
        )

        results.append(
            result
        )

        if len(symbols) > 1:
            if args.write:
                print(
                    json.dumps(
                        {
                            "status":
                                result["status"],
                            "symbol":
                                result["symbol"],
                            "company_id":
                                result["company_id"],
                            "model":
                                (
                                    args.model
                                    if args.openai
                                    else None
                                ),
                            "output":
                                result.get("output"),
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                print()
                print(
                    f"=== {result['symbol']} ==="
                )
                print(
                    json.dumps(
                        result["payload"],
                        ensure_ascii=False,
                        indent=2,
                    )
                )

    if len(results) == 1:
        result = results[0]

        if args.write:
            print(
                json.dumps(
                    {
                        "status":
                            result["status"],
                        "symbol":
                            result["symbol"],
                        "company_id":
                            result["company_id"],
                        "schema_version":
                            result["schema_version"],
                        "output":
                            result.get("output"),
                        "model":
                            (
                                args.model
                                if args.openai
                                else None
                            ),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(
                json.dumps(
                    result["payload"],
                    ensure_ascii=False,
                    indent=2,
                )
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())