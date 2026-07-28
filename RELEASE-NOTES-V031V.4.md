# V031V.4 — Full-Market Previous Close Population

V031V.4 begins resumable previous-close population for all 5,876 normalized valuation companies.

- Recent Canonical closes are skipped before any provider request.
- Successful rows are checkpointed every 25 companies, limiting interruption replay.
- CLI execution resolves imports from the active repository worktree rather than an unrelated editable installation.
- Transient Yahoo errors use bounded retry and US class-share symbols are mapped reversibly from canonical dot form to Yahoo hyphen form.

The first 1,000-company checkpoint is complete. The Canonical market snapshot now contains 1,003 symbols, of which 1,002 match valuation-scope companies. DCF eligibility reaches 332 and Forward P/B eligibility reaches 512; 219 companies are eligible for at least two models. The remaining population will continue from offset 1,000; raw daily archives remain excluded from new commits.
