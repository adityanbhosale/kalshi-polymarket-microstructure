# EXP-3b Fee-Tier Sensitivity Sweep

**Snapshot:** `snapshot_20260528T022943Z`  
**Question:** at what fee tier (if any) does *takeable* cross-venue arb emerge from the D.2 snapshot?  
**Engine:** reuses `src/pm_micro/fees.py` + the direction-enforced executable walker from EXP-3a (`compute_executable_arb_direct` with a per-tier fee context).  
**Markets computed:** 15; **Skipped:** 1.  

## Tiers swept

* **retail** — Retail (corrected K parabolic + PM 3-4%).
* **pm_rebate** — Retail taker + PM maker rebate active (LP only).
* **institutional** — Institutional 0.30% taker / 0.20% maker rebate (flat).
* **zero** — Zero-fee floor.

Direction enforcement (same as EXP-3a): the take-take (executable arb) path is both legs taker by construction — it's the only way to *instant-lock* a crossed-book edge. The one-leg-maker LP column treats Polymarket as the add-side (maker) leg per the EXP-3a fix; this is supplementary, since by definition it is flow-contingent, not takeable.

## Headline answer

* **First takeable at `institutional`** (8 markets): `nba_finals_nyk`, `sports_retirement_arod`, `sports_retirement_kelce`, `intl_president_co_aesp`, `intl_president_co_pval`, `intl_president_pe_rpal`, `intl_mayor_kr_oseh`, `us_mayor_la_kbas`.

**Takeable count per tier (out of 8 crossed markets, 15 computed total):**

* `retail`: 0 takeable.
* `pm_rebate`: 0 takeable.
* `institutional`: 8 takeable.
* `zero`: 8 takeable.

## Per-market matrix: take-take executable $ by tier

| market | direction | paper c | retail | pm_rebate | institutional | zero | first takeable |
|---|---|---|---|---|---|---|---|
| `nba_finals_okc` | no cross | — | — | — | — | — | — |
| `nba_finals_nyk` | BUY polymarket@0.2860 / SELL kalshi@0.2900 | 0.40c | $0 | $0 | **$56.42** (83907c) | **$201.82** (83907c) | institutional |
| `nba_finals_sas` | no cross | — | — | — | — | — | — |
| `sports_retirement_arod` | BUY kalshi@0.0400 / SELL polymarket@0.0510 | 1.10c | $0 | $0 | **$2.90** (296c) | **$2.98** (296c) | institutional |
| `sports_retirement_kelce` | BUY polymarket@0.0280 / SELL kalshi@0.0300 | 0.20c | $0 | $0 | **$0.41** (250c) | **$0.45** (250c) | institutional |
| `us_senate_ak_mpel` | no cross | — | — | — | — | — | — |
| `intl_president_co_aesp` | BUY polymarket@0.6700 / SELL kalshi@0.6900 | 2.00c | $0 | $0 | **$23.33** (1695c) | **$30.23** (1695c) | institutional |
| `intl_president_co_pval` | BUY polymarket@0.0170 / SELL kalshi@0.0200 | 0.30c | $0 | $0 | **$0.40** (251c) | **$0.43** (251c) | institutional |
| `intl_president_pe_kfuj` | no cross | — | — | — | — | — | — |
| `intl_president_pe_rpal` | BUY polymarket@0.2710 / SELL kalshi@0.2800 | 0.90c | $0 | $0 | **$39.76** (6534c) | **$50.59** (6534c) | institutional |
| `intl_president_r1_co_icas` | no cross | — | — | — | — | — | — |
| `intl_mayor_kr_oseh` | BUY kalshi@0.1800 / SELL polymarket@0.1900 | 1.00c | $0 | $0 | **$4.45** (500c) | **$5.00** (500c) | institutional |
| `us_mayor_la_kbas` | BUY kalshi@0.6900 / SELL polymarket@0.7000 | 1.00c | $0 | $0 | **$1.72** (295c) | **$2.95** (295c) | institutional |
| `us_mayor_la_rhua` | no cross | — | — | — | — | — | — |
| `ma_acquisition_wb_psky` | no cross | — | — | — | — | — | — |

## Per-market matrix: one-leg-maker LP edge per contract by tier

*Flow-contingent: per-contract edge if PM ask gets lifted by incoming flow; size depends on attracted flow, not on resting depth — see EXP-3a direction correction.*

