# Arm A — Episode Detection + Counterfactual First-Clearance

**Scope:** the FROZEN 30s panel (`FROZEN_MANIFEST.json`, `capture_ts < 2026-06-06T04:00:00Z`),
10 INCLUDED pairs (Appendix A, conditional-with-floor). Everything below is
deterministic and reproducible from:

```
uv run python batch_counterfactual/arms/arm_a_clearance.py   # episodes + per-contract first-clearance
uv run python batch_counterfactual/arms/extract_ladders.py   # scoped gz ladders at episode starts
uv run python batch_counterfactual/arms/arm_a_sized.py        # size-weighted first-clearance
uv run python batch_counterfactual/arms/arm_a_figs.py         # fig_a1..fig_a5
```

Outputs: `results/arm_a/{episodes.parquet, episodes_summary.csv, clearable_by_bucket.csv,
sensitivity.csv, stats.json, sized_clearance.parquet, ladders/*.parquet, figs/*.png}`.

---

## 0. Read-this-first caveats (do not skip)

- **Mechanical / flow-fixed counterfactual.** Every clearance number asks one
  narrow question: *holding the observed top-of-book (or full ladder) FIXED, could
  a single uniform-price call at the episode's first crossed quote have cleared, and
  at what price improvement?* It does **not** model how order flow, quoting, or
  inventory would have responded to the existence of an auction. These are
  *opportunity* figures, not realized-PnL.
- **Per-contract vs size-weighted are never mixed.** `arm_a_clearance.py` (and the
  `pi_*_c` columns / `clearable_frac_*`) are **per-contract** (price-only, from the
  panel). `arm_a_sized.py` / `sized_clearance.parquet` (`contracts_*`, `pi_usd_*`)
  are **size-weighted** and carry `metric='size_weighted'`. Any table that mixes
  them carries an explicit column.
- **Size-weighted $ inherit the published size convention.** `src/pm_micro/normalize.py`
  treats the Kalshi `*_dollars` level field as the contract-size field; we preserve
  that verbatim. Polymarket sizes are shares. Absolute size-weighted **$** are
  therefore convention-dependent; executable **contracts** and **clearing prices**
  are robust to the ambiguity. Read $ figures as order-of-magnitude.
- **Tier labels.** `gross` = zero-fee pre-fee view (`Tier.ZERO`); `retail` =
  live retail (Kalshi parabolic + PM category taker); `retail_pm_rebate` = retail
  with the PM maker rebate variant; `institutional` = counterfactual 0.30% taker /
  0.20% maker. Fee functions are ported verbatim in `fees.py`.
- **ASSUMPTION-1 (tie-break):** an optimal price interval clears at its midpoint,
  rounded to the finer venue tick (PM 0.001). **ASSUMPTION-2 (rationing):** pro-rata
  by order qty at the margin, no time priority, largest-remainder residue. Both live
  in `auction.py`; ASSUMPTION-2 only binds in the size-weighted path.

---

## 1. Methods — episode semantics

An **episode** is a contiguous run of GROSS-crossed cycles (`cross_size > 0`) for one
pair on the global daemon-cycle grid (10.1h outage excluded). It begins at the first
crossed cycle and **ends** on an *observed* uncross, an *observed* one-sided / `None`
leg, a gap **> `EPISODE_GAP_MAX_S`**, or market termination.

**Bridging assumption (decision Q2=A).** `EPISODE_GAP_MAX_S = 600s` is the
episode-contiguity tolerance and is **decoupled** from `book.py`'s 90s staleness bound
(unchanged — `book_state` still returns `None` past 90s). A daemon gap of **≤ 600s
within a crossed run is BRIDGED**: the unobserved interval is assumed continuously
crossed. Episodes that bridge any gap (an intra-episode delta > 90s) carry
`gap_adjacent=True` and a `bridged_gap_seconds` tally. Stated plainly: **≤ 600s
unobserved inside an episode is treated as continuously crossed.**

Durations are wall time from first to last crossed cycle (single-cycle episodes →
0s; immaterial to time-in-state totals, which the long tail dominates). Duration
strata used everywhere aggregates appear: **`<1min`, `1-5min`, `5-30min`, `>30min`**.

---

## 2. Headline findings

**The flagship is the extreme tail of the distribution, not the typical state.**
Over the full 9-day capture NYK is gross-crossed in **56.5%** of its present cycles
and breaks into **241 distinct episodes**. Its longest episode — the flagship — is
**15.15h / 1,787 cycles**, but the median NYK episode is far shorter. The continuously
crossed multi-hour window is the rare extreme, surrounded by hundreds of brief
re-crossings. (`fig_a1`, `fig_a5`.)

