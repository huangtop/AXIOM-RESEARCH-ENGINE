# AXIOM v0.4.0 update-only

Do not copy files directly into WordPress. Apply this patch to the Git repository, run all checks, build public JSON, and let the website consume only the generated static JSON.

```bash
cd /path/to/AXIOM-v0.4.0-update-only
./apply_patch.sh /path/to/AXIOM-RESEARCH-ENGINE
cd /path/to/AXIOM-RESEARCH-ENGINE
python -m pip install -e '.[dev]'
axiom validate
pytest -q
ruff check .
axiom research --company-id company:US-NVDA
axiom value
axiom build-public
```
