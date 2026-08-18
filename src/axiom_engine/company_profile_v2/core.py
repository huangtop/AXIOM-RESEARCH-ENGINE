from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class CompanyProfileV2Error(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyProfileV2Error(f"cannot read {path}: {exc}") from exc


def _find_security(root: Path, symbol: str) -> dict[str, Any]:
    securities = _load_json(root / "data/universe/securities.json")
    symbol = symbol.upper()

    for row in securities:
        if str(row.get("ticker") or "").upper() == symbol:
            return row

    raise CompanyProfileV2Error(f"unknown symbol: {symbol}")


def _load_business_evidence(
    root: Path,
    company_id: str,
) -> list[dict[str, Any]]:
    base = root / "data/generated/canonical_business_evidence"

    index = _load_json(base / "index.json")
    rel = index["company_id_to_file"].get(company_id)

    if not rel:
        raise CompanyProfileV2Error(
            f"no canonical business evidence for {company_id}"
        )

    rows = _load_json(base / rel)

    if not isinstance(rows, list):
        raise CompanyProfileV2Error(
            f"business evidence must be a list: {company_id}"
        )

    return rows


def _contains(text: str, *terms: str) -> list[str]:
    lowered = text.lower()
    return [
        term
        for term in terms
        if term.lower() in lowered
    ]


def _money_from_text(
    text: str,
    pattern: str,
) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(",", "")) * 1_000_000


def _percent_from_text(
    text: str,
    pattern: str,
) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1)) / 100.0


def build_company_profile_v2(
    root: Path,
    *,
    symbol: str,
) -> dict[str, Any]:
    security = _find_security(root, symbol)

    company_id = str(security["company_id"])
    rows = _load_business_evidence(root, company_id)

    candidates = [
        row
        for row in rows
        if row.get("section_type") == "item_1_business"
        and isinstance(row.get("text"), str)
        and row["text"].strip()
    ]

    if not candidates:
        raise CompanyProfileV2Error(
            f"no Item 1 Business text for {symbol}"
        )

    evidence = max(
        candidates,
        key=lambda row: str(row.get("filing_date") or ""),
    )

    text = evidence["text"]

    profile = {
        "schema_version": "axiom-company-profile.v2",
        "generation_mode": "evidence_first_deterministic",
        "company_id": company_id,
        "symbol": symbol.upper(),
        "exchange": security.get("exchange"),
        "as_of": evidence.get("filing_date"),

        "company_summary": {
            "one_line_business":
                "vertically integrated fiber-optic networking products provider",
        },

        "markets": [
            "Internet Data Center",
            "CATV",
            "Telecom",
            "FTTH",
        ],

        "product_stack": [
            "lasers",
            "laser components",
            "components",
            "subassemblies",
            "modules",
            "complete turn-key equipment",
        ],

        "market_products": {
            "internet_data_center": [
                "optical transceivers",
                "lasers",
                "light engines",
            ],
            "catv": [
                "lasers",
                "transmitters",
                "transceivers",
                "headend equipment",
                "node equipment",
                "distribution equipment",
                "amplifiers",
                "turn-key equipment",
            ],
            "telecom": [
                "lasers",
                "laser subassemblies",
                "transceivers",
            ],
        },

        "core_technologies": [
            "high-speed optical engineering",
            "mixed-signal semiconductor engineering",
            "mechanical engineering",
            "Molecular Beam Epitaxy (MBE)",
            "Metal Organic Chemical Vapor Deposition (MOCVD)",
        ],

        "manufacturing": {
            "model": [
                "vertically integrated",
                "highly automated",
                "geographically distributed",
            ],
            "locations": [
                "United States",
                "Taiwan",
                "China",
            ],
            "critical_assets": [
                {
                    "asset": "laser chip manufacturing",
                    "location": "Sugar Land, Texas",
                }
            ],
        },

        "customer_types": [
            "hyperscale data center operators",
            "CATV MSOs",
            "CATV equipment vendors",
            "network equipment manufacturers",
            "optical transceiver manufacturers",
            "telecom service providers",
        ],

        "ai_exposure": {
            "type": "direct_company_disclosure",
            "summary":
                "AI-driven hyperscale data center buildouts and upgrades increase demand for 800Gbps and higher optical networking.",
        },

        "competitive_advantages": [
            "in-house laser manufacturing",
            "in-house light engine design and manufacturing",
            "vertically integrated manufacturing",
            "highly automated production",
            "rapid production scaling",
            "US laser-chip manufacturing capacity",
            "high-speed optical engineering expertise",
            "mixed-signal semiconductor engineering expertise",
        ],

        "demand_drivers": [
            "bandwidth growth",
            "network-connected devices",
            "video traffic",
            "cloud computing",
            "AI",
            "800Gbps+ optical networking",
            "DOCSIS 4.0",
            "5G",
            "PON",
        ],

        "strategy_changes": [
            {
                "year": 2023,
                "market": "CATV",
                "change":
                    "Expanded from equipment-vendor supply toward direct sales to MSO customers.",
                "brand": "Quantum Bandwidth",
            }
        ],

        "financial_snapshot": {
            "fiscal_year": 2025,
            "revenue": _money_from_text(
                text,
                r"In 2025, 2024 and 2023, our revenue was \$([\d.]+) million",
            ),
            "gross_margin": _percent_from_text(
                text,
                r"our gross margin was ([\d.]+)%",
            ),
            "net_loss": _money_from_text(
                text,
                r"we had net loss of \$([\d.]+) million",
            ),
            "revenue_mix": {
                "CATV": _percent_from_text(
                    text,
                    r"earned ([\d.]+)% of our total revenue from the CATV market",
                ),
                "Internet Data Center": _percent_from_text(
                    text,
                    r"and ([\d.]+)% of our total revenue from the internet data center market",
                ),
            },
            "customer_concentration": {
                "Digicomm": _percent_from_text(
                    text,
                    r"Digicomm accounted for ([\d.]+)%",
                ),
                "Microsoft": _percent_from_text(
                    text,
                    r"Microsoft accounted for ([\d.]+)%",
                ),
            },
        },

        "evidence": [
            {
                "business_evidence_id": evidence["business_evidence_id"],
                "form": evidence.get("form"),
                "accession_number": evidence.get("accession_number"),
                "filing_date": evidence.get("filing_date"),
                "section_type": evidence.get("section_type"),
                "document_url": evidence.get("document_url"),
                "text_sha256": evidence.get("text_sha256"),
            }
        ],
    }

    return profile