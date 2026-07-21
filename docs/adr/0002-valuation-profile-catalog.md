# ADR-0002: Valuation Profile Catalog belongs to Market Universe

## Status
Proposed for Commit-002 validation.

## Decision
Create a Universe-owned valuation profile catalog that describes company applicability, lifecycle, profitability, model priority, legacy website mapping, warning policy, and confidence policy.

The existing `data/valuation/valuation_profiles.json` remains the runtime valuation configuration used by the valuation engine. This commit does not replace it and does not change valuation execution.

## Boundary
This commit adds classification metadata only. It does not add financial facts, news, industry-chain inference, knowledge-graph edges, scenarios, or reasoning.

## Compatibility
The legacy website mapping is explicit through `legacy_calc_type`. Existing valuation profile IDs remain unchanged.
