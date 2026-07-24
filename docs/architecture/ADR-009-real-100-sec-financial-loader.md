# ADR-009 — Real-100 SEC Financial Loader

V023 downloads SEC Companyfacts by canonical CIK, maps reported US-GAAP facts into the isolated V017 financial-data contract, and writes only historical reported facts. It excludes estimates, prices, valuation assumptions, and derived valuation outputs.

Production acceptance requires all 100 registry companies to have facts and minimum metric coverage thresholds. Raw SEC responses are cacheable for deterministic re-validation.

## V023 Hotfix 1

Production execution revealed one company with no selected facts, 78% capital-expenditure coverage, and 90% debt coverage. Hotfix 1 therefore:

- accepts annual Companyfacts rows that omit `fy` when their duration is annual;
- expands conservative SEC US-GAAP aliases for CapEx and debt;
- derives debt only from explicitly ordered, same-period components;
- records the selected XBRL tag and any derived components;
- writes `v023_financial_diagnostics.json` containing company-level missing metrics and tag usage;
- raises production acceptance thresholds for CapEx and debt to 95%.

## Hotfix 2

- Supports financial-facts CIK aliases when a listed issuer changes its SEC registrant identity while historical Companyfacts remain under a predecessor CIK.
- Adds adaptive current/non-current debt component pairing.
- Allows an explicitly marked `noncurrent_debt_only` proxy only as a final fallback; provenance retains the exact source concept and proxy status.


## V023 Hotfix 3 — Debt selection precedence

Current-only debt concepts are not consolidated total debt. They are excluded from the direct-total candidate list so exact or adaptive current + noncurrent combinations are evaluated first. A noncurrent-only value remains an explicitly marked coverage proxy only when no complete pair exists.
