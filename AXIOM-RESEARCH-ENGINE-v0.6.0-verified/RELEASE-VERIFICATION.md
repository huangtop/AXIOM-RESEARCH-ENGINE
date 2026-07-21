# Release Verification

Artifact: `AXIOM-RESEARCH-ENGINE-v0.4.0-verified.zip`

The artifact was verified from a clean Python 3.13 virtual environment with:

```text
editable install                       PASS
import axiom_engine                    PASS (0.4.0)
import axiom_engine.io                 PASS
ruff check .                           PASS
pytest -q                              PASS (5 tests)
axiom validate                         PASS
axiom research --company-id ...        PASS
axiom value                            PASS
axiom build-public                     PASS
```

This verifies the included artifact in the build environment. A consumer machine can still differ because of local Python paths, shell configuration, permissions, or pre-existing global command shims. Prefer `python -m ...` inside a fresh virtual environment and confirm `which python`, `which pip`, and `which axiom` all point into `.venv`.
