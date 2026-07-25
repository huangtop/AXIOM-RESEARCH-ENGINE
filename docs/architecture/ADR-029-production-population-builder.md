# ADR-029 — Production Population Builder

V030.4 converts the V030.35 selected source manifest into three universe-aligned populations.

Every company receives exactly one financial, market, and estimate population record. Existing source rows are linked through company ID, security ID, ticker, or CIK. Missing source data is represented explicitly with `data_present: false`; the builder never fabricates financial values, prices, or analyst estimates.

Generated artifacts are build outputs and are not canonical source files.
