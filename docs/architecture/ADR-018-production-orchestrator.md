# ADR-018: Production Orchestrator

## Decision

Introduce a V027.3 orchestration layer that coordinates valuation strategy selection, the canonical batch research/card pipeline, strategy enrichment, and final company coverage audit.

## Boundaries

The orchestrator owns sequencing, state, validation, resumability, and output assembly. It does not replace V025 valuation logic, mutate canonical source layers, or duplicate research/card engines.

## Stage order

1. Build V027.2 valuation strategy results.
2. Run V027.1 canonical batch pipeline.
3. Add strategy metadata to merged research bundles and valuation cards.
4. Run V027.0 coverage audit against final production outputs.

## Operational outputs

The orchestrator writes a versioned state file, diagnostics, manifest, and isolated stage directories. This allows a 6000-company run to be resumed and validated without coupling the underlying engines.
