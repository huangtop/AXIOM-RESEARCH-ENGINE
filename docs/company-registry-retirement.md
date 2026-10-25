# Company registry retirement

Company and security readers now default to `data/universe/companies.json` and
`data/universe/securities.json`. The duplicate 100-company file at
`data/company_registry/companies.json` is removed. Existing explicit registry
arguments remain available for fixtures and isolated imports.

Financial, estimate and market import validation, research, batch processing,
production imports, valuation strategy and their CLI entry points use Universe.
Identity mapping no longer consults the retired registry for CIK fallbacks. A
missing Universe CIK remains an explicit unresolved diagnostic; this change does
not rewrite company IDs, merge share classes or regenerate published data.

The independent company importer and production registry builder now default to
`data/onboarding/generated/company_registry`, which is ignored staging storage.
Their companion validator uses the same staging path. These writers do not
overwrite Universe or recreate the retired file by default. Universe publication
continues through its own importer and reconciliation workflow.

The legacy `build_real_100_financials` and `validate_real_100_financials` helpers
have cohort-specific acceptance rules. They now require an explicit `registry_dir`
instead of silently expanding a 100-company SEC job to the whole market.

Remaining historical securities, provenance, business descriptions and official
classifications in `data/company_registry` are retained. The latter metadata is
still consumed by the theme/sector pipeline; it is not a company identity source.
The manifest marks the identity snapshot retired and its counts historical.
