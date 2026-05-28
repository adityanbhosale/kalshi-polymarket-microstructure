# EXP-3a: Fee Correction Diff vs Stale Baseline

**Snapshot:** `snapshot_20260528T022943Z`
**Markets computed:** 15  
**Markets skipped:** 1  

## Fee model corrections

**Stale baseline (pre-EXP-3a):** Kalshi $0.02 flat per contract, Polymarket 2% flat of notional. Both legs taker. Source: hardcoded constants in `src/pm_micro/arb.py` lines 17-19 prior to this commit.

**Corrected models (live API, fetched 2026-05-28):**

* Kalshi parabolic: `taker_cents = ceil(7 * fee_multiplier * C * (1-C))`. All 16 markets have `fee_multiplier=1`. At midprice this equals the historical 2¢; at tail prices (C<0.10 or C>0.90) it drops to 1¢.
* Kalshi maker: 25% of taker for `fee_type=quadratic_with_maker_fees` (4 NBA Finals only); **$0** for `fee_type=quadratic` (other 12 markets). We do NOT apply 25% uniformly.
* Polymarket: category-dependent, pulled per-market from `feeSchedule.rate`. Sports = 3%, politics/tech = 4%. **Zero of our 16 markets are fee-free geopolitics** — all intl elections classify as `politics_fees` at 4% per the live API.
* Polymarket maker: 0% (`takerOnly: true` on every market). Rebate is 25% of counterparty taker fee (modeled OFF by default; not used in any scenario below to keep maker numbers conservative).

## Per-market verdict diff

| market | category | k_mult | k_fee_type | pm_rate | stale | corr_taker | mixed | both_maker | verdict_Δ |
|---|---|---|---|---|---|---|---|---|---|
| nba_finals_okc | sports_nba_finals | 1.0 | quadratic_with_maker_fees | 0.03 | NO ($0.00) | NO ($0.00) | NO ($0.00) | NO ($0.00) | N |
| nba_finals_nyk | sports_nba_finals | 1.0 | quadratic_with_maker_fees | 0.03 | NO ($0.00) | NO ($0.00) | NO ($0.00) | NO ($0.00) | N |
| nba_finals_sas | nba_finals | 1.0 | quadratic_with_maker_fees | 0.03 | NO ($0.00) | NO ($0.00) | NO ($0.00) | NO ($0.00) | N |
| sports_retirement_arod | sports_retirement | 1.0 | quadratic | 0.03 | NO ($0.00) | NO ($0.00) | YES ($0.06) | YES ($2.98) | **Y** |
| sports_retirement_kelce | sports_retirement | 1.0 | quadratic | 0.03 | NO ($0.00) | NO ($0.00) | NO ($0.00) | YES ($0.45) | **Y** |
| us_senate_ak_mpel | us_senate | 1.0 | quadratic | 0.04 | NO ($0.00) | NO ($0.00) | NO ($0.00) | NO ($0.00) | N |
| intl_president_co_aesp | intl_president | 1.0 | quadratic | 0.04 | NO ($0.00) | NO ($0.00) | NO ($0.00) | YES ($30.23) | **Y** |
| intl_president_co_pval | intl_president | 1.0 | quadratic | 0.04 | NO ($0.00) | NO ($0.00) | NO ($0.00) | YES ($0.43) | **Y** |
| intl_president_pe_kfuj | intl_president | 1.0 | quadratic | 0.04 | NO ($0.00) | NO ($0.00) | NO ($0.00) | NO ($0.00) | N |
| intl_president_pe_rpal | intl_president | 1.0 | quadratic | 0.04 | NO ($0.00) | NO ($0.00) | NO ($0.00) | YES ($50.59) | **Y** |
| intl_president_r1_co_icas | intl_president_round1 | 1.0 | quadratic | 0.04 | NO ($0.00) | NO ($0.00) | NO ($0.00) | NO ($0.00) | N |
| intl_mayor_kr_oseh | intl_mayor | 1.0 | quadratic | 0.04 | NO ($0.00) | NO ($0.00) | NO ($0.00) | YES ($5.00) | **Y** |
| us_mayor_la_kbas | us_mayor | 1.0 | quadratic | 0.04 | NO ($0.00) | NO ($0.00) | NO ($0.00) | YES ($2.95) | **Y** |
| us_mayor_la_rhua | us_mayor | 1.0 | quadratic | 0.04 | NO ($0.00) | NO ($0.00) | NO ($0.00) | NO ($0.00) | N |
| ma_acquisition_wb_psky | ma_acquisition | 1.0 | quadratic | 0.04 | NO ($0.00) | NO ($0.00) | NO ($0.00) | NO ($0.00) | N |

