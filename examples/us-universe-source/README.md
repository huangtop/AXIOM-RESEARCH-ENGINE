# US Universe source snapshot

Run from the repository root:

```bash
python scripts/build_us_universe_source.py \
  --user-agent "AXIOM your-email@example.com" \
  --output data/sources/us_universe/listings.json
```

This produces an intermediate source snapshot only. Do not copy it directly into `data/universe/companies.json` or `securities.json`.
