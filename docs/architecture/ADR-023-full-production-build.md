# ADR-023: Full Production Build

V028.4 orchestrates the four canonical production imports in dependency order: Registry, Financial, Market, Estimate. It does not fetch external data. Source acquisition remains the responsibility of provider/SEC/market adapters. The build fails fast, validates cross-layer identifiers through each layer, and writes one production build manifest.
