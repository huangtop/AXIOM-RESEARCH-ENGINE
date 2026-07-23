# ADR-005 — Canonical Valuation Engine

V019 valuation reads only V017 reported financial facts and V018 estimates or approved forward assumptions.

The engine must not import or read the legacy valuation service, legacy research reports, yfinance output, analyst targets, current market prices, classification, exposure, or frontend data.

Canonical valuation outputs are reproducible derived records. Initial supported models are a five-year discounted cash-flow model and a forward earnings multiple model. A model is unavailable when its required canonical inputs are absent or invalid; the engine must not silently invent inputs.

The 100-company acceptance gate means 100 distinct companies have all required inputs and complete both supported models. Synthetic fixtures may test engine capacity, but must never be represented as real-company valuation coverage.
