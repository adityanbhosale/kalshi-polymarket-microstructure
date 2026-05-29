# EXP-12a Regime-Sliced Markout

Tests whether the pervasive negative 5min net markout from EXP-12a is *conditional* — whether any of the 8 LP-edge markets has a regime where net markout turns non-negative with enough fills to trust (≥20 genuine fills per leg).

Fill definition, markout horizon (5min), and buy/sell leg assignment are identical to EXP-12a; this is a conditional overlay, not a re-verdict. `net markout = mean(buy-leg markout) + mean(sell-leg markout)`, legs sliced independently.

## Headline

**No market has a tradeable regime.** Across all tested regime bins (24 hour-of-day bins + low/high volatility) with ≥20 genuine fills on each leg, **zero** show non-negative net 5min markout. Adverse selection on the cross-venue LP is **unconditional** within this daemon window — it is not concentrated in specific hours or volatility states that an LP could avoid.

*Noise watch:* 4 regime bin(s) show non-negative net markout but FAIL the ≥20-fills-per-leg floor — treated as noise, not candidates:
  - `arod` [hour = 00Z]: net +0.088c but n_buy=0, n_sell=4.
  - `arod` [hour = 17Z]: net +0.150c but n_buy=0, n_sell=1.
  - `co_aesp` [hour = 18Z]: net +0.000c but n_buy=1, n_sell=0.
  - `co_pval` [hour = 19Z]: net +0.250c but n_buy=0, n_sell=1.

## Slice 1 — UTC hour-of-day

For each market, the hour bins (with ≥20 fills on BOTH legs) having the least-negative net markout. A market is a conditional-LP candidate only if some qualifying bin is ≥ 0.

| market | best qualifying hour | net markout | n_buy | n_sell | any non-neg bin (≥20/leg)? |
|---|---|---:|---:|---:|---|
| `arod` | — (no bin ≥20/leg) | — | — | — | no |
| `kelce` | — (no bin ≥20/leg) | — | — | — | no |
| `co_aesp` | — (no bin ≥20/leg) | — | — | — | no |
| `co_pval` | — (no bin ≥20/leg) | — | — | — | no |
| `pe_rpal` | — (no bin ≥20/leg) | — | — | — | no |
| `kr_oseh` | — (no bin ≥20/leg) | — | — | — | no |
| `la_kbas` | — (no bin ≥20/leg) | — | — | — | no |
| `nyk` | — (no bin ≥20/leg) | — | — | — | no |

*No market has any single hour bin with ≥20 genuine fills on **both** legs — total fills (≤112 on the best-filled leg) spread across 24 hourly bins are too sparse to clear a per-leg floor. The hour-of-day slice is therefore underpowered for this single-day window; nothing here can be trusted as a structural hour effect (see also caveat 3).*

## Slice 2 — catalyst proximity

Nearest known catalysts (F.1 event dates): Colombia 1st round 2026-05-31, Seoul mayor 2026-06-03; sports/other markets use their (year-offset-corrected) resolution dates, all 2026-09 or later. The E.1 daemon window analyzed here is 2026-05-28.

**Fills within 2h of any catalyst: 0.** Every catalyst is ≥2.5 days after the daemon window, so the near-catalyst bucket is **empty** — this slice is degenerate for the current data. The EXP-12a markouts are therefore all "far-from-catalyst" measurements; near-catalyst LP behavior remains uncharacterized (consistent with EXP-12a caveat 4, pending the F.1 dense captures of May 31 / June 3).

## Slice 3 — volatility regime (trailing-15min mid stddev)

Fills split by whether the trailing-15min mid stddev at fill time is below (low-vol) or above (high-vol) the market's median. Adverse selection should be WORSE in high-vol (more informed flow); a non-negative low-vol regime would be a conditional-LP candidate.

| market | low-vol net | n_buy/n_sell | high-vol net | n_buy/n_sell | low-vol non-neg (≥20/leg)? |
|---|---:|---|---:|---|---|
| `arod` | -3.350c | 0/1 | -0.556c | 0/36 | no |
| `kelce` | -0.400c | 2/0 | -0.034c | 16/0 | no |
| `co_aesp` | -1.667c | 3/1 | -1.000c | 1/0 | no |
| `co_pval` | -0.503c | 16/8 | -0.627c | 97/25 | no |
| `pe_rpal` | -0.760c | 5/1 | -1.587c | 27/1 | no |
| `kr_oseh` | -2.375c | 2/12 | -0.785c | 79/25 | no |
| `la_kbas` | -2.286c | 7/2 | -1.873c | 17/6 | no |
| `nyk` | -0.600c | 1/3 | -0.644c | 18/11 | no |

*For 6 of 8 markets the median trailing-15min mid stddev is ~0.00c (books are flat at 30s cadence on these thin markets), so the "low-vol" bin is effectively the perfectly-flat-trailing-window subset and "high-vol" is any-movement. The only bins that clear the ≥20-fills-per-leg floor are the **high-vol** bins for `co_pval` (96/25) and `kr_oseh` (79/25) — both firmly negative (−0.633c, −0.785c). Every other bin is under-powered. Consistent with the adverse-selection story, where high-vol net markout is evaluable it is negative, not positive.*

## Caveats

1. **Same 30s / queue-proxy limits as EXP-12a.** Slicing does not add resolution; it only conditions the same proxy fills.
2. **Catalyst slice is degenerate for this window** (no fills within 2h of any catalyst). It becomes informative only once the F.1 May 31 / June 3 dense captures are folded in.
3. **Hour bins are single-day.** The daemon window is one UTC date, so each hour bin is one observation of that hour, not a day-of-week-robust average. A non-negative hour here could be a one-off, not a structural window.
4. **Per-leg independence.** Net combines two independently sliced legs; it does not require the two fills to be contemporaneous.
