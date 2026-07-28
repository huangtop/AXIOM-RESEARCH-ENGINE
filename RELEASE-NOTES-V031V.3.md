# V031V.3 — SEC Companyfacts Full-Population

V031V.3 projects the official SEC nightly Companyfacts archive into Canonical financial facts for the normalized valuation scope. The ZIP adapter reads one requested CIK at a time and does not retain the expanded bulk archive in memory.

Production coverage includes 5,659 Companyfacts payloads, 4,774 companies with usable financial facts, and 42,588 facts. Book value per share is derived only when stockholders' equity and instant shares are present for the same period. EBITDA remains unavailable because the current SEC standard concept coverage is zero; EBIT is never relabeled as EBITDA.

After cutover, financial coverage rises from 99 to 4,774 companies. With the current 92-company market snapshot, DCF eligibility rises from 6 to 30 and Forward P/B eligibility reaches 56. Forward P/E, PEG, Forward P/S, and Milestone remain blocked by the absent production estimate population; EV/EBITDA remains blocked by EBITDA coverage.

The 1.3 GB raw Companyfacts ZIP is ignored. The 27 MB Canonical output is committed with explicit missing-company diagnostics.
