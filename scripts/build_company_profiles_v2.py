#!/usr/bin/env python3
"""
V2.6.5.8 — Production Promotion Quality Gate

This file intentionally freezes the V2.6.5.7 extractor implementation at the
known-good repository commit fa9f64c341eda97e457c4178686b6409b12dae33 and
overlays promotion-only quality logic.

Important:
- extractor semantics are not changed here;
- product_stack is never rewritten by the promotion gate;
- PROMOTE / REVIEW / FAIL controls production promotion only;
- OpenAI is not used by this script.

The frozen source is loaded from the repository's own Git object database.
That keeps this handoff file small while making the extractor freeze explicit
and reproducible.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from urllib.parse import quote
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

FROZEN_V2657_COMMIT = (
    "fa9f64c341eda97e457c4178686b6409b12dae33"
)
FROZEN_SCRIPT_PATH = (
    "scripts/build_company_profiles_v2.py"
)

CANONICAL_ROOT = (
    ROOT / "data/generated/company_profile_v2"
)


class FrozenExtractorLoadError(RuntimeError):
    pass


def _load_frozen_v2657_namespace() -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "git",
                "show",
                (
                    f"{FROZEN_V2657_COMMIT}:"
                    f"{FROZEN_SCRIPT_PATH}"
                ),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        raise FrozenExtractorLoadError(
            "cannot load frozen V2.6.5.7 extractor from "
            f"{FROZEN_V2657_COMMIT}:{FROZEN_SCRIPT_PATH}"
        ) from exc

    source = result.stdout

    marker = (
        '\nif __name__ == "__main__":\n'
        "    raise SystemExit(main())"
    )

    if marker not in source:
        raise FrozenExtractorLoadError(
            "frozen V2.6.5.7 source has unexpected module tail"
        )

    source = source.replace(
        marker,
        "",
        1,
    )

    namespace: dict[str, Any] = {
        "__name__": "_axiom_frozen_company_profiles_v2657",
        "__file__": str(
            ROOT
            / FROZEN_SCRIPT_PATH
        ),
        "__package__": None,
    }

    exec(
        compile(
            source,
            (
                f"{FROZEN_V2657_COMMIT}:"
                f"{FROZEN_SCRIPT_PATH}"
            ),
            "exec",
        ),
        namespace,
    )

    return namespace


_V2657 = _load_frozen_v2657_namespace()


# Export the frozen implementation first. Promotion-only names below then
# intentionally override selected gate/report functions.
for _name, _value in _V2657.items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value


# === V2.6.5.8 PRODUCTION PROMOTION QUALITY GATE ============================

PROMOTION_GATE_VERSION = "v2.6.5.8"

_PROMOTION_HARD_PREFIX_RE = re.compile(
    r"^(?:"
    r"any\s+|"
    r"are\s+|"
    r"is\s+|"
    r"was\s+|"
    r"were\s+|"
    r"paid\s+licenses?\s+to\s+|"
    r"functionality\s+of\s+|"
    r"completeness\s+of\s+|"
    r"end-to-end\s+platform\s+spanning\s+|"
    r"ev\s+market\s+under\s+"
    r")",
    flags=re.IGNORECASE,
)

_PROMOTION_PROSE_CONTAINS = (
    " designed to comply with ",
    " essentially an operating system ",
    " are based on ",
    " interconnectivity between ",
    " data bandwidth",
    " applicable software solutions",
    " software design tools",
    " listed below:",
    " described in the previous sentence",
    " our devices ",
    " ourselves",
)

_PROMOTION_MARKET_GEOGRAPHY_RE = re.compile(
    r"(?:"
    r"\b(?:Europe|Asia|China|United States|U\.S\.)\b"
    r".*\b(?:market|ourselves|specific product)\b"
    r"|"
    r"\bmarket\s+under\b"
    r")",
    flags=re.IGNORECASE,
)

_PROMOTION_LEGAL_RE = re.compile(
    r"\b(?:"
    r"patents?|patent issued|"
    r"securities|prospectus|"
    r"litigation|regulatory filing"
    r")\b",
    flags=re.IGNORECASE,
)

_PROMOTION_EMBEDDED_FILING_RE = re.compile(
    r"(?:"
    r"•|"
    r"\bOur\s+(?:devices?|products?)\b|"
    r"\bfive\s+major\s+[^:]{0,80}:"
    r")",
    flags=re.IGNORECASE,
)

# Generic organization-name guard. It intentionally does not contain company
# names. Two-or-more title-case tokens ending in an organization head should
# not be promoted as a product.
_PROMOTION_ORGANIZATION_RE = re.compile(
    r"^(?:"
    r"[A-Z][A-Za-z0-9&.+-]*\s+"
    r"){1,5}"
    r"(?:"
    r"Networks?|Systems?|Corporation|Corp\.?|Inc\.?|"
    r"Technologies|Technology|Holdings?|Group"
    r")$"
)

_PROMOTION_EXTERNAL_PRODUCT_RE = re.compile(
    r"^(?:new\s+)?"
    r"(?:"
    r"[A-Z][A-Za-z0-9&.+-]*\s+"
    r"){2,8}"
    r"(?:Ally|Console|Device|Platform)$",
    flags=re.IGNORECASE,
)


def _promotion_issue(
    *,
    issue_type: str,
    symbol: str,
    value: str,
    severity: str = "REVIEW",
) -> dict[str, str]:
    return {
        "type": issue_type,
        "severity": severity,
        "symbol": symbol,
        "value": value,
    }


def _promotion_quality_issue_rows(
    row: dict,
) -> list[dict]:
    """
    Promotion-only diagnostics.

    The extractor output is read but never mutated. Existing V2.6.5.7 quality
    diagnostics remain part of the decision, then V2.6.5.8 adds guards for
    patterns observed to be unsafe for direct frontend promotion.
    """
    symbol = str(
        row.get("symbol")
        or ""
    ).strip().upper()

    products = _record_products(
        row
    )

    if not products:
        return [
            _promotion_issue(
                issue_type="EMPTY_PRODUCT_STACK",
                severity="FAIL",
                symbol=symbol,
                value="",
            )
        ]

    issues: list[dict] = []

    for issue in _quality_issue_rows(
        row
    ):
        normalized = dict(
            issue
        )

        if (
            normalized.get("type")
            == "EMPTY_PRODUCT_STACK"
        ):
            normalized["severity"] = "FAIL"
        else:
            normalized["severity"] = "REVIEW"

        issues.append(
            normalized
        )

    seen = {
        (
            str(issue.get("type") or ""),
            str(issue.get("value") or ""),
        )
        for issue in issues
    }

    def add(
        issue_type: str,
        value: str,
    ) -> None:
        key = (
            issue_type,
            value,
        )

        if key in seen:
            return

        seen.add(
            key
        )
        issues.append(
            _promotion_issue(
                issue_type=issue_type,
                symbol=symbol,
                value=value,
            )
        )

    for raw_value in products:
        text = re.sub(
            r"\s+",
            " ",
            str(raw_value or ""),
        ).strip()

        if not text:
            continue

        lower = text.casefold()

        if _PROMOTION_HARD_PREFIX_RE.search(
            text
        ):
            add(
                "PROMOTION_NON_PRODUCT_CLAUSE",
                text,
            )
            continue

        if _PROMOTION_EMBEDDED_FILING_RE.search(
            text
        ):
            add(
                "PROMOTION_EMBEDDED_FILING_TEXT",
                text,
            )
            continue

        if any(
            marker in (
                " " + lower + " "
            )
            for marker
            in _PROMOTION_PROSE_CONTAINS
        ):
            add(
                "PROMOTION_FILING_PROSE",
                text,
            )
            continue

        if _PROMOTION_LEGAL_RE.search(
            text
        ):
            add(
                "PROMOTION_LEGAL_OR_PATENT_TEXT",
                text,
            )
            continue

        if _PROMOTION_MARKET_GEOGRAPHY_RE.search(
            text
        ):
            add(
                "PROMOTION_MARKET_OR_GEOGRAPHY",
                text,
            )
            continue

        if _PROMOTION_ORGANIZATION_RE.fullmatch(
            text
        ):
            add(
                "PROMOTION_ORGANIZATION_NAME",
                text,
            )
            continue

        if _PROMOTION_EXTERNAL_PRODUCT_RE.fullmatch(
            text
        ):
            add(
                "PROMOTION_EXTERNAL_PRODUCT",
                text,
            )
            continue

        # Sentence punctuation inside a candidate is a strong sign that an SEC
        # prose fragment crossed a list boundary. Product abbreviations and
        # decimal/model punctuation are not affected by this guard.
        if (
            ". " in text
            and len(
                text.split()
            ) >= 7
        ):
            add(
                "PROMOTION_SENTENCE_BOUNDARY",
                text,
            )
            continue

    return issues


def _promotion_quality_gate(
    row: dict,
) -> dict:
    products = _record_products(
        row
    )

    issues = (
        _promotion_quality_issue_rows(
            row
        )
    )

    fail_issues = [
        issue
        for issue in issues
        if issue.get(
            "severity"
        ) == "FAIL"
    ]

    review_issues = [
        issue
        for issue in issues
        if issue.get(
            "severity"
        ) == "REVIEW"
    ]

    if fail_issues:
        status = "FAIL"
    elif review_issues:
        status = "REVIEW"
    else:
        status = "PROMOTE"

    return {
        "status": status,
        "product_stack_count": len(
            products
        ),
        "issue_count": len(
            issues
        ),
        "issue_types": sorted(
            {
                str(
                    issue.get("type")
                    or ""
                )
                for issue in issues
                if issue.get("type")
            }
        ),
        "issue_samples": issues[:8],
    }


def _promotion_gate_summary(
    rows: list[dict],
) -> dict:
    counts = {
        "PROMOTE": 0,
        "REVIEW": 0,
        "FAIL": 0,
    }

    for row in rows:
        status = str(
            row.get(
                "promotion_status"
            )
            or ""
        )

        if status in counts:
            counts[
                status
            ] += 1

    total = len(
        rows
    )

    return {
        "total": total,
        "promote": counts["PROMOTE"],
        "review": counts["REVIEW"],
        "fail": counts["FAIL"],
        "promotion_rate": (
            round(
                counts["PROMOTE"]
                / total,
                4,
            )
            if total
            else 0.0
        ),
        "usable_rate": (
            round(
                (
                    counts["PROMOTE"]
                    + counts["REVIEW"]
                )
                / total,
                4,
            )
            if total
            else 0.0
        ),
    }


def _production_promotion_gate(
    report: dict,
    *,
    sample_limit: int = 12,
) -> dict:
    metadata = (
        _translation_candidate_metadata()
    )

    rows = []

    for record in (
        report.get("records")
        or []
    ):
        symbol = str(
            record.get("symbol")
            or ""
        ).strip().upper()

        meta = metadata.get(
            symbol,
            {},
        )

        gate = _promotion_quality_gate(
            record
        )

        rows.append(
            {
                "symbol": symbol,
                "theme_id": meta.get(
                    "theme_id"
                ),
                "theme_name": meta.get(
                    "theme_name"
                ),
                "promotion_status": gate[
                    "status"
                ],
                "product_stack_count": gate[
                    "product_stack_count"
                ],
                "issue_count": gate[
                    "issue_count"
                ],
                "issue_types": gate[
                    "issue_types"
                ],
                "issue_samples": gate[
                    "issue_samples"
                ],
            }
        )

    by_symbol = {
        row["symbol"]: row
        for row in rows
    }

    core_rows = [
        row
        for row in rows
        if row.get(
            "theme_id"
        )
        in CORE_TECH_THEME_IDS
    ]

    major_rows = []

    for symbol in MAJOR_TECH_SYMBOLS:
        row = by_symbol.get(
            symbol
        )

        if row is None:
            major_rows.append(
                {
                    "symbol": symbol,
                    "promotion_status":
                        "NOT_IN_UNIVERSE",
                }
            )
        else:
            major_rows.append(
                row
            )

    attention = [
        row
        for row in core_rows
        if row[
            "promotion_status"
        ]
        != "PROMOTE"
    ][
        :max(
            30,
            sample_limit,
        )
    ]

    return {
        "gate_version":
            PROMOTION_GATE_VERSION,
        "definitions": {
            "PROMOTE": (
                "non-empty enriched product stack with no "
                "V2.6.5.7 or V2.6.5.8 promotion blocker"
            ),
            "REVIEW": (
                "usable enriched product stack, but promotion "
                "is blocked pending review"
            ),
            "FAIL": (
                "empty product stack or hard extraction failure"
            ),
        },
        "strategic_universe":
            _promotion_gate_summary(
                rows
            ),
        "core_tech_subset":
            _promotion_gate_summary(
                core_rows
            ),
        "major_tech_gate":
            major_rows,
        "core_tech_attention":
            attention,
        "rows":
            rows,
    }


def _compact_census_report_v2658(
    report: dict,
    *,
    sample_limit: int = 12,
    worst_limit: int = 20,
    expand_symbols: set[str] | None = None,
) -> dict:
    base = _V2657[
        "_compact_census_report"
    ](
        report,
        sample_limit=sample_limit,
        worst_limit=worst_limit,
        expand_symbols=expand_symbols,
    )

    base[
        "schema_version"
    ] = (
        "axiom-company-profile-product-census.v2.6.5.8"
    )

    base[
        "promotion_gate"
    ] = (
        _production_promotion_gate(
            report,
            sample_limit=sample_limit,
        )
    )

    return base


def _pct(
    value: float,
) -> str:
    return (
        f"{value * 100:.1f}%"
    )


def _one_screen_promotion_summary(
    report: dict,
) -> str:
    gate = _production_promotion_gate(
        report,
        sample_limit=12,
    )

    strategic = gate[
        "strategic_universe"
    ]
    core = gate[
        "core_tech_subset"
    ]

    lines = [
        "=== V2.6.5.8 Production Promotion Gate ===",
        "",
        "Strategic universe",
        (
            f"  Total {strategic['total']:>6}   "
            f"PROMOTE {strategic['promote']:>6}   "
            f"REVIEW {strategic['review']:>6}   "
            f"FAIL {strategic['fail']:>6}"
        ),
        (
            f"  Promotion rate "
            f"{_pct(strategic['promotion_rate'])}   "
            f"Usable rate "
            f"{_pct(strategic['usable_rate'])}"
        ),
        "",
        "Core AI / Tech",
        (
            f"  Total {core['total']:>6}   "
            f"PROMOTE {core['promote']:>6}   "
            f"REVIEW {core['review']:>6}   "
            f"FAIL {core['fail']:>6}"
        ),
        (
            f"  Promotion rate "
            f"{_pct(core['promotion_rate'])}   "
            f"Usable rate "
            f"{_pct(core['usable_rate'])}"
        ),
        "",
        "Major Tech",
    ]

    for row in gate[
        "major_tech_gate"
    ]:
        symbol = row[
            "symbol"
        ]

        status = row[
            "promotion_status"
        ]

        if status == "NOT_IN_UNIVERSE":
            lines.append(
                f"  {symbol:<6} NOT_IN_UNIVERSE"
            )
            continue

        issue_types = (
            row.get(
                "issue_types"
            )
            or []
        )

        suffix = (
            "  "
            + ", ".join(
                issue_types
            )
            if issue_types
            else ""
        )

        lines.append(
            f"  {symbol:<6} {status:<7}{suffix}"
        )

    attention = (
        gate.get(
            "core_tech_attention"
        )
        or []
    )

    if attention:
        lines.extend(
            [
                "",
                "Core-tech promotion attention",
            ]
        )

        for row in attention[
            :30
        ]:
            issue_types = (
                ", ".join(
                    row.get(
                        "issue_types"
                    )
                    or []
                )
                or "-"
            )

            lines.append(
                (
                    f"  {row['symbol']:<6} "
                    f"{row['promotion_status']:<7} "
                    f"{issue_types}"
                )
            )

    return "\n".join(
        lines
    )


# Patch only reporting/gating behavior in the frozen namespace. Extraction
# helpers such as _extract_named_products, _extract_section_aware_products,
# _extract_subject_gated_product_lists, _enrich_profile_product_recall and
# _apply_product_recall remain the exact V2.6.5.7 implementation.
_V2657[
    "_production_promotion_gate"
] = _production_promotion_gate
_V2657[
    "_promotion_quality_gate"
] = _promotion_quality_gate
_V2657[
    "_promotion_quality_issue_rows"
] = _promotion_quality_issue_rows



def _snapshot_records(payload: dict) -> list[dict]:
    records = payload.get("records")
    if isinstance(records, list):
        valid = [row for row in records if isinstance(row, dict)]
        if valid and all(isinstance(row.get("product_stack_full"), list) for row in valid):
            return valid
    raise ValueError(
        "snapshot has no complete record-level product stacks; "
        "expected records[].product_stack_full"
    )


def _report_from_snapshot(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("census snapshot root must be an object")
    records = _snapshot_records(payload)
    failures = payload.get("failures") or payload.get("failure_samples") or []
    return {
        "scope": "evidence",
        "_requested_scope": "strategic",
        "records": records,
        "failures": failures,
        "summary": {
            "target_company_count": payload.get("summary", {}).get("target_company_count", len(records)+len(failures)),
            "generated_company_count": len(records),
            "failed_company_count": len(failures),
            "complete": not failures,
        },
        "snapshot_source": str(path),
    }


def _resolve_snapshot_path(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
    else:
        path = (CANONICAL_ROOT / "strategic_product_census_v2657.json").resolve()
    if not path.is_file():
        raise ValueError(f"V2.6.5.7 census snapshot not found: {path}")
    return path


def _canonical_index_payload() -> dict:
    path = CANONICAL_ROOT / "index.json"
    if not path.is_file():
        return {"schema_version":"axiom-company-profile-index.v2.3","symbol_to_file":{},"company_id_to_file":{},"symbols":[],"company_count":0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"canonical index is not an object: {path}")
    payload.setdefault("symbol_to_file", {})
    payload.setdefault("company_id_to_file", {})
    return payload


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    tmp.replace(path)


def _safe_upsert_canonical_profiles(profiles: list[dict]) -> dict:
    index = _canonical_index_payload()
    symbol_to_file = dict(index.get("symbol_to_file") or {})
    company_id_to_file = dict(index.get("company_id_to_file") or {})
    before_symbols = set(symbol_to_file)
    before_company_ids = set(company_id_to_file)
    written = []
    for profile in profiles:
        symbol = str(profile.get("symbol") or "").strip().upper()
        company_id = str(profile.get("company_id") or "").strip()
        products = profile.get("product_stack") or []
        if not symbol or not company_id:
            raise ValueError("safe promotion profile requires symbol and company_id")
        if not isinstance(products, list) or not products:
            raise ValueError(f"{symbol}: safe promotion refuses empty product_stack")
        rel = Path("per-company") / (quote(company_id, safe="") + ".json")
        target = CANONICAL_ROOT / rel
        _write_json_atomic(target, profile)
        readback = json.loads(target.read_text(encoding="utf-8"))
        if readback.get("product_stack") != profile.get("product_stack"):
            raise ValueError(f"{symbol}: canonical product_stack read-back mismatch")
        symbol_to_file[symbol] = str(rel)
        company_id_to_file[company_id] = str(rel)
        written.append({"symbol":symbol,"company_id":company_id,"relative_path":str(rel),"product_stack_count":len(products)})
    if not before_symbols <= set(symbol_to_file):
        raise ValueError("safe promotion invariant failed: existing symbol index entry lost")
    if not before_company_ids <= set(company_id_to_file):
        raise ValueError("safe promotion invariant failed: existing company index entry lost")
    index["symbol_to_file"] = dict(sorted(symbol_to_file.items()))
    index["company_id_to_file"] = dict(sorted(company_id_to_file.items()))
    index["symbols"] = sorted(symbol_to_file)
    index["company_count"] = len(company_id_to_file)
    _write_json_atomic(CANONICAL_ROOT / "index.json", index)
    return {
        "written_count": len(written),
        "company_count_before": len(before_company_ids),
        "company_count_after": len(company_id_to_file),
        "preserved_existing_symbols": before_symbols <= set(index["symbol_to_file"]),
        "written": written,
    }


def _promotion_candidates_from_snapshot(snapshot_path: Path) -> tuple[list[str], dict]:
    report = _report_from_snapshot(snapshot_path)
    gate = _production_promotion_gate(report, sample_limit=12)
    symbols = [row["symbol"] for row in gate.get("rows", []) if row.get("promotion_status") == "PROMOTE"]
    return symbols, gate


def _safe_promotion_run(snapshot_path: Path, write: bool, limit: int | None) -> dict:
    candidates, snapshot_gate = _promotion_candidates_from_snapshot(snapshot_path)
    if limit is not None:
        if limit <= 0: raise ValueError("--promotion-limit must be > 0")
        candidates = candidates[:limit]
    report = build_company_profile_batch(ROOT, scope="evidence", symbols=candidates)
    report["_requested_scope"] = "strategic"
    _apply_product_recall(report)
    rebuild_gate = _production_promotion_gate(report, sample_limit=12)
    status_by_symbol = {row["symbol"]:row["promotion_status"] for row in rebuild_gate.get("rows", [])}
    still_promote = [s for s in candidates if status_by_symbol.get(s) == "PROMOTE"]
    downgraded = [{"symbol":s,"status":status_by_symbol.get(s,"MISSING")} for s in candidates if status_by_symbol.get(s) != "PROMOTE"]
    profiles_by_symbol = {str(p.get("symbol") or "").upper():p for p in report.get("_canonical_profiles", [])}
    result = {
        "gate_version": PROMOTION_GATE_VERSION,
        "mode": "safe_promotion_writer",
        "snapshot": str(snapshot_path),
        "snapshot_promote_count": snapshot_gate["strategic_universe"]["promote"],
        "selected_candidate_count": len(candidates),
        "revalidated_promote_count": len(still_promote),
        "downgraded_count": len(downgraded),
        "downgraded": downgraded,
        "write_requested": write,
    }
    if not write:
        result["write_status"] = "dry_run"
        result["promote_symbols"] = still_promote
        return result
    profiles = [profiles_by_symbol[s] for s in still_promote if s in profiles_by_symbol]
    result["write_status"] = "written"
    result["write_result"] = _safe_upsert_canonical_profiles(profiles)
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="V2.6.5.8 Company Profile promotion gate and safe writer")
    parser.add_argument("--scope", choices=("published","strategic"), default="strategic")
    parser.add_argument("--symbol", action="append", default=[])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--full-report", action="store_true")
    parser.add_argument("--diagnostic-limit", type=int, default=12)
    parser.add_argument("--worst-limit", type=int, default=20)
    parser.add_argument("--one-screen", action="store_true")
    parser.add_argument("--census-snapshot", help="Existing V2.6.5.7 strategic product census JSON")
    parser.add_argument("--promote-from-snapshot", action="store_true", help="Rebuild only snapshot PROMOTE symbols and revalidate")
    parser.add_argument("--promotion-limit", type=int, help="Optional canary limit for safe promotion")
    args = parser.parse_args()

    if args.promote_from_snapshot:
        try:
            snapshot = _resolve_snapshot_path(args.census_snapshot)
            result = _safe_promotion_run(snapshot, args.write, args.promotion_limit)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status":"blocked","gate_version":PROMOTION_GATE_VERSION,"error":str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.write:
        print(json.dumps({"write_status":"blocked","gate_version":PROMOTION_GATE_VERSION,"write_error":"Destructive batch --write is disabled. Use --promote-from-snapshot --write."}, ensure_ascii=False, indent=2))
        return 2

    explicit_symbols = [str(s).strip().upper() for s in args.symbol if str(s).strip()]
    if explicit_symbols:
        report = build_company_profile_batch(ROOT, scope="evidence", symbols=explicit_symbols)
        report["_requested_scope"] = args.scope
        _apply_product_recall(report)
    elif args.scope == "strategic":
        try:
            report = _report_from_snapshot(_resolve_snapshot_path(args.census_snapshot))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status":"blocked","gate_version":PROMOTION_GATE_VERSION,"error":str(exc)}, ensure_ascii=False, indent=2))
            return 2
    else:
        report = build_company_profile_batch(ROOT, scope="published", symbols=[])
        report["_requested_scope"] = args.scope
        _apply_product_recall(report)

    report["promotion_gate"] = _production_promotion_gate(report, sample_limit=max(1,args.diagnostic_limit))
    if args.one_screen or (args.scope == "strategic" and not explicit_symbols and not args.full_report):
        print(_one_screen_promotion_summary(report))
    elif args.full_report:
        print(json.dumps(_public_report(report), ensure_ascii=False, indent=2))
    else:
        output = _compact_census_report_v2658(report, sample_limit=max(1,args.diagnostic_limit), worst_limit=max(1,args.worst_limit), expand_symbols=set(explicit_symbols))
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if report.get("summary",{}).get("complete",True) else 1


if __name__ == "__main__":
    raise SystemExit(main())