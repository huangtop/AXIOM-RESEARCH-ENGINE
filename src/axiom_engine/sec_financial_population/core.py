from __future__ import annotations
import json
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote
from axiom_engine.sec_financial_loader.core import METRICS, _debt, _fiscal_year, _latest_annual

EXTRA_METRICS = {
    "stockholders_equity": {
        "statement": "balance_sheet",
        "period_type": "instant",
        "unit": "currency",
        "tags": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    },
    "shares_outstanding_instant": {
        "statement": "balance_sheet",
        "period_type": "instant",
        "unit": "shares",
        "tags": ["CommonStocksIncludingAdditionalPaidInCapitalMember", "CommonStockSharesOutstanding"],
    },
    "ebitda": {
        "statement": "income_statement",
        "period_type": "duration",
        "unit": "currency",
        "tags": ["EarningsBeforeInterestTaxesDepreciationAndAmortization"],
    },
}

QUARTERLY_METRICS = {
    key: value
    for key, value in METRICS.items()
    if key in {"revenue", "net_income", "operating_cash_flow", "capital_expenditures", "diluted_shares_outstanding"}
}
QUARTERLY_METRICS["diluted_eps"] = {
    "statement": "income_statement",
    "period_type": "duration",
    "unit": "currency_per_share",
    "tags": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
}

