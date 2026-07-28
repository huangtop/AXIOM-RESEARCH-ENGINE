# V031V.4 — Full-Market Previous Close Population

V031V.4 begins resumable previous-close population for all 5,876 normalized valuation companies.

- Recent Canonical closes are skipped before any provider request.
- Successful rows are checkpointed every 25 companies, limiting interruption replay.
- CLI execution resolves imports from the active repository worktree rather than an unrelated editable installation.
- Transient Yahoo errors use bounded retry and US class-share symbols are mapped reversibly from canonical dot form to Yahoo hyphen form.

The first 200-company checkpoint is complete with 110 new closes and 90 cache hits. The Canonical market snapshot now contains 203 symbols. DCF eligibility rises from 30 to 60 and Forward P/B eligibility rises from 56 to 106. The remaining population will continue through explicit offsets; raw daily archives remain excluded from Git.