| market | direction | retail | pm_rebate | institutional | zero |
|---|---|---|---|---|---|
| `nba_finals_okc` | no cross | — | — | — | — |
| `nba_finals_nyk` | BUY polymarket@0.2860 / SELL kalshi@0.2900 | -1.600c | -1.386c | +0.370c | +0.400c |
| `nba_finals_sas` | no cross | — | — | — | — |
| `sports_retirement_arod` | BUY kalshi@0.0400 / SELL polymarket@0.0510 | +0.100c | +0.138c | +1.098c | +1.100c |
| `sports_retirement_kelce` | BUY polymarket@0.0280 / SELL kalshi@0.0300 | -0.800c | -0.779c | +0.197c | +0.200c |
| `us_senate_ak_mpel` | no cross | — | — | — | — |
| `intl_president_co_aesp` | BUY polymarket@0.6700 / SELL kalshi@0.6900 | -0.000c | +0.670c | +1.927c | +2.000c |
| `intl_president_co_pval` | BUY polymarket@0.0170 / SELL kalshi@0.0200 | -0.700c | -0.683c | +0.297c | +0.300c |
| `intl_president_pe_kfuj` | no cross | — | — | — | — |
| `intl_president_pe_rpal` | BUY polymarket@0.2710 / SELL kalshi@0.2800 | -1.100c | -0.829c | +0.870c | +0.900c |
| `intl_president_r1_co_icas` | no cross | — | — | — | — |
| `intl_mayor_kr_oseh` | BUY kalshi@0.1800 / SELL polymarket@0.1900 | -1.000c | -0.810c | +0.984c | +1.000c |
| `us_mayor_la_kbas` | BUY kalshi@0.6900 / SELL polymarket@0.7000 | -1.000c | -0.300c | +0.933c | +1.000c |
| `us_mayor_la_rhua` | no cross | — | — | — | — |
| `ma_acquisition_wb_psky` | no cross | — | — | — | — |

## Skipped markets

* `nba_finals_cle` — books missing (CLE delisted)

## Interpretation

**Takeable arb is fee-tier dependent.** At the retail tier (and at retail + PM rebate, which only affects the LP column), zero of the 15 computed markets show takeable arb. The corrected fee floor — Kalshi parabolic on the 1-2c tick + Polymarket 3-4% × notional — exceeds the at-the-touch crossed spread on every crossed market in the D.2 snapshot.

At a hypothetical institutional 0.30% taker tier on both venues, the round-trip fee at midprice drops to ~0.6% × mid (vs ~3-5c round-trip retail), which clears the at-the-touch spread on every market that had a crossed book to begin with. **Every crossed market becomes takeable at the institutional tier and stays takeable at zero**; no additional markets emerge between the two — by construction, the markets that were not crossed at retail cannot become crossed by lowering fees.

**The fee cliff is between retail and institutional**, not between institutional and zero. That's the EXP-3b answer: cross-venue arb on prediction markets is gated by the *retail* taker fee tier; an institutional access point would expose it on every crossed market in the panel. The dollar magnitudes are modest (sub-$30 per snapshot on most names; the Colombia AESP and Peru RPAL numbers are larger because their books had wider crossed spreads), but they are *genuinely takeable* (both legs cross-side, instant lock) rather than the flow-contingent LP edges the original EXP-3a Scenario D claimed.

## Caveats (provisional findings, pending EXP-3c)

1. Single-snapshot. The Peru `pe_rpal` book in particular sat in a regime that ended at ~14:00Z on 2026-05-28 (see `exp3a_peru_depth_check.md`); the executable dollar figure for Peru reflects that regime. A multi-snapshot sweep is needed to characterize the *frequency* of takeable arb at the institutional tier, not just one moment.
2. Institutional tier is hypothetical. Neither Kalshi nor Polymarket currently offers a 0.30%/0.20% institutional schedule; this is a counterfactual showing what fee level would *just* expose the arb. Reality is somewhere on the curve between retail and zero; volume tiers and direct-market-access deals would land in between.
3. Adverse selection / queue priority not modeled. A real take-take arb at the institutional tier requires racing the queue against other arbitrageurs; the dollar figures here are the *exclusive* fill assumption — first-come, first-served on the resting depth. In practice you'd compete and get a fraction.
4. Direction enforcement uses the natural crossed-book direction. Books that are NOT crossed at retail (no_cross rows above) remain $0 takeable at every tier — fees can't conjure a cross where none exists. EXP-3b is a sensitivity sweep on the *existing* crossed-book subset, not a discovery of new arbs.