PUBLIC_SOURCE_KEYS = {
    "provider",
    "formula_version",
    "source_fact_ids",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _public_fact(row: Mapping[str, Any]) -> dict[str, Any]:
    """Remove parser-only SEC provenance before writing public snapshots."""
    public = dict(row)
    source = row.get("source")
    if isinstance(source, Mapping):
        public["source"] = {
            str(key): value
            for key, value in source.items()
            if key in PUBLIC_SOURCE_KEYS
        }
    return public


def _scope(root: Path, company_ids: set[str] | None = None) -> list[dict[str, str]]:
    companies = _load(root / "data/universe/companies.json")
    identity = _load(root / "data/generated/security_identity/security_identity_normalization.json")
    included = {row["company_id"] for row in identity["companies"] if row["valuation_scope_status"] == "included"}
    output = []
    for row in companies:
        if row["company_id"] not in included or (company_ids is not None and row["company_id"] not in company_ids):
            continue
        cik = str((row.get("metadata") or {}).get("cik") or "").zfill(10)
        if cik.strip("0"):
            output.append({"company_id": row["company_id"], "cik": cik})
    return sorted(output, key=lambda row: row["company_id"])


def _fact(company_id: str, cik: str, metric: str, spec: Mapping[str, Any], found: tuple[str, Mapping[str, Any]]) -> dict[str, Any]:
    tag, row = found
    return {
        "financial_fact_id": f"financial_fact:{cik}:{metric}:{row['end']}:FY",
        "company_id": company_id,
        "metric": metric,
        "value": str(row["val"]),
        "unit": spec["unit"],
        "currency": "USD" if spec["unit"] == "currency" else None,
        "period_type": spec["period_type"],
        "period_start": row.get("start"),
        "period_end": row["end"],
        "fiscal_year": _fiscal_year(dict(row)),
        "fiscal_period": "FY",
        "statement": spec["statement"],
        "form_type": row.get("form"),
        "accession_number": row.get("accn"),
        "source": {"provider": "sec_companyfacts", "cik": cik, "xbrl_tag": tag},
    }


def _quarter_unit_rows(fact: Mapping[str, Any], unit: str) -> list[Mapping[str, Any]]:
    units = fact.get("units") if isinstance(fact.get("units"), Mapping) else {}
    preferred = {
        "currency": ("USD", "usd"),
        "shares": ("shares", "SHARES"),
        "currency_per_share": ("USD/shares", "usd/shares", "USD / shares"),
    }[unit]
    for name in preferred:
        if name in units and isinstance(units[name], list):
            return units[name]
    return []


def _is_discrete_quarter(row: Mapping[str, Any]) -> bool:
    if str(row.get("fp") or "").upper() not in {"Q1", "Q2", "Q3", "Q4"}:
        return False
    if str(row.get("form") or "").upper() not in {"10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A"}:
        return False
    try:
        days = (date.fromisoformat(str(row["end"])) - date.fromisoformat(str(row["start"]))).days
    except (KeyError, TypeError, ValueError):
        return False
    return 60 <= days <= 120


def _is_annual_duration(row: Mapping[str, Any]) -> bool:
    if str(row.get("fp") or "").upper() != "FY":
        return False
    try:
        days = (date.fromisoformat(str(row["end"])) - date.fromisoformat(str(row["start"]))).days
    except (KeyError, TypeError, ValueError):
        return False
    return 300 <= days <= 430


def _duration_days(row: Mapping[str, Any]) -> int | None:
    try:
        return (date.fromisoformat(str(row["end"])) - date.fromisoformat(str(row["start"]))).days
    except (KeyError, TypeError, ValueError):
        return None


def _observation_rank(row: Mapping[str, Any], tag_priority: int) -> tuple[str, str, int]:
    # Later filings can restate comparative values (for example after a stock
    # split), so keep the newest observation while deriving period identity from
    # dates rather than the newer filing's misleading \`fy\` value.
    return (str(row.get("filed") or ""), str(row.get("accn") or ""), -tag_priority)


def _filing_lag(row: Mapping[str, Any]) -> int:
    try:
        return max((date.fromisoformat(str(row["filed"])) - date.fromisoformat(str(row["end"]))).days, 0)
    except (KeyError, TypeError, ValueError):
        return 100_000


def _derive_additive_q4(company_id: str, cik: str, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Derive additive Q4 facts from same-FY FY and first-nine-month durations.
    Annual and nine-month durations must share a fiscal start; no subtraction is
    performed for diluted EPS or weighted-average shares. Retain provenance.
    """
    from datetime import timedelta
    gaap = ((payload.get("facts") or {}).get("us-gaap") or {})
    additive = {"revenue", "net_income", "operating_cash_flow", "capital_expenditures"}
    result = []
    for metric, spec in QUARTERLY_METRICS.items():
        if metric not in additive:
            continue
        candidates = []
        for priority, tag in enumerate(spec["tags"]):
            fact = gaap.get(tag)
            if not isinstance(fact, Mapping):
                continue
            for observation in _quarter_unit_rows(fact, str(spec["unit"])):
                duration = _duration_days(observation)
                if duration is None or observation.get("val") is None:
                    continue
                if str(observation.get("form") or "").upper() not in {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A"}:
                    continue
                if 300 <= duration <= 430 and str(observation.get("fp") or "").upper() == "FY":
                    candidates.append(("FY", priority, tag, observation))
                elif 240 <= duration <= 310 and str(observation.get("fp") or "").upper() == "Q3":
                    candidates.append(("9M", priority, tag, observation))
        annuals = [item for item in candidates if item[0] == "FY"]
        nine_months = [item for item in candidates if item[0] == "9M"]
        for _, annual_priority, annual_tag, annual in annuals:
            try:
                annual_start = date.fromisoformat(str(annual["start"]))
                annual_end = date.fromisoformat(str(annual["end"]))
            except (KeyError, TypeError, ValueError):
                continue
            matched = []
            for _, nine_priority, nine_tag, nine in nine_months:
                try:
                    nine_start = date.fromisoformat(str(nine["start"]))
                    nine_end = date.fromisoformat(str(nine["end"]))
                except (KeyError, TypeError, ValueError):
                    continue
                gap = (annual_end - nine_end).days
                if abs((annual_start - nine_start).days) > 7 or not 60 <= gap <= 120:
                    continue
                if str(nine.get("filed") or "") > str(annual.get("filed") or ""):
                    continue
                matched.append((nine_priority, nine_tag, nine, nine_end))
            if not matched:
                continue
            # Prefer the same accounting concept; then the newest 9M observation.
            nine_priority, nine_tag, nine, nine_end = max(
                matched,
                key=lambda item: (item[1] == annual_tag, str(item[2].get("filed") or ""), -item[0]),
            )
            value = Decimal(str(annual["val"])) - Decimal(str(nine["val"]))
            fiscal_year = int(annual.get("fy") or annual_end.year)
            result.append({
                "financial_fact_id": f"quarterly_financial_fact:{cik}:{metric}:{annual_end.isoformat()}:Q4",
                "company_id": company_id,
                "metric": metric,
                "value": format(value, "f"),
                "unit": spec["unit"],
                "currency": "USD",
                "period_type": "duration",
                "period_start": (nine_end + timedelta(days=1)).isoformat(),
                "period_end": annual_end.isoformat(),
                "fiscal_year": fiscal_year,
                "fiscal_period": "Q4",
                "statement": spec["statement"],
                "form_type": annual.get("form"),
                "filed_at": annual.get("filed"),
                "accession_number": annual.get("accn"),
                "source": {
                    "provider": "sec_companyfacts", "cik": cik,
                    "xbrl_tag": annual_tag,
                    "period_selection": "derived_q4_from_fy_minus_9m",
                    "source_accessions": list(dict.fromkeys([a for a in (annual.get("accn"), nine.get("accn")) if a])),
                },
            })
    # Multiple annual comparative observations may exist: prefer latest filing.
    latest = {}
    for row in result:
        key = (row["metric"], row["period_end"])
        existing = latest.get(key)
        if existing is None or (str(row["filed_at"]), str(row["accession_number"])) > (str(existing["filed_at"]), str(existing["accession_number"])):
            latest[key] = row
    return list(latest.values())


def _normalize_quarterly_identity(rows: list[dict[str, Any]], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Anchor fiscal quarters to annual period ends, then deduplicate comparatives."""
    gaap = ((payload.get("facts") or {}).get("us-gaap") or {})
    annuals: dict[str, tuple[tuple[int, str], int]] = {}
    for concept in gaap.values():
        if not isinstance(concept, Mapping):
            continue
        units = concept.get("units") or {}
        if not isinstance(units, Mapping):
            continue
        for observations in units.values():
            if not isinstance(observations, list):
                continue
            for obs in observations:
                if not isinstance(obs, Mapping) or str(obs.get("fp") or "").upper() != "FY":
                    continue
                if str(obs.get("form") or "").upper() not in {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}:
                    continue
                duration = _duration_days(obs)
                if duration is None or not 300 <= duration <= 430:
                    continue
                end, filed = str(obs.get("end") or ""), str(obs.get("filed") or "")
                try:
                    lag = (date.fromisoformat(filed) - date.fromisoformat(end)).days
                    fy = int(obs.get("fy") or 0)
                except (ValueError, TypeError):
                    continue
                if not (0 <= lag <= 550 and 1990 <= fy <= 2200):
                    continue
                rank = (lag, filed)
                old = annuals.get(end)
                if old is None or rank < old[0]:
                    annuals[end] = (rank, fy)
    anchors = sorted((date.fromisoformat(end), value[1]) for end, value in annuals.items())
    # Prefer original, timely-filed 10-Q quarter identities.
    # Later comparative filings may carry different fy/fp labels.
    original_identities = {}
    for concept in gaap.values():
        if not isinstance(concept, Mapping):
            continue
        units = concept.get("units") or {}
        if not isinstance(units, Mapping):
            continue
        for observations in units.values():
            if not isinstance(observations, list):
                continue
            for obs in observations:
                if not isinstance(obs, Mapping):
                    continue
                if not _is_discrete_quarter(obs):
                    continue
                end_string = str(obs.get("end") or "")
                filed_string = str(obs.get("filed") or "")
                try:
                    lag = (
                        date.fromisoformat(filed_string)
                        - date.fromisoformat(end_string)
                    ).days
                    fy = int(obs.get("fy") or 0)
                except (ValueError, TypeError):
                    continue
                if not (0 <= lag <= 120 and 1990 <= fy <= 2200):
                    continue
                identity = (fy, str(obs["fp"]).upper())
                previous = original_identities.get(end_string)
                if previous is None or lag < previous[0]:
                    original_identities[end_string] = (lag, identity)
    def fiscal_identity(end_string: str) -> tuple[int, str] | None:
        try:
            end = date.fromisoformat(end_string)
        except (ValueError, TypeError):
            return None
        for annual_end, fiscal_year in anchors:
            days = (annual_end - end).days
            if days == 0:
                return fiscal_year, "Q4"
            if 60 <= days <= 125:
                return fiscal_year, "Q3"
            if 150 <= days <= 225:
                return fiscal_year, "Q2"
            if 240 <= days <= 315:
                return fiscal_year, "Q1"
        return None
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    def rank(row: Mapping[str, Any]) -> tuple[int, str, str]:
        derived = (row.get("source") or {}).get("period_selection") == "derived_q4_from_fy_minus_9m"
        return (0 if derived else 1, str(row.get("filed_at") or ""), str(row.get("accession_number") or ""))
    for original in rows:
        row = dict(original)
        period_end = str(row.get("period_end") or "")
        original = original_identities.get(period_end)
        identity = original[1] if original is not None else fiscal_identity(period_end)
        if identity:
            row["fiscal_year"], row["fiscal_period"] = identity
            fid = str(row.get("financial_fact_id") or "")
            if fid.startswith("quarterly_financial_fact:"):
                row["financial_fact_id"] = fid.rsplit(":", 1)[0] + ":" + identity[1]
        key = (str(row.get("metric") or ""), str(row.get("period_end") or ""))
        old = chosen.get(key)
        if old is None or rank(row) > rank(old):
            chosen[key] = row
    # Only reconsider identities that actually collide. Uncontested timely
    # 10-Q identities must not be overwritten by calendar assumptions.
    by_identity: dict[tuple[int, str], set[str]] = {}
    for item in chosen.values():
        key = (int(item["fiscal_year"]), str(item["fiscal_period"]))
        by_identity.setdefault(key, set()).add(str(item["period_end"]))
    collided = {key for key, ends in by_identity.items() if len(ends) > 1}
    if collided:
        by_end: dict[str, list[dict[str, Any]]] = {}
        for item in chosen.values():
            by_end.setdefault(str(item["period_end"]), []).append(item)
        # Change only the periods supported by a distinct annual anchor.
        for end, period_rows in by_end.items():
            key = (int(period_rows[0]["fiscal_year"]), str(period_rows[0]["fiscal_period"]))
            if key not in collided:
                continue
            anchored = fiscal_identity(end)
            if anchored is None or anchored == key:
                continue
            for item in period_rows:
                item["fiscal_year"], item["fiscal_period"] = anchored
                fid = str(item.get("financial_fact_id") or "")
                if fid.startswith("quarterly_financial_fact:"):
                    item["financial_fact_id"] = fid.rsplit(":", 1)[0] + ":" + anchored[1]
    return list(chosen.values())


def _repair_annual_separated_quarter_collisions(
    rows: list[dict[str, Any]],
    *,
    diagnostics: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Repair a narrow SEC comparative FY-label error without fabricating quarters.

    If precisely two distinct quarter ends share the same FY/Q and their
    dates are about one year apart, the older period may have inherited the
    newer filing's FY. Reassign the older FY only if every metric for that end
    agrees, the new identity is unused, and the dates support adjacent years.
    Other collisions remain quarantined by the existing safety guard.
    """
    by_end: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_end.setdefault(str(row["period_end"]), []).append(row)
    # Mixed identities at the same period end require separate examination.
    clean_ends: dict[str, tuple[int, str]] = {}
    for end, items in by_end.items():
        identities = {(int(r["fiscal_year"]), str(r["fiscal_period"])) for r in items}
        if len(identities) == 1:
            clean_ends[end] = next(iter(identities))
    by_identity: dict[tuple[int, str], list[str]] = {}
    for end, identity in clean_ends.items():
        by_identity.setdefault(identity, []).append(end)
    occupied = set(clean_ends.values())
    for (fy, quarter), ends in sorted(by_identity.items()):
        if len(ends) != 2 or quarter not in {"Q1", "Q2", "Q3", "Q4"}:
            continue
        older, newer = sorted(ends)
        try:
            elapsed = (date.fromisoformat(newer) - date.fromisoformat(older)).days
        except ValueError:
            continue
        if not 330 <= elapsed <= 400:
            continue
        # Do not invent an extra fiscal year for a fiscal-year transition or
        # override an already represented quarter.
        replacement = (fy - 1, quarter)
        if replacement in occupied:
            continue
        # Require fiscal year to be plausible relative to the newer period.
        # A standard Dec-ending issuer uses FY == calendar year; a non-Dec
        # issuer may use FY == calendar year + 1.
        if fy not in {date.fromisoformat(newer).year, date.fromisoformat(newer).year + 1}:
            continue
        for item in by_end[older]:
            item["fiscal_year"] = replacement[0]
            fid = str(item.get("financial_fact_id") or "")
            if fid.startswith("quarterly_financial_fact:"):
                item["financial_fact_id"] = fid.rsplit(":", 1)[0] + ":" + replacement[1]
        occupied.add(replacement)
        if diagnostics is not None:
            diagnostics.append({
                "reason_code": "COMPARATIVE_FISCAL_YEAR_REPAIRED",
                "company_id": by_end[older][0]["company_id"],
                "period_ends": [older, newer],
                "fiscal_year_before": fy,
                "fiscal_year_after": replacement[0],
                "fiscal_period": quarter,
            })
    return rows


def _resolve_fiscal_quarter_collisions(rows: list[dict[str, Any]], *, diagnostics: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Withhold ambiguous FY/Q assignments rather than publish wrong quarters.
    Some Companyfacts datasets associate two distinct economic periods with one
    fiscal identity (transition years, comparisons, short fiscal years). We
    cannot safely decide from their fy/fp alone which financial period is real.
    These are quarantined; the period's other metrics are also withheld to
    preserve a coherent quarterly timeline. No values are fabricated.
    """
    by_identity: dict[tuple[int, str], set[str]] = {}
    by_end: dict[str, set[tuple[int, str]]] = {}
    for row in rows:
        identity = (int(row["fiscal_year"]), str(row["fiscal_period"]))
        end = str(row["period_end"])
        by_identity.setdefault(identity, set()).add(end)
        by_end.setdefault(end, set()).add(identity)
    ambiguous = {
        end for ends in by_identity.values() if len(ends) > 1 for end in ends
    } | {end for end, ids in by_end.items() if len(ids) > 1}
    if ambiguous and diagnostics is not None:
        diagnostics.append({
            "reason_code": "AMBIGUOUS_FISCAL_QUARTER_QUARANTINED",
            "company_id": rows[0]["company_id"],
            "period_ends": sorted(ambiguous),
        })
    return [row for row in rows if str(row["period_end"]) not in ambiguous]


def _repair_cbrs_quarter_identity_from_sec_frames(
    rows: list[dict[str, Any]], payload: Mapping[str, Any], *,
    cik: str, diagnostics: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Evidence-gated CBRS pilot; do not infer an issuer's FY from calendar alone.

    In Cerebras 2026 10-Q, 2025 Q1 comparatives inherit filing FY2026.
    Require exact SEC duration/frame/accession proof for every reassigned end.
    This issuer-specific pilot must not affect other companies.
    """
    if cik != "0002021728":
        return rows
    expected = {
        "2025-03-31": (2025, "Q1", "2025-01-01", "CY2025Q1", "0001628280-26-044981"),
        "2026-03-31": (2026, "Q1", "2026-01-01", "CY2026Q1", "0001628280-26-044981"),
        "2026-06-30": (2026, "Q2", "2026-04-01", "CY2026Q2", "0001628280-26-056357"),
    }
    # Only restore a period if the corresponding actual SEC Companyfacts
    # observation exists; never manufacture a metric value or a period.
    gaap = ((payload.get("facts") or {}).get("us-gaap") or {})
    proofs: set[str] = set()
    for concept in gaap.values():
        if not isinstance(concept, Mapping):
            continue
        units = concept.get("units") or {}
        if not isinstance(units, Mapping):
            continue
        for observations in units.values():
            if not isinstance(observations, list):
                continue
            for obs in observations:
                if not isinstance(obs, Mapping):
                    continue
                end = str(obs.get("end") or "")
                evidence = expected.get(end)
                if evidence is None:
                    continue
                _, _, start, frame, accession = evidence
                if (str(obs.get("start")) == start
                    and str(obs.get("frame")) == frame
                    and str(obs.get("accn")) == accession
                    and str(obs.get("form")) in {"10-Q", "10-Q/A"}
                    and _is_discrete_quarter(obs)):
                    proofs.add(end)
    adjusted: set[str] = set()
    for row in rows:
        end = str(row.get("period_end") or "")
        if end not in proofs:
            continue
        fy, fp, _, _, _ = expected[end]
        if (int(row["fiscal_year"]), str(row["fiscal_period"])) == (fy, fp):
            continue
        row["fiscal_year"], row["fiscal_period"] = fy, fp
        fid = str(row.get("financial_fact_id") or "")
        if fid.startswith("quarterly_financial_fact:"):
            row["financial_fact_id"] = fid.rsplit(":", 1)[0] + ":" + fp
        adjusted.add(end)
    if adjusted and diagnostics is not None:
        diagnostics.append({
            "reason_code": "CBRS_SEC_FRAME_QUARTER_IDENTITY_REPAIRED",
            "company_id": "company:US-CIK0002021728",
            "period_ends": sorted(adjusted),
            "evidence": "sec_companyfacts_discrete_frame_and_accession",
        })
    return rows


def _repair_priority_technology_quarters(
    rows: list[dict[str, Any]], payload: Mapping[str, Any], *,
    cik: str, diagnostics: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Conservative final-pass identity recovery for three audited SEC issuers.

    Correct ONLY the quarter period identity, based on a timely contemporaneous
    10-Q or annual 10-K.  Never manufacture an absent financial observation.
    SEC Companyfacts `fy` on retrospective 10-Q/10-K observations is the FY
    of the *filing*, not necessarily the FY of the observed period.

    Do not collapse WOLF's 2025-09-28 vs 2025-09-29 based on proximity alone.
    A one-day end adjustment requires a matching metric, start and value in
    the contemporaneous 2025 10-Q, and only removes its proven duplicate.
    """
    if cik not in {"0001108524", "0000895419", "0000704532"}:
        return rows
    gaap = ((payload.get("facts") or {}).get("us-gaap") or {})
    original_by_end: dict[str, tuple[tuple[int, str, str], tuple[int, str]]] = {}
    for concept in gaap.values():
        if not isinstance(concept, Mapping):
            continue
        units = concept.get("units") or {}
        if not isinstance(units, Mapping):
            continue
        for observations in units.values():
            if not isinstance(observations, list):
                continue
            for obs in observations:
                if not isinstance(obs, Mapping) or not _is_discrete_quarter(obs):
                    continue
                if str(obs.get("form") or "").upper() != "10-Q":
                    continue
                end, filed = str(obs.get("end") or ""), str(obs.get("filed") or "")
                fp = str(obs.get("fp") or "").upper()
                if fp not in {"Q1", "Q2", "Q3"}:
                    continue
                try:
                    lag = (date.fromisoformat(filed) - date.fromisoformat(end)).days
                    fy = int(obs["fy"])
                except (KeyError, ValueError, TypeError):
                    continue
                if not 0 <= lag <= 110 or not 1990 <= fy <= 2200:
                    continue
                rank = (lag, filed, str(obs.get("accn") or ""))
                previous = original_by_end.get(end)
                if previous is None or rank < previous[0]:
                    original_by_end[end] = (rank, (fy, fp))

    # Compare directly with original-period 10-K source for annual endings;
    # infer adjacent FY solely from an independently documented prior 10-K.
    original_annual: dict[str, tuple[int, str]] = {}
    for concept in gaap.values():
        if not isinstance(concept, Mapping):
            continue
        for observations in (concept.get("units") or {}).values():
            if not isinstance(observations, list):
                continue
            for obs in observations:
                if not isinstance(obs, Mapping):
                    continue
                if str(obs.get("form") or "").upper() != "10-K" or str(obs.get("fp") or "").upper() != "FY":
                    continue
                days = _duration_days(obs)
                if days is None or not 300 <= days <= 430:
                    continue
                end, filed = str(obs.get("end") or ""), str(obs.get("filed") or "")
                try:
                    lag = (date.fromisoformat(filed) - date.fromisoformat(end)).days
                    fy = int(obs["fy"])
                except (KeyError, ValueError, TypeError):
                    continue
                if not 0 <= lag <= 160:
                    continue
                old = original_annual.get(end)
                if old is None or filed < old[1]:
                    original_annual[end] = (fy, filed)

    # For an annual end whose originating 10-K has an anomalous `fy`,
    # require two consecutive annual ends plus an original-period Q3 anchor.
    annual_identity: dict[str, int] = {}
    for end, (fy, _) in original_annual.items():
        anchor_q3 = []
        for qend, (_, ident) in original_by_end.items():
            if ident[1] != "Q3":
                continue
            try:
                delta = (date.fromisoformat(end) - date.fromisoformat(qend)).days
            except ValueError:
                continue
            if 60 <= delta <= 125:
                anchor_q3.append(ident[0])
        if len(set(anchor_q3)) == 1:
            annual_identity[end] = anchor_q3[0]
        else:
            annual_identity[end] = fy

    changed = set()
    for row in rows:
        end = str(row.get("period_end") or "")
        selection = str((row.get("source") or {}).get("period_selection") or "")
        target = original_by_end.get(end)
        identity = target[1] if target is not None else None
        if selection == "derived_q4_from_fy_minus_9m" and end in annual_identity:
            identity = (annual_identity[end], "Q4")
        if identity is None or identity == (int(row["fiscal_year"]), str(row["fiscal_period"])):
            continue
        row["fiscal_year"], row["fiscal_period"] = identity
        fid = str(row.get("financial_fact_id") or "")
        if fid.startswith("quarterly_financial_fact:"):
            row["financial_fact_id"] = fid.rsplit(":", 1)[0] + ":" + identity[1]
        changed.add(end)
    if changed and diagnostics is not None:
        diagnostics.append({
            "reason_code": "TECH_ORIGINAL_SEC_FILING_IDENTITY_REPAIRED",
            "company_id": f"company:US-CIK{cik}",
            "period_ends": sorted(changed),
            "evidence": "original_period_10q_and_10k",
        })
    return rows


def _quarterly_facts(company_id: str, cik: str, payload: Mapping[str, Any], limit: int = 8, *, diagnostics: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    us_gaap = ((payload.get("facts") or {}).get("us-gaap") or {})
    # A SEC comparative can carry the reporting filing's fy/fp, not the
    # economic quarter's identity. Select per real period end first.
    selected: dict[tuple[str, str], tuple[str, Mapping[str, Any], Mapping[str, Any]]] = {}
    for metric, spec in QUARTERLY_METRICS.items():
        for tag_priority, tag in enumerate(spec["tags"]):
            fact = us_gaap.get(tag)
            if not isinstance(fact, Mapping):
                continue
            for row in _quarter_unit_rows(fact, str(spec["unit"])):
                if row.get("val") is None or not row.get("start") or not row.get("end"):
                    continue
                if not _is_discrete_quarter(row):
                    continue
                key = (metric, str(row["end"]))
                old = selected.get(key)
                if old is None or _observation_rank(row, tag_priority) > _observation_rank(old[1], spec["tags"].index(old[0])):
                    selected[key] = (tag, dict(row), spec)
    derived_q4 = _derive_additive_q4(company_id, cik, payload)
    period_ends = sorted({str(row.get("end")) for _, row, _ in selected.values() if row.get("end")} | {row["period_end"] for row in derived_q4})[-limit:]
    allowed_ends = set(period_ends)
    output: list[dict[str, Any]] = []
    for (metric, period_end), (tag, row, spec) in selected.items():
        if str(row.get("end")) not in allowed_ends:
            continue
        output.append({
            "financial_fact_id": f"quarterly_financial_fact:{cik}:{metric}:{row['end']}:{str(row.get('fp') or '').upper()}",
            "company_id": company_id,
            "metric": metric,
            "value": str(row["val"]),
            "unit": spec["unit"],
            "currency": "USD" if spec["unit"] in {"currency", "currency_per_share"} else None,
            "period_type": "duration",
            "period_start": row.get("start"),
            "period_end": row["end"],
            "fiscal_year": int(row.get("fy") or str(row["end"])[:4]),
            "fiscal_period": str(row.get("fp") or "").upper(),
            "statement": spec["statement"],
            "form_type": row.get("form"),
            "filed_at": row.get("filed"),
            "accession_number": row.get("accn"),
            "source": {"provider": "sec_companyfacts", "cik": cik, "xbrl_tag": tag, "period_selection": row.get("_derivation_type") or "discrete_quarter_60_to_120_days", "source_accessions": row.get("_source_accessions") or [row.get("accn")]},
        })
    # A direct Q4 observation takes precedence over an inferred observation.
    present = {(str(row["metric"]), str(row["period_end"])) for row in output}
    output.extend(row for row in derived_q4 if row["period_end"] in allowed_ends and (row["metric"], row["period_end"]) not in present)
    output = _normalize_quarterly_identity(output, payload)
    output = _repair_annual_separated_quarter_collisions(output, diagnostics=diagnostics)
    output = _repair_cbrs_quarter_identity_from_sec_frames(output, payload, cik=cik, diagnostics=diagnostics)
    output = _repair_priority_technology_quarters(output, payload, cik=cik, diagnostics=diagnostics)
    output = _resolve_fiscal_quarter_collisions(output, diagnostics=diagnostics)
    return sorted(output, key=lambda row: (str(row["period_end"]), str(row["metric"])))


def build_sec_financial_population(
    root: Path,
    *,
    bulk_zip: Path | None = None,
    cache_dir: str = "data/generated/provider_cache/sec/companyfacts",
    limit: int | None = None,
    offset: int = 0,
    write_cache: bool = False,
    cache_ttl_days: int = 90,
    now: datetime | None = None,
    company_ids: list[str] | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    scope = _scope(root, set(company_ids) if company_ids is not None else None)
    source_scope_count = len(scope)
    scope = scope[offset:]
    if limit is not None:
        scope = scope[:limit]
    cache_root = root / cache_dir
    bulk_archive = zipfile.ZipFile(bulk_zip) if bulk_zip else None
    bulk_names = set(bulk_archive.namelist()) if bulk_archive else set()
    facts: list[dict[str, Any]] = []
    quarterly_facts: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    company_coverage: Counter[str] = Counter()
    source_modes: Counter[str] = Counter()
    all_specs = {**METRICS, **EXTRA_METRICS}
    for company in scope:
        cik = company["cik"]
        cache_path = cache_root / f"CIK{cik}.json"
        cache_is_fresh = cache_path.is_file() and current.timestamp() - cache_path.stat().st_mtime <= cache_ttl_days * 86_400
        if cache_is_fresh:
            payload, mode = _load(cache_path), "cache"
        elif f"CIK{cik}.json" in bulk_names and bulk_archive is not None:
            payload = json.loads(bulk_archive.read(f"CIK{cik}.json"))
            mode = "sec_bulk"
            if write_cache:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        elif cache_path.is_file():
            payload, mode = _load(cache_path), "stale_cache_fallback"
        else:
            diagnostics.append({**company, "reason_code": "SEC_COMPANYFACTS_NOT_AVAILABLE"})
            continue
        source_modes[mode] += 1
        quarterly_facts.extend(_quarterly_facts(company["company_id"], cik, payload, diagnostics=diagnostics))
        company_facts: dict[str, dict[str, Any]] = {}
        for metric, spec in all_specs.items():
            found = _debt(payload) if metric == "total_debt" else _latest_annual(payload, spec)
            if found:
                company_facts[metric] = _fact(company["company_id"], cik, metric, spec, found)
                company_coverage[metric] += 1
        equity = company_facts.get("stockholders_equity")
        shares = company_facts.get("shares_outstanding_instant")
        if equity and shares and Decimal(shares["value"]) > 0 and equity["period_end"] == shares["period_end"]:
            value = Decimal(equity["value"]) / Decimal(shares["value"])
            company_facts["book_value_per_share"] = {
                "financial_fact_id": f"financial_fact:{cik}:book_value_per_share:{equity['period_end']}:FY",
                "company_id": company["company_id"], "metric": "book_value_per_share", "value": str(value),
                "unit": "currency_per_share", "currency": "USD", "period_type": "instant",
                "period_end": equity["period_end"], "fiscal_year": equity["fiscal_year"], "fiscal_period": "FY",
                "statement": "derived", "form_type": equity["form_type"], "accession_number": equity["accession_number"],
                "source": {"provider": "sec_companyfacts", "formula_version": "book_value_per_share.v031v.3", "source_fact_ids": [equity["financial_fact_id"], shares["financial_fact_id"]]},
            }
            company_coverage["book_value_per_share"] += 1
        facts.extend(company_facts.values())
    if bulk_archive is not None:
        bulk_archive.close()
    companies_with_facts = len({row["company_id"] for row in facts})
    coverage_names = [*all_specs, "book_value_per_share"]
    return {
        "schema_version": "sec-financial-population.v031v.3", "version": "V031V.3", "generated_at": current.isoformat(),
        "summary": {"valuation_scope_company_count": 5876, "cik_scope_company_count": source_scope_count, "batch_offset": offset, "companies_requested": len(scope), "companies_with_companyfacts": sum(source_modes.values()), "companies_with_financial_facts": companies_with_facts, "financial_fact_count": len(facts), "quarterly_financial_fact_count": len(quarterly_facts), "quarterly_company_count": len({row["company_id"] for row in quarterly_facts}), "quarantined_company_count": len({row["company_id"] for row in diagnostics if row.get("reason_code") == "AMBIGUOUS_FISCAL_QUARTER_QUARANTINED"}), "metric_company_coverage": {name: company_coverage[name] for name in coverage_names}, "source_mode_counts": dict(sorted(source_modes.items())), "missing_companyfacts_count": len(diagnostics), "cache_ttl_days": cache_ttl_days},
        "financial_facts": facts, "quarterly_financial_facts": quarterly_facts, "diagnostics": diagnostics,
    }


def _quarter_latest_end(rows: list[Mapping[str, Any]]) -> str:
    """ISO date quarters only; reject malformed period ends before comparing."""
    ends = []
    for row in rows:
        end = str(row.get("period_end") or "")
        date.fromisoformat(end)
        ends.append(end)
    return max(ends, default="")


def write_sec_financial_population(report: Mapping[str, Any], output_dir: Path, *, merge_existing: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    quarterly_root = output_dir / "quarterly"
    quarterly_root.mkdir(parents=True, exist_ok=True)
    facts = list(report["financial_facts"])
    if merge_existing and (output_dir / "financial_facts.json").is_file():
        refreshed = {str(row["company_id"]) for row in facts}
        prior = _load(output_dir / "financial_facts.json")
        facts = [row for row in prior if str(row.get("company_id")) not in refreshed] + facts
        facts.sort(key=lambda row: (str(row.get("company_id")), str(row.get("metric"))))
    # This file is the current valuation snapshot, not an archive.  Do not keep
    # an isolated metric years after the same company has filed newer facts;
    # stale values (for example a 2021 debt value beside 2025 statements) are
    # unsafe inputs and only add dead weight.  Quarterly history remains in its
    # bounded per-company files below.
    newest_by_company: dict[str, date] = {}
    for row in facts:
        try:
            observed = date.fromisoformat(str(row.get("period_end"))[:10])
        except ValueError:
            continue
        company_id = str(row.get("company_id") or "")
        if company_id and observed > newest_by_company.get(company_id, date.min):
            newest_by_company[company_id] = observed
    facts = [
        row for row in facts
        if not (company_id := str(row.get("company_id") or ""))
        or company_id not in newest_by_company
        or not str(row.get("period_end") or "")
        or (newest_by_company[company_id] - date.fromisoformat(str(row["period_end"])[:10])).days <= 550
    ]
    facts = [_public_fact(row) for row in facts]
    quarterly_by_company: dict[str, list[Mapping[str, Any]]] = {}
    for row in report["quarterly_financial_facts"]:
        quarterly_by_company.setdefault(str(row["company_id"]), []).append(row)
    index_path = output_dir / "quarterly_index.json"
    quarterly_index: dict[str, str] = (
        dict((_load(index_path).get("company_id_to_file") or {}))
        if merge_existing and index_path.is_file()
        else {}
    )
    # Safe merge policy: do not replace newer canonical quarterly history with a
    # shorter/quarantined SEC reconstruction. Preserve the ENTIRE old company file,
    # not a mixture of incompatible fiscal identities. Track every hold for review.
    quarterly_holds: list[dict[str, Any]] = []
    updated_quarterly_companies = 0
    for company_id, rows in sorted(quarterly_by_company.items()):
        rows = [_public_fact(row) for row in rows]
        filename = quote(company_id, safe="._-") + ".json"
        previous_rel = quarterly_index.get(company_id) if merge_existing else None
        if previous_rel:
            previous_path = (output_dir / previous_rel).resolve()
            if not previous_path.is_relative_to(output_dir.resolve()) or not previous_path.is_file():
                raise ValueError(f"Missing/unsafe pre-existing quarterly index target for {company_id}: {previous_rel}")
            previous_rows = _load(previous_path)
            if not isinstance(previous_rows, list):
                raise ValueError(f"Malformed existing quarterly data for {company_id}")
            old_latest = _quarter_latest_end(previous_rows)
            new_latest = _quarter_latest_end(rows)
            if old_latest > new_latest:
                quarterly_holds.append({
                    "company_id": company_id,
                    "reason_code": "PUBLISH_QUARTERLY_LATEST_REGRESSION_HELD",
                    "old_latest": old_latest,
                    "candidate_latest": new_latest,
                })
                continue
            # Prevent partial reruns from deleting still-valid metrics for the
            # same fiscal quarter/date. A true older-history trim is permitted
            # only when the candidate advances the latest financial period.
            previous_keys = {(str(r.get("period_end")), str(r.get("metric"))) for r in previous_rows}
            candidate_keys = {(str(r.get("period_end")), str(r.get("metric"))) for r in rows}
            lost_same_or_newer = sorted(k for k in previous_keys - candidate_keys if k[0] >= new_latest)
            if lost_same_or_newer:
                quarterly_holds.append({
                    "company_id": company_id,
                    "reason_code": "PUBLISH_QUARTERLY_METRIC_COVERAGE_HELD",
                    "old_latest": old_latest,
                    "candidate_latest": new_latest,
                    "missing_latest_metrics": [list(x) for x in lost_same_or_newer[:20]],
                })
                continue
        quarterly_index[company_id] = f"quarterly/{filename}"
        temporary = (quarterly_root / filename).with_suffix(".json.tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(quarterly_root / filename)
        updated_quarterly_companies += 1
    manifest = {key: report[key] for key in ("schema_version", "version", "generated_at", "summary")}
    manifest["summary"] = dict(
        manifest["summary"],
        write_mode="merge_existing" if merge_existing else "replace",
        quarterly_safe_merge_held_company_count=len(quarterly_holds),
        quarterly_safe_merge_updated_company_count=updated_quarterly_companies,
    )
    for name, payload in {"manifest.json": manifest, "financial_facts.json": facts, "quarterly_index.json": {"schema_version": "quarterly-financial-index.v031v.4", "company_count": len(quarterly_index), "company_id_to_file": quarterly_index}, "diagnostics.json": list(report["diagnostics"]) + quarterly_holds}.items():
        temporary = output_dir / f"{name}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_dir / name)
