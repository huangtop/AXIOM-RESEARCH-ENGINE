# V030.11.3 — Bridge QA

Adds production quality gates across Canonical Identity, Financial Bridge, Financial Timeline, and Source Router.

## Gates

- Identity linkage: company_id, CIK, primary symbol consistency.
- Bridge integrity: unique fact IDs, finite values, SEC provenance, period presence, summary reconciliation.
- Timeline integrity: bridge/timeline population parity, period ordering, TTM and freshness state validity.
- Router attribution: SEC precedence, Yahoo fallback attribution, provider/confidence completeness, missing-reason completeness.

Warnings do not fail strict mode. Critical issues do.
