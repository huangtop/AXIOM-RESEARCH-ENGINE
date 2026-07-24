# ADR-022: Production Estimate Import

## Status
Accepted for V028.3.

## Decision
Introduce an isolated canonical import boundary for point-in-time analyst consensus estimates. Records link to V028.0 company identifiers and optionally security identifiers, preserve provider/source metric and provenance, normalize decimal values and UTC timestamps, and reject invalid periods, links, ranges, duplicates, and unsupported metrics.

## Non-goals
V028.3 does not scrape providers, replace provider adapters, calculate valuation, or silently merge conflicting consensus snapshots.
