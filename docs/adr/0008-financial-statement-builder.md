# ADR-0008: Canonical Financial Statement Builder

## Status

Accepted

## Decision

Introduce a read-only builder between SEC Company Facts and the future Financial Repository.
It resolves US-GAAP aliases through a registry, selects annual observations by fiscal year and
filing cutoff, preserves source provenance, returns canonical income/balance/cash-flow models,
and derives free cash flow as operating cash flow less absolute capital expenditure.

The builder does not persist data, derive quarters, construct TTM periods, convert currencies,
or reconcile restatements. Missing concepts remain `None`.
