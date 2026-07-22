# ADR 0010D: Efficiency and Capital Structure Metrics

## Status

Accepted.

## Context

The normalization layer already maps canonical annual statements and computes
profitability margins. The next analytical step is to expose capital efficiency,
liquidity, and leverage metrics without moving calculation logic into the SEC
parser, statement builder, or repository query layer.

## Decision

`FinancialNormalizer` computes the following decimal-fraction metrics:

- Return on equity = net income / average shareholders' equity.
- Return on assets = net income / average total assets.
- Asset turnover = revenue / average total assets.
- Current ratio = current assets / current liabilities.
- Debt ratio = total liabilities / total assets.
- Debt to equity = total liabilities / shareholders' equity.

Average balance-sheet denominators use the nearest older fiscal year available.
When no older year exists, the current-year balance is used. A prior value with a
different unit is not averaged with the current value.

Current assets and current liabilities are added to the canonical balance-sheet
and normalized balance models. They are sourced only from reported SEC concepts
(`AssetsCurrent` and `LiabilitiesCurrent`); no synthetic estimate is produced.

Missing inputs and zero denominators return `None`. Calculations retain full
`Decimal` precision and do not apply display rounding.

## Consequences

The normalized snapshot now supports business-quality and capital-structure
analysis while remaining deterministic and auditable. Consumers can distinguish
reported values from unavailable metrics because the layer does not estimate
missing current balances. Adding canonical current-balance fields is backward
compatible because both fields default to `None`.
