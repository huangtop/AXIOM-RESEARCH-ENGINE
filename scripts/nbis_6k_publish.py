from __future__ import annotations

import argparse
import json
import os
import shutil
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

CID = "company:US-CIK0001513845"
CIK = "0001513845"

ROOT = Path("data/generated/canonical_financial_population").resolve()
INPUT = Path("/tmp/axiom_nbis_6k_staging.json")
LINEAGE = Path("/tmp/axiom_nbis_6k_lineage.json")
INDEX = "quarterly_index.json"
REL = "quarterly/" + quote(CID, safe="") + ".json"

EXPECTED = {
    "revenue": 529800000,
    "net_income": 82500000,
    "operating_cash_flow": 384800000,
    "capital_expenditures": 4066000000,
}

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".writing")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)

def validate(rows, lineage):
    assert isinstance(rows, list) and len(rows) == 24
    assert isinstance(lineage, list) and len(lineage) == 24

    ids = set()
    pairs = set()
    counts = Counter()

    for r in rows:
        fid = r["financial_fact_id"]
        metric = r["metric"]
        end = r["period_end"]
        fy = r["fiscal_year"]
        fp = r["fiscal_period"]

        assert fid == (
            f"quarterly_financial_fact:{CIK}:{metric}:{end}:{fp}"
        )
        assert r["company_id"] == CID
        assert metric in EXPECTED
        assert r["unit"] == "currency"
        assert r["currency"] == "USD"
        assert r["period_type"] == "duration"
        assert r["statement"] == (
            "income_statement"
            if metric in ("revenue", "net_income")
            else "cash_flow"
        )
        assert r["form_type"] in ("6-K", "20-F")
        assert r.get("accession_number")
        assert r["source"]["provider"]
        assert r["period_start"] < end

        assert fid not in ids
        assert (metric, end) not in pairs
        ids.add(fid)
        pairs.add((metric, end))
        counts[metric] += 1

        assert (fy, fp, end) in {
            (2025, "Q1", "2025-03-31"),
            (2025, "Q2", "2025-06-30"),
            (2025, "Q3", "2025-09-30"),
            (2025, "Q4", "2025-12-31"),
            (2026, "Q1", "2026-03-31"),
            (2026, "Q2", "2026-06-30"),
        }

    assert all(counts[m] == 6 for m in EXPECTED)
    assert {x["financial_fact_id"] for x in lineage} == ids

    for metric, expected in EXPECTED.items():
        total = sum(
            int(r["value"])
            for r in rows
            if r["metric"] == metric
            and r["fiscal_year"] == 2025
        )
        assert total == expected, (metric, total, expected)

    h1 = {
        metric: sum(
            int(r["value"])
            for r in rows
            if r["metric"] == metric
            and r["fiscal_year"] == 2026
        )
        for metric in EXPECTED
    }

    assert h1 == {
        "revenue": 981300000,
        "net_income": 430800000,
        "operating_cash_flow": 4504100000,
        "capital_expenditures": 8130300000,
    }

    # Validate the lineage record for each fact.
    for item in lineage:
        assert item["sources"]
        for source in item["sources"]:
            assert source["accession"]
            assert source["url"].startswith(
                "https://www.sec.gov/Archives/"
            )

    # Do not publish synthetic IDs as real SEC fact IDs.
    clean = []
    for row in rows:
        r = dict(row)
        source = r["source"]
        r["source"] = {
            "provider": source["provider"],
            "formula_version": source["formula_version"],
        }
        clean.append(r)

    return sorted(
        clean, key=lambda x: (
            x["period_end"], x["metric"]
        )
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()

    if not ROOT.is_dir():
        raise SystemExit("STOP: canonical root missing")

    if not INPUT.is_file() or not LINEAGE.is_file():
        raise SystemExit("STOP: NBIS staging or lineage missing")

    rows = validate(read(INPUT), read(LINEAGE))
    lineage = read(LINEAGE)

    old_index = read(ROOT / INDEX)
    assert old_index["schema_version"] == (
        "quarterly-financial-index.v031v.4"
    )

    mapping = old_index["company_id_to_file"]
    if CID in mapping:
        raise SystemExit(
            "STOP: NBIS already indexed; refusing overwrite"
        )

    assert old_index["company_count"] == len(mapping)
    assert not (ROOT / REL).exists()

    annual = read(ROOT / "financial_facts.json")
    for metric, expected in EXPECTED.items():
        matching = [
            r for r in annual
            if r.get("company_id") == CID
            and r.get("metric") == metric
            and r.get("period_end") == "2025-12-31"
        ]
        assert len(matching) == 1
        assert int(matching[0]["value"]) == expected

    stamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    suffix = stamp + "-" + uuid.uuid4().hex[:8]
    stage = ROOT.with_name(ROOT.name + ".nbis-stage-" + suffix)
    backup = ROOT.with_name(ROOT.name + ".nbis-backup-" + suffix)

    print("Copying canonical into NBIS staging...")
    shutil.copytree(ROOT, stage)

    swapped = False
    try:
        write(stage / REL, rows)
        write(stage / "nbis_6k_lineage.json", {
            "company_id": CID,
            "schema_version": "nbis_6k_lineage.v1",
            "facts": lineage,
        })

        index = read(stage / INDEX)
        index["company_id_to_file"][CID] = REL
        index["company_count"] = len(
            index["company_id_to_file"]
        )
        write(stage / INDEX, index)

        reread = read(stage / REL)
        check = read(stage / INDEX)

        assert reread == rows
        assert check["company_id_to_file"][CID] == REL
        assert check["company_count"] == (
            old_index["company_count"] + 1
        )

        assert read(stage / "financial_facts.json") == annual
        assert len(read(stage / "nbis_6k_lineage.json")["facts"]) == 24

        print("NBIS FACTS:", len(reread))
        print("INDEX BEFORE:", old_index["company_count"])
        print("INDEX AFTER:", check["company_count"])
        print("ANNUAL DATA: UNCHANGED")
        print("NBIS STAGED VALIDATION: PASS")

        if not args.publish:
            print("DRY RUN PASS — canonical unchanged")
            return

        print("Publishing NBIS; stop concurrent readers first.")

        ROOT.rename(backup)
        try:
            stage.rename(ROOT)
            swapped = True
        except BaseException:
            if not ROOT.exists() and backup.exists():
                backup.rename(ROOT)
            raise

        print("NBIS PUBLISHED:", ROOT)
        print("ROLLBACK BACKUP:", backup)
        print(
            "NBIS FILE:",
            ROOT / REL,
        )

    finally:
        if not swapped and stage.exists():
            shutil.rmtree(stage)

if __name__ == "__main__":
    main()
