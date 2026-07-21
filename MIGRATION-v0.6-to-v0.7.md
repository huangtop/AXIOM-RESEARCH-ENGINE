# Migration: v0.6 to v0.7

1. Copy the v0.7 repository over the tracked project while preserving `.git`.
2. Recreate or reactivate the virtual environment.
3. Run `python -m pip install -e '.[dev]'`.
4. Run `./scripts/verify_release.sh`.

New data directory: `data/impact/`.

New models: `Shock`, `PropagationRule`, `ImpactScenario`, `ImpactNode`, `CompanyImpactSnapshot`, and `ETFImpactSnapshot`.

New CLI: `axiom impact --shock-id <shock-id>`.
