#!/usr/bin/env python3
from pathlib import Path

from axiom_engine.business_evidence_store import load_business_evidence, write_business_evidence_shards


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "data/generated/canonical_business_evidence"
    evidence = load_business_evidence(root)
    index = write_business_evidence_shards(evidence, root)
    print({"company_count": index["company_count"], "evidence_count": index["evidence_count"]})


if __name__ == "__main__":
    main()
