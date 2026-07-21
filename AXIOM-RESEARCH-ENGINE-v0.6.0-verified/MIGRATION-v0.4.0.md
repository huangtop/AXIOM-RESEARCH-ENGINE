# Upgrade to v0.4.0

1. Commit your current repository.
2. Extract the update package outside the repository.
3. Run `./apply_patch.sh /path/to/AXIOM-RESEARCH-ENGINE`.
4. Reinstall editable package: `python -m pip install -e '.[dev]'`.
5. Run `axiom validate`, `pytest -q`, `ruff check .`, `axiom research`, `axiom value`, `axiom build-public`.

The update does not install or modify WordPress. Keep the website as a read-only consumer of generated public JSON. Deploy generated JSON atomically only after CI passes.
