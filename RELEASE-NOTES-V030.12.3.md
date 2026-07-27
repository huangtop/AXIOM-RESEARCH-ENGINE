# V030.12.3 — Valuation QA

Adds formal QA gates across Valuation Method Eligibility and Valuation Method Inputs.

## Gates

- eligibility consistency
- formula integrity
- derived calculation reproducibility
- provider provenance
- confidence propagation
- blocked-method safety

## Commands

```bash
python -m pytest tests/test_valuation_qa.py -q
python scripts/run_valuation_qa.py --write --strict
```

## Output

`data/generated/valuation_qa/valuation_qa_report.json`
