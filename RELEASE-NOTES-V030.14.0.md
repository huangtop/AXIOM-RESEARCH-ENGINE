# V030.14.0 — Production Fair Value Beta

Single-pass production output for the valuation card.

- Historical Fair Value from ready V030.13.3 benchmarks.
- Peer Fair Value from cross-sectional production-universe medians.
- FCF DCF MVP with bounded growth and explicit discount/terminal policy.
- Composite Fair Value that excludes blocked models and renormalizes ready weights.
- Final rating, upside, confidence, range, diagnostics, and frontend-ready payload.
- Writes only `data/generated/fair_value/fair_value_snapshot.json` and `fair_value_diagnostic.json`.
- `--strict` requires both the configured company target and ready valuation cards for that target.

Run:

```bash
python scripts/build_fair_value_snapshot.py --write --strict
```
