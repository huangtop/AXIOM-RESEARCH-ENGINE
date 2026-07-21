# Safe deployment boundary

AXIOM runs in GitHub/CI or a controlled worker. WordPress should not execute the research engine.

1. CI validates and tests.
2. CI builds `data/public` into a temporary release directory.
3. Publish only immutable JSON/static files.
4. Switch the website pointer atomically after validation.
5. Keep the previous release for rollback.

Security hardening of the public ETF/news endpoints is intentionally deferred, but secrets, write APIs, raw ingestion payloads, and internal evidence must never be placed in `data/public`.
