# ADR-003: Independent Financial Data Pipeline

Canonical financial truth consists of reported facts plus provenance. Providers adapt their data into one schema. Estimates, prices, derived ratios, valuation outputs, classifications, exposures, and legacy research data are not financial facts and must not enter this layer. The valuation engine consumes this layer but does not own or mutate it.
