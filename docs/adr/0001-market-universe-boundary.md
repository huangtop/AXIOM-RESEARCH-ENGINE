# ADR-0001: Market Universe as an extension of v0.7 Canonical and Valuation domains

## Status
Proposed for validation.

## Decision
Add a small Market Universe model layer without replacing the v0.7 Canonical, Valuation, Industry, ETF, or Impact domains.

Universe owns stable company coverage metadata: company/security masters, classifications, research level, and company-to-valuation-profile assignments.

Valuation continues to own profiles, assumptions, scenarios, executions, snapshots, and valuation books.

## Consequences
- Existing `company:*`, `security:*`, and `valuation_profile:*` IDs are reused.
- `ValuationBook.profile_ids` remains valid.
- Universe does not duplicate financial facts or valuation outputs.
- Future news and supply-chain records can resolve to the same company IDs.
