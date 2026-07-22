# ADR-0007.1: SEC Company Facts Parser Robustness

## Status

Accepted

## Context

A live SEC Company Facts response for NVIDIA contained descriptive fact metadata that
did not satisfy the parser's original assumption that every `label` and `description`
value is a non-null string. The HTTP connector succeeded, but parsing rejected the
otherwise usable response.

External regulatory payloads can contain nullable, omitted, historical, custom-taxonomy,
or scalar metadata. Rejecting an entire issuer response because non-essential metadata
is absent prevents downstream normalization.

## Decision

The SEC Company Facts parser remains strict about the structural fields required to
interpret the payload:

- `cik` must be valid;
- `facts` and taxonomy/concept containers must be objects;
- unit observation collections must be arrays;
- each observation must be an object and contain a supported `val`.

The parser becomes tolerant for descriptive and optional metadata:

- missing or null `entityName` becomes an empty string;
- missing or null `label` falls back to the concept name;
- missing or null `description` becomes an empty string;
- other scalar metadata is converted to text;
- missing or null `units` becomes an empty unit collection;
- unknown and empty taxonomies are accepted;
- numeric-string fiscal years are converted to integers.

The unmodified source payload remains available through `raw_payload`.

## Consequences

Live SEC responses are less likely to fail because of non-essential metadata variation.
Canonical validation remains the responsibility of the Financial Statement Builder and
future Financial Repository.