## Skipped markets

* `nba_finals_cle`: missing Polymarket YES snapshot: nba_finals_cle_polymarket_yes.json (token likely delisted at fetch time) — delisted 2026-05-26, PM 404, no executable arb computable

## Summary of verdict flips

* **B (corrected taker) vs A (stale):** 0 flips out of 15.
* **C (mixed: K taker / PM maker) vs A:** 1 flips.
* **D (both maker) vs A:** 7 flips.

Which markets flip and why:

* **Scenario B (corrected taker)**: no markets flip.
* **Scenario C (mixed)** (1 flips):
  * `sports_retirement_arod` ($0.00 → $0.06)
* **Scenario D (both maker)** (7 flips):
  * `sports_retirement_arod` ($0.00 → $2.98)
  * `sports_retirement_kelce` ($0.00 → $0.45)
  * `intl_president_co_aesp` ($0.00 → $30.23)
  * `intl_president_co_pval` ($0.00 → $0.43)
  * `intl_president_pe_rpal` ($0.00 → $50.59)
  * `intl_mayor_kr_oseh` ($0.00 → $5.00)
  * `us_mayor_la_kbas` ($0.00 → $2.95)

## ARod depth-binds check

The D.2 finding (`docs/build_log.md:30-34`) was: *"sports_retirement_arod paper edge (+5.85c) CLEARS the ~3c fee threshold — the first such market in the project — yet executable arb is still $0 because Polymarket YES has $0 depth within 1c. In thin tail markets the binding constraint is depth, not the 2% taker fee."*

**On this snapshot the framing of that finding was muddled.** The +5.85c number was the *mid-discrepancy* (poly_yes_mid - kalshi_mid). The relevant executable spread is the at-the-touch gap between best Kalshi ask and best Polymarket YES bid, which was ~1.0c at the time and is ~1.1c on this D.2 snapshot — i.e. BELOW the stale 3c round-trip fee floor. Under stale fees the walker terminates at level 0 because per-contract is *negative*, not because depth runs out. Whether fees or depth binds depends on the scenario:

At the D.2 snapshot, Kalshi mid = 0.0300, Polymarket YES mid = 0.0900. Mid-discrepancy: direct = 6.00c, synthetic = 6.00c. At-the-touch direct spread (PY_bid − K_ask) ≈ 1.1c. Top-of-book sizes: K_ask = 695, PY_bid = 60, PY_ask = 13.

Per scenario:

* **A_STALE**: best_net = $0.00, verdict = NO, direct fillable = 0, synth fillable = 0.
* **B_CORR_TAKER**: best_net = $0.00, verdict = NO, direct fillable = 0, synth fillable = 0.
* **C_MIXED**: best_net = $0.06, verdict = YES, direct fillable = 60, synth fillable = 60.
* **D_BOTH_MAKER**: best_net = $2.98, verdict = YES, direct fillable = 296, synth fillable = 296.

**Verdict: the executable-arb-is-zero result holds under corr_taker, but the *mechanism* is fees, not depth.**

* Under A_STALE and B_CORR_TAKER: the at-the-touch 1.1c paper spread does not survive the round-trip fee (~3.0c stale, ~1.15c corrected sports-taker = K parabolic ~1c + PM 3% × $0.05 ≈ 0.15c). Walker terminates at level 0 with negative per-contract. **Fees bind, not depth.**
* Under C_MIXED (PM maker = 0): fees almost vanish on the PM leg; net per-contract is ~+$0.001. **Depth then binds**: only 60 contracts at the inside, walker stops at level 1 when prices step off-touch. Net = $0.06.
* Under D_BOTH_MAKER: both legs free, walker lifts deeper levels until the next big tick jump on PM kills per-contract; 296 contracts filled, $2.98 net.

