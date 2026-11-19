# Safe deployment boundary

AXIOM runs in GitHub Actions/CI or a controlled worker. WordPress must not execute the research engine.

1. CI validates inputs and runs automated tests.
2. Publication artifacts are generated through the current publication pipeline and its independent validation gates.
3. Only approved, read-only publication artifacts are exposed to frontend consumers.
4. Publication changes are activated only after validation, with rollback capability retained.
5. Secrets, write APIs, raw ingestion payloads, and internal evidence must not be exposed through public endpoints.

The legacy `axiom build-public` command and AXIOM `data/public` static JSON export pipeline have been retired.

The current `data/generated/publication_gate` artifacts remain independent of the retired legacy export pipeline.

The `ETF-ENGINE-V2` repository maintains its own `data/public` artifacts and is outside the scope of this retirement.