**Population (10 pairs, full capture):** 1,289 episodes, 67,860 crossed cycles,
~35,560 crossed-minutes total. Duration distribution: median **210s**, p90 **4,273s**,
max **54,524s** (flagship). Episode counts by bucket: `<1min` 455 · `1-5min` 252 ·
`5-30min` 347 · `>30min` 235. But crossed-minutes are dominated by the long tail:
the `>30min` bucket is 18% of episodes yet **86%** of all crossed-minutes
(30,560 of 35,560 min). (`fig_a5`.)

**The fee cliff survives the upgrade from snapshots to episodes.** Gross-crossed
holds for **100%** of episode-starts by construction, but who could actually eat it:

| tier | clearable fraction of episode-starts | median total per-contract PI (¢) |
|---|---|---|
| gross (zero-fee) | **1.000** | 0.70 |
| retail | **0.057** | 0.31 |
| retail + PM rebate | **0.130** | 0.64 |
| institutional (0.30/0.20%) | **0.774** | 0.54 |

Retail clears **<6%** of crossed episode-starts — consistent with the published
Part 1 "no takeable retail arb" headline — while a counterfactual institutional fee
schedule clears ~77%. (`fig_a2`.) Stratified by duration the cliff is stable across
buckets (retail 2–9%, institutional 72–80%; full grid in `clearable_by_bucket.csv`).

---

## 3. Per-pair summary

| pair | episodes | longest (h) | crossed-min | mkt-days | crossed-min/mkt-day | retail clearable | inst clearable |
|---|---:|---:|---:|---:|---:|---:|---:|
| intl_president_co_aesp | 96 | 5.27 | 2,278 | 9 | 253 | 0.00 | 1.00 |
| intl_president_pe_kfuj | 74 | 8.52 | 2,566 | 8 | 321 | 0.00 | 1.00 |
| intl_president_pe_rpal | 170 | 6.77 | 4,618 | 10 | 462 | 0.00 | 0.69 |
| ma_acquisition_wb_psky | 50 | 12.29 | 3,522 | 10 | 352 | 0.00 | 1.00 |
| nba_finals_nyk | 241 | 15.15 | 4,824 | 10 | 482 | 0.00 | 0.60 |
| nba_finals_sas | 290 | 3.31 | 3,387 | 10 | 339 | 0.00 | 0.59 |
| sports_retirement_arod | 65 | 5.58 | 2,262 | 5 | 452 | 0.09 | 0.63 |
| **sports_retirement_kelce** | 129 | 15.15 | **8,463** | 10 | **846** | **0.52** | 1.00 |
| us_mayor_la_kbas | 174 | 8.61 | 3,641 | 10 | 364 | 0.00 | 1.00 |
| us_senate_ak_mpel | 0 | 0.00 | 0 | 0 | — | — | — |

(Per `episodes_summary.csv`; `fig_a4` = crossed-min/mkt-day. `us_senate_ak_mpel` is
INCLUDED by the two-sided floor but is **never gross-crossed** — a clean zero.)

---

## 4. Gap-tolerance sensitivity (90 / 300 / 600s)

Episode count and longest-episode duration (h) per pair, across the three tolerances.
Longest-episode duration is **robust** — it changes only where a sub-600s daemon gap
sits inside the flagship window (NYK 13.54→15.15h, kelce 13.77→15.15h); episode
*counts* fall as expected when short fragments merge. The clearability headlines are
unchanged across all three.

| pair | n@90 | h@90 | n@300 | h@300 | n@600 | h@600 |
|---|---:|---:|---:|---:|---:|---:|
| intl_president_co_aesp | 150 | 5.27 | 117 | 5.27 | 96 | 5.27 |
| intl_president_pe_kfuj | 105 | 8.52 | 82 | 8.52 | 74 | 8.52 |
| intl_president_pe_rpal | 241 | 6.62 | 197 | 6.62 | 170 | 6.77 |
| ma_acquisition_wb_psky | 83 | 12.10 | 69 | 12.16 | 50 | 12.29 |
| nba_finals_nyk | 300 | 13.54 | 267 | 13.54 | 241 | 15.15 |
| nba_finals_sas | 340 | 3.31 | 310 | 3.31 | 290 | 3.31 |
| sports_retirement_arod | 80 | 5.58 | 73 | 5.58 | 65 | 5.58 |
| sports_retirement_kelce | 251 | 13.77 | 178 | 13.77 | 129 | 15.15 |
| us_mayor_la_kbas | 218 | 8.46 | 193 | 8.46 | 174 | 8.61 |
| us_senate_ak_mpel | 0 | 0.00 | 0 | 0.00 | 0 | 0.00 |

