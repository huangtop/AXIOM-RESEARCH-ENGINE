# ADR-012 Canonical Market Data Layer

V025.5 establishes an independent provider-adapter boundary between raw market snapshots and valuation. The canonical output filename is `data/market_data/observations.json`, matching V025's input contract. Market data contains point-in-time observations only; fair value, analyst targets, research classifications, and valuation outputs are rejected. Provider-specific payloads are normalized before persistence. Company and security references must resolve through Company Registry. Provenance, diagnostics, and manifest are written beside observations.
