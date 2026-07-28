# V031C.2 — Rebuildable Company Signals

## Outcome

- Converts SEC annual-report Business sections into deterministic, evidence-linked company signals.
- Produces one record for every company in the 6,464-company Registry, including explicit unavailable and no-match states.
- Keeps raw concept detection separate from later Theme, Sector, and Cluster inference.
- Forbids ticker or company membership lists in signal rules.

## Evidence contract

Every detected signal includes its canonical signal ID, dimension, confidence, occurrence count, matched aliases, Business Evidence IDs, SEC accession numbers, character offsets, matched text, and bounded context. The snapshot can therefore be rebuilt from Canonical Business Evidence plus the versioned rule set.

## Current population

- Registry companies: 6,464
- Companies with Canonical Business Evidence: 280
- Companies with at least one signal: 214
- Evidence-bearing companies with no detected signal: 66
- Companies awaiting Business Evidence: 6,184

The coverage numbers describe the current filing population and are not a manually selected Research Universe.