**Robustness:** the longest-episode duration and the per-tier clearability split are
stable across 90/300/600s; only the count of short episodes is tolerance-sensitive.
(`sensitivity.csv`.) At the chosen 600s, 606 of 1,289 episodes bridge at least one gap.

---

## 5. Scoped ladder extraction + size-weighted clearance

**Extraction coverage:** episode first-cycle timestamps only — **1,289 / 1,289
(100.0%)** have both-venue YES ladders in the raw gz (`ladders/coverage.json`). No
full-panel extraction. Top-of-book reconstructed from the ladders ties out exactly to
`book.py` (Kalshi YES asks rebuilt from `no_dollars` as `(1-p, size)`, per
`src/pm_micro/normalize.py`).

**Size-weighted first-clearance** (`sized_clearance.parquet`, `metric='size_weighted'`)
ran the full uniform-price call on both venues' complete ladders, both objectives, all
tiers. Clearable fractions match the per-contract path **exactly** (gross 1.000 /
retail 0.057 / rebate 0.130 / institutional 0.774) — the size path does not move the
cliff. At gross, the median episode-start clears **~415 contracts** for a median
**~$0.85** price improvement (`max_volume`); summed across all gross-clearable starts,
~**$24.9k** of mechanical PI. `max_volume` and `max_agg_pi` choose **different** clearing
prices in **1,864 / 5,156** episode×tier rows (`objective_disagree=True`) — a real,
documented divergence, not noise. Flagship (NYK#0000): gross ≈ $468 / 132,292 contracts,
institutional ≈ $239 / 132,253 contracts; retail and rebate blocked (`fig_a3`).

---

## 6. Figures

- `fig_a1_duration_distribution.png` — stratified episode-duration distribution (log-x).
- `fig_a2_clearable_by_tier.png` — clearable fraction by fee tier × duration bucket.
- `fig_a3_knicks_flagship.png` — **FLAGSHIP**: NYK crossed top-of-book + counterfactual
  first call (per-contract PI per side, size-weighted $ / contracts annotated, by tier).
- `fig_a4_minutes_crossed_per_day.png` — minutes-in-crossed-state per market-day, per pair.
- `fig_a5_buckets_per_pair.png` — episode count + total crossed-minutes by duration bucket.

---

## 7. ANOMALIES (stated loudly, not smoothed)

1. **kelce is retail-clearable ~52% of the time — this contradicts the Part 1
   "no takeable retail arb" headline.** `sports_retirement_kelce` clears at the live
   **retail** tier in 52% of its 129 episode-starts (and 100% institutional), and it
   carries the most crossed time of any pair (846 crossed-min/market-day, 8,463 min
   total). The blanket "retail can't eat the cross" claim is a *population* statement;
   at the pair level it is false for kelce (and partially for `sports_retirement_arod`,
   ~9% retail). Either the cross on these retirement markets is genuinely large enough
   to clear retail fees, or their PM fee category / quoting differs from the basketball
   pairs. Flagged for Arm-B follow-up; do not repeat "zero retail arb" without the
   kelce exception.

2. **Institutional clearance is NOT universal.** The institutional tier clears only
   ~60% of NYK, ~59% of SAS and ~69% of rpal episode-starts — i.e. a large minority of
   *gross-crossed* episodes have crosses too thin to survive even a 0.30/0.20% schedule.
   "Institutional could eat it" is a ~77% population statement, not a guarantee.

3. **The flagship is atypical of its own market.** NYK's headline 15.15h continuously
   crossed window coexists with 240 other NYK episodes and a 56.5% crossed-cycle rate.
   Any narrative that treats the flagship as "the NYK state" overstates persistence;
   the median NYK episode is short. (Framed as the Q1=A headline above.)

4. **kelce and NYK report an identical longest-episode span (54,524.13s).** Both
   episodes start at capture start and terminate at the same daemon boundary; this is a
   shared grid feature, not a copy bug (verified: kelce longest = 1,787 cycles, 2 bridged
   gaps / 824.6s).

5. **`us_senate_ak_mpel` passes the inclusion floor but never crosses.** It is two-sided
   often enough to be INCLUDED yet has 0 gross-crossed episodes — a reminder that
   inclusion (liquidity presence) and dislocation (crossing) are independent.

> **Reconciliation:** the kelce retail-clearable anomaly (§7.1) is examined in [`results/arm_a/RECONCILIATION_KELCE.md`](results/arm_a/RECONCILIATION_KELCE.md) — verdict: not a contradiction (Part 1's '0 of 15' is a pre-panel 2026-05-28 02:29Z snapshot where kelce's cross was 0.2¢; the retail-clearable regime is a later, wider-cross vintage of a tail-priced low-fee-wall market).
