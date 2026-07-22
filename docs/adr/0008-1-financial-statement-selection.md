# ADR-0008.1: Financial Statement Selection Accuracy

## Status

Accepted

## Context

SEC Company Facts filings include comparative observations that share the same fiscal-year
and filing metadata. Selecting each concept independently can combine values from different
statement dates, such as current assets with equity from an older comparative balance sheet.
The same issue affects duration facts in income and cash-flow statements.

## Decision

The builder derives a statement context before resolving individual concepts:

- the balance-sheet date is the latest eligible end date from primary instant anchors;
- the duration end date is the latest eligible end date from revenue, net income, and
  operating-cash-flow anchors;
- exact statement-date matches outrank older comparative observations;
- alias and preferred-unit priorities remain deterministic fallback criteria;
- common equity and capital-expenditure aliases are expanded.

The public Financial Statements API remains unchanged.

## Consequences

Canonical statements are internally date-aligned and are less likely to mix comparative
periods from the same filing. Free cash flow is available for more issuers when a supported
CapEx fallback concept is present.