So the D.2 build_log assertion that *"depth, not the 2% taker fee, is the binding constraint"* is **incorrect on this snapshot under the actual (stale or corrected) taker fee schedule**. Depth-binds only emerges as the binding mechanism once PM fees drop to maker (0%). The corrected `build_log.md` entry should distinguish *mid-discrepancy* (5.85c, irrelevant to execution) from *at-the-touch spread* (1.1c, what actually has to clear fees).

## PROSE CLAIMS REQUIRING UPDATE

The repo cites a `~3¢ fee threshold` in five places, derived from the stale Kalshi $0.02 + Polymarket 2% × $0.50 mid model. Under the corrected fee schedule the threshold is no longer flat — it depends on the market's category and price level. Suggested updates below; apply deliberately.

| Location | Stale claim | Suggested corrected sentence |
| --- | --- | --- |
| `README.md:9` | "…~3¢ fee threshold…" | The conservative fee floor is ~2c at midprice (Kalshi parabolic + Polymarket sports at 3%) and ~2.5c for politics markets (4% PM leg); tail-priced markets see ~1c on the Kalshi leg. See `data/processed/exp3a_fee_correction.md` for per-market detail. |
| `README.md:49` | "…3¢ fee threshold…" | Per-market fee floors range from ~1.3c (tail-priced sports) to ~2.5c (central-priced politics), under the corrected Kalshi parabolic / Polymarket category-dependent model verified against live venue APIs on 2026-05-28. |
| `README.md:55` | "…clears the ~3¢ fee threshold…" | ARod's *mid-discrepancy* (+5.85c) clears the corrected fee floor but the *at-the-touch* executable spread is only ~1.1c, which does not survive either the stale ~3c or the corrected ~1.15c (sports taker) round-trip fee. Executable arb remains $0 because of fees at the touch — depth only becomes the binding constraint if PM fees drop to maker mode (see `data/processed/exp3a_fee_correction.md`). |
| `docs/findings.md:7` | "…~3¢ fee threshold…" | After correcting the fee model to Kalshi parabolic + Polymarket category-dependent rates (3% sports, 4% politics/tech, 0 fee-free geopolitics), the per-market fee floor ranges from ~1.3c (tail sports) to ~2.5c (central politics). The no-executable-arb finding strengthens on most central-priced markets because the corrected Polymarket politics rate (4%) is higher than the stale 2%. |
| `docs/build_log.md:30-34` | D-finding (2): "sports_retirement_arod paper edge (+5.85c) CLEARS the ~3c fee threshold ... executable arb is still $0 because Polymarket YES has $0 depth within 1c. In thin tail markets the binding constraint is depth, not the 2% taker fee." | **Re-characterize.** Under stale fees, the +5.85c MID-discrepancy obscured the relevant number: the at-the-touch direct spread is only ~1.1c, which is BELOW both the stale ~3c and the corrected ~1.15c (sports-taker) round-trip fee. The walker terminates at level 0 with NEGATIVE per-contract — *fees bind at the touch, not depth*. Depth becomes the binding constraint only under the MIXED scenario (PM maker = 0%), where ARod yields $0.06 capped by 60 contracts of PM YES bid size. The corrected D-finding: *in this snapshot fees still bind for ARod even under corrected taker; the depth-binds story only activates once a strategy can post passive on Polymarket.* |

Additional note for `docs/findings.md` and `docs/build_log.md`: the user's expectation that Colombia/Peru/Seoul (`intl_president_*`, `intl_mayor_*`) would map to fee-free `geopolitics` on Polymarket is contradicted by the live `feeType` field — all 6 intl-election markets in our panel return `politics_fees` at 4%. There is no fee-free arb surface in the current dataset. The favorable-PM-leg category exists in the rate table (`CATEGORY_RATES['geopolitics'] = 0`), but no market on our panel uses it.
