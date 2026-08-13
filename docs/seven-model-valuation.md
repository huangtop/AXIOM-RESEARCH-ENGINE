# Seven-model valuation contract

Every company valuation payload contains the same ordered seven-model universe. A model with
insufficient inputs remains present with `status=unavailable`; it is never silently removed.

| Model | Formula | Independent assumptions required |
|---|---|---|
| DCF | PV of forecast free cash flow + PV of terminal value + cash − debt, divided by diluted shares | forecast growth, discount rate, terminal growth |
| Forward P/E | forward EPS × target forward P/E | target forward P/E |
| PEG | forward EPS × long-term EPS growth percentage × target PEG | long-term growth and target PEG |
| Forward P/S | forward revenue ÷ diluted shares × target forward P/S | target forward P/S |
| EV/EBITDA | (EBITDA × target EV/EBITDA − debt + cash) ÷ diluted shares | target EV/EBITDA |
| Forward P/B | book value per share × target forward P/B | target forward P/B |
| Milestone | success probability × success value + (1 − probability) × failure value | verified probability and scenario values |

An analyst target price is an output opinion, not an independent multiple assumption. It must
not be reverse-engineered into multiple model assumptions: doing that forces every model back to
the same target price and creates false model agreement. PEG assumptions are company/profile
specific; NVIDIA's legacy base scenario has an explicit 0.90 target PEG, but that value is not a
market-wide default.

When an explicit base-scenario estimate exists, it takes precedence over a provider consensus
estimate for that company. This preserves NVIDIA's evidence-linked forward EPS and long-term
growth inputs instead of substituting Yahoo's near-term `earningsGrowth` field for long-term PEG
growth.

The current DCF policy uses common defaults where company-specific forecasts are absent. Such a
DCF remains diagnostic and is excluded from headline aggregation by product policy until its
assumptions are company-specific.
