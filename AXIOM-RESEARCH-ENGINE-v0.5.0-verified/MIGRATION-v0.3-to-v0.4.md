# Migration from v0.3 to v0.4

This archive is a complete repository and is the recommended installation path. Do not copy its files over a live WordPress site.

## Safe migration

1. Commit and tag the current v0.3 repository.
2. Extract this archive into a new directory.
3. Copy only user-maintained canonical or valuation data after comparing schemas.
4. Create a new virtual environment.
5. Run `./scripts/verify_release.sh`.
6. Compare generated valuation books and public JSON before switching any downstream consumer.

## Clean installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
./scripts/verify_release.sh
```

## Website boundary

The website should consume only validated files under `data/public/`. Research code, raw ingestion files, credentials, AI prompts, and write access must remain outside WordPress.
