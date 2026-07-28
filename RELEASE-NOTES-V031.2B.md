# V031.2B — SEC Filing Business Evidence Extraction

V031.2B downloads annual filing primary documents incrementally and extracts evidence-bearing Business sections without summarization or theme classification.

- 10-K families use Item 1 Business bounded by Item 1A Risk Factors.
- 20-F and 40-F families use Item 4 Information on the Company bounded by Item 4A or Item 5.
- The longest valid span is selected to avoid table-of-contents matches.
- Documents and extracted text carry independent SHA-256 hashes, filing identity, URL, retrieval time, and extraction location.
- Missing cache, fetch failure, missing boundaries, short sections, and unsupported forms remain explicit diagnostics.

Raw filing HTML is a rebuildable provider cache and is excluded from Git. This stage does not generate summaries, signals, themes, sectors, clusters, or ticker membership.
