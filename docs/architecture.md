# v0.3.0 Architecture

## Core chain

```text
Company → CompanyValuationProfile → ValuationProfile → Models → ValuationBook
```

## Snapshot versus execution

- `ValuationExecution` records every command invocation.
- `ValuationSnapshot` represents one unique result for one unique set of inputs.
- Snapshot IDs are deterministic hashes; unchanged inputs do not create duplicates.
- `ValuationBook` groups the available models for one company/security/scenario.

## Current models

- Forward P/E: forward EPS × target P/E
- Forward P/B: book value per share × target P/B
- Forward P/S: forward revenue per share × target P/S
- EV/EBITDA: (EBITDA × target multiple − net debt) / shares outstanding

DCF remains an optional future adapter, not a required architectural dependency.
