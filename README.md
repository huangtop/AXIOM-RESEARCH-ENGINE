# AXIOM Research Engine v0.7.0

AXIOM is an evidence-based investment knowledge graph with valuation, Industry Graph, ETF exposure mapping, and deterministic causal impact propagation.

## Verify

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
./scripts/verify_release.sh
```

## Impact examples

```bash
axiom impact --shock-id shock:CLOUD-AI-CAPEX-DOWN-15
axiom impact --shock-id shock:HBM4-SUPPLY-DOWN-20
```

The graph convention is always **cause → effect**. v0.7 maps entity shocks through Industry Graph paths to company revenue, EPS, fair-value impact, and ETF holding-weighted impact.

See `docs/impact-engine.md` for formulas and limitations.
