# Build Log

Append-only record of follow-on builds (EXP series). One entry per build.
Findings enter here when OBSERVED; they graduate to docs/findings.md only
after surviving the next build's data. Do not rewrite past entries.

---

## Build D — Expand market coverage (EXP-6)
**Date:** 2026-05-27
**Goal:** Expand cross-venue dataset beyond the 3 NBA Finals pairs to test
whether headline findings replicate at scale and across categories.

**Sub-steps:**
- D.1: Built discovery infrastructure — src/pm_micro/discovery.py (locked
  constants, rapidfuzz match scoring, prob-bucket assignment, paginated
  fetchers, ID validator), scripts/discover_markets.py,
  scripts/validate_markets_yaml.py, scripts/curate_candidates.py.
  Output: 96 candidates, semantically tagged into match_type categories.
- D.2: Expanded markets.yaml 3 → 16 (13 new picks across sports, US/intl
  politics, M&A). Added delisted markers for CLE (both tokens) and NYK
  (NO token) 404s. Re-ran Phase 3-4 snapshot + arb.
- Spread diagnostic: verified K/P spread asymmetry is tick-mechanical,
  not a normalize.py artifact.

**Findings observed (PROVISIONAL — pending next-build confirmation):**
1. No-executable-arb REPLICATES at scale: 8/15 markets show crossed-book
   paper signal, zero survive fees. No category-specific arb regime — intl
   and political markets behave like NBA on the fee frontier.
2. ~~Depth binds before fees. sports_retirement_arod paper edge (+5.85c)
   CLEARS the ~3c fee threshold — the first such market in the project —
   yet executable arb is still $0 because Polymarket YES has $0 depth
   within 1c. In thin tail markets the binding constraint is depth, not
   the 2% taker fee. (More Lean-relevant than the fee story: depth-aware
   execution is what a terminal provides.)~~
   **[CORRECTED by EXP-3a, 2026-05-28]:** The +5.85c number was the
   *mid-discrepancy* (poly_yes_mid − kalshi_mid), not the at-the-touch
   executable spread. The actual at-the-touch direct spread on the D.2
   snapshot was ~1.1c (PM YES bid 0.051 vs Kalshi YES ask 0.04). That
   spread does NOT clear either the stale ~3c round-trip fee or the
   corrected ~1.15c sports-taker round-trip fee (Kalshi parabolic 1c at
   the 4c price + PM 3% × 5c ≈ 0.15c). Under both stale and corrected
   taker, the walker terminates at level 0 with negative per-contract:
   **fees bind at the touch, not depth.** Depth-binds only emerges
   under the MIXED scenario (PM execution = maker, fee = 0), where ARod
   yields $0.06 capped by 60 contracts of PM YES bid size before the
   next price step kills per-contract. Lean-relevant reframing: the
   depth story activates only for strategies posting passive on
   Polymarket; a pure taker strategy is still fee-blocked at the touch.
   See `data/processed/exp3a_fee_correction.md` § "ARod depth-binds
   check" for the full per-scenario decomposition.
3. Spread asymmetry is structural/tick-mechanical. 4/5 sampled Kalshi
   books sit at the 1-tick floor (excess_bps=0); Kalshi's 1c tick vs
   Polymarket's 0.1c effective tick mechanically inflates tail-market
   spread_bps. Sole genuine-width exception: kelce (maker scarcity, 2
   resting bids). normalize.py reconstruction verified against raw
   yes_ask_dollars. CAVEAT: "symmetric pairs" is snapshot-dependent, not
   a stable category (OKC's apparent symmetry is partly Polymarket having
   a wide body right now).
4. NYK bucket drift mid_low -> central -> mid_low over ~36hr, now -0.95c
   with Kalshi richer. Kalshi participants re-rate faster than Polymarket
   as Spurs/OKC info arrives — directional speed asymmetry. Observed twice
   now. Seeds EXP-1 (sim) and EXP-4 (latency).
5. same_race_diff_side = 0 across 96 candidates: venues converge on the
   same candidate set per race; no naturally-occurring cross-venue
   "A on Kalshi, B on Polymarket" structure within one contest.

**Errata:** CLE NO token newly 404'd since the morning snapshot (Cavs
eliminated 2026-05-26; Polymarket delisted both Cavs-win sides on ~24hr lag
— reinforces Finding 3 delisting-follows-impossibility pattern).

**Files added:** src/pm_micro/discovery.py, scripts/{discover,curate,
validate,expand}_markets*.py, data/processed/{discovery_candidates,
discovery_curated,spread_asymmetry_check}.md
**markets.yaml:** 3 -> 16 entries
**Tests:** 6/6 green throughout

---

## Build EXP-3a — Fee engine correction
**Date:** 2026-05-28
**Goal:** Replace the repo's stale flat fee constants (Polymarket 2%,
Kalshi $0.02/contract, both legs taker) with live per-market fee schedules
from the venue APIs, and quantify how the executable-arb verdict changes.
Targeted correction; the broader fee-tier sweep is EXP-3b.

**Sub-steps:**
- Built `src/pm_micro/fees.py` (Kalshi parabolic `ceil(7 × mult × C × (1-C))`
  cents, Polymarket category-dependent rates table, maker/taker/rebate
  models). Refactored `src/pm_micro/arb.py` to delegate to it via a new
  `FeeContext` dataclass; legacy constants (`POLYMARKET_TAKER_FEE_RATE`,
  `KALSHI_PER_CONTRACT_FEE`) retained as inert module-level for diff
  scripts but read by zero live paths.
- `scripts/fetch_market_fee_metadata.py` pulls Kalshi `/series` fields
  (`fee_multiplier`, `fee_type`) + Polymarket Gamma `feeSchedule.rate`
  per market; output `data/processed/market_fee_metadata.yaml`.
- `scripts/exp3a_fee_correction.py` re-runs the D.2 snapshot
  (`snapshot_20260528T022943Z`) under 4 fee scenarios: stale, corrected
  taker (both legs), mixed (K taker / PM maker), both maker. Output
  `data/processed/exp3a_fee_correction.md`.
- `scripts/exp3a_peru_depth_check.py` validates the Scenario-D Peru
  $50.59 against the E.1 daemon's ~1670 raw PM YES snapshots covering
  2026-05-28T04:00Z–18:12Z. Output
  `data/processed/exp3a_peru_depth_check.md`.

**Findings observed (PROVISIONAL — pending EXP-3b fee-tier sweep):**
1. **Zero geopolitics, zero fee-free markets in panel.** The user
   hypothesis that Colombia/Peru/Seoul would map to PM `world_events`
   (0% fee) is contradicted by the live `feeType` field — all 6
   intl-election markets return `politics_fees` at 4%. There is no
   fee-free arb surface in the current dataset.
2. **No-arb finding STRENGTHENS under corrected fees, not softens.**
   0/15 markets show executable arb under corrected B (both legs taker).
   The corrected PM politics rate (4%) is *higher* than the stale 2%,
   so central-priced political markets are tighter against fees than
   the stale model implied. 1 market (ARod) flips under C (mixed,
   $0.06); 7 markets flip under D (both maker, headline $0.06–$50.59).
3. **Edge is execution-mode, not arbitrage.** The verdict gradient
   0-taker / 1-mixed / 7-maker (out of 15) quantifies what the project
   has been gesturing at since Build B: cross-venue value is *liquidity
   provision*, not *price discrepancy*. A strategy that posts passive on
   Polymarket and crosses on Kalshi (mixed) is on a fundamentally
   different fee floor than one that takes on both venues. The number
   of profitable markets goes up monotonically as fees decline, which
   makes the case explicitly: every cent of fee discount becomes
   accessible alpha at the maker margin.
4. **Build-D ARod finding was wrong.** Corrected above (Build D §2):
   the +5.85c was mid-discrepancy, not at-the-touch; under stale or
   corrected-taker, *fees* bind, not depth; depth-binds only activates
   under PM maker mode.
5. **Peru depth verdict: (a*) PERSISTENT WITHIN REGIME** —
   the 3225-contract resting ask at 0.271 underlying the Scenario-D
   $50.59 is real and sustained across the ~10 hours surrounding the
   D.2 fetch (100.0% large-level presence in the early window). A
   regime shift at ~14:00Z (best ask fell from ~0.27 to ~0.22)
   collapsed the level (53.3% in the late window). Depth was not a
   spoof or single-snapshot artifact; it was real LP behavior that
   re-quoted when consensus probability moved. Separate caveat: the
   Scenario-D figure also mis-models execution mode — the trade buys
   PM (takes the ask, 4% taker fee), so even with persistent depth
   the $50.59 is an idealized number, not a takeable opportunity.

**Errata:** Build-D finding 2 (depth-binds) re-characterized in place
above with strike-through + annotation, per append-only discipline.

**Files added:**
- `src/pm_micro/fees.py`, `tests/test_fees.py` (45 new tests)
- `scripts/fetch_market_fee_metadata.py`,
  `scripts/exp3a_fee_correction.py`,
  `scripts/exp3a_peru_depth_check.py`
- `data/processed/market_fee_metadata.yaml`,
  `data/processed/exp3a_fee_correction.md`,
  `data/processed/exp3a_peru_depth_check.md`

**Files modified:** `src/pm_micro/arb.py` (refactor only; legacy
constants kept inert as documented), `docs/build_log.md` (this entry +
Build-D finding-2 strike-through). `markets.yaml`, `README.md`,
`docs/findings.md`, E.1 daemon, and F.1 harness untouched.

**Prose updates DEFERRED:** the "~3¢ fee threshold" is cited in 5
places (`README.md:9,49,55`, `docs/findings.md:7`, `docs/build_log.md`
Build D §2 — the last fixed above; the README/findings ones not yet
touched). Suggested replacement sentences live in
`data/processed/exp3a_fee_correction.md` § "PROSE CLAIMS REQUIRING
UPDATE" for a deliberate later pass.

**Tests:** 51/51 green (6 prior + 45 new in `tests/test_fees.py`).
`tests/test_normalize.py::test_fees_directional` verified independently
after the `arb.py` refactor.

### EXP-3a addendum — direction correction (2026-05-28, post-review)
Reviewer caught a category error in Scenarios C and D: the
`execution_mode='maker'` fee was applied to whichever venue the
FeeContext named, regardless of which side of the cross the trade had
to hit. On a crossed book the natural take-take execution is taker on
BOTH legs; maker pricing is only available on the side a strategy ADDS
liquidity to (post passive, wait for incoming flow), not the side it
crosses. The original C/D walker also reported dollar figures tied to
the contra-venue's resting depth — but a maker can't fill against that
depth at maker rates, only by attracting flow to their post.

`scripts/exp3a_direction_correction.py` reclassifies each of the 8
flips (1 C + 7 D) per leg as add-side (maker-eligible) or cross-side
(taker-forced), recomputes per-contract edges, and re-verdicts under
direction enforcement. Output:
`data/processed/exp3a_direction_correction.md`.

**Findings (PROVISIONAL pending EXP-3b fee-tier sweep):**
- **0 takeable, 8 flow-contingent, 0 fees-bind.** None of the 8
  original flips survive as genuinely takeable arb. Every C/D flip
  required at least one add-side leg; the per-contract edges are real
  (PM 4% → 0% maker, K parabolic → 0c for quadratic markets) but
  extracting them requires posting passive on PM (or K) and being
  filled by incoming flow, not lifting contra-venue depth.
- The honest cross-venue *arbitrage* count on the D.2 snapshot is
  **0/15** — matches Scenario B (corrected taker). The C/D winners
  quantify a *liquidity-provision* edge, not an arbitrage edge.
- Headline dollar figures from the original direction-blind D ($50.59
  Peru, $30.23 Colombia AESP, etc.) were category errors: they modeled
  the LP as also sweeping the contra-venue's resting depth at maker
  rates. Peru's $50.59 is killed by direction enforcement
  *independently* of the regime-shift caveat from
  `exp3a_peru_depth_check.md`. Both corrections kill the number.
- Lean-relevant: this reframes the project's headline from "no
  takeable arb because of fees" to "no takeable arb because of fees;
  LP edge exists at 0.1c–2.7c per contract on a flow-contingent
  basis." Both are no-arbitrage findings; the second one is more
  actionable for a market-making thesis.

**.gitignore:** added `data/processed/timeofday_poll.csv` and
`data/processed/event_*_poll.csv` (E.1 daemon + F.1 harness live
outputs; these grew continuously into the repo and were tracked by
mistake). Files left intact on disk; `git rm --cached` only.

**Tests:** still 51/51 green; no source code changed in this addendum
(direction correction is analysis-only).

### EXP-3b — fee-tier sensitivity sweep (2026-05-28)
With the direction-correct engine in place, parameterize the fee tier
and ask: does *takeable* cross-venue arb appear below the retail tier?

`scripts/exp3b_fee_sweep.py` runs the D.2 snapshot through four tiers
on the direction-enforced take-take path (`compute_executable_arb_direct`
with a per-tier `FeeContext`):

1. **retail** — corrected baseline (K parabolic 7c·C·(1−C), PM
   category 3–4%).
2. **pm_rebate** — retail taker + PM 25% maker rebate active.
   Take-take column is identical to retail (rebate only enters on
   add-side legs); LP column changes.
3. **institutional** — counterfactual 0.30% taker / 0.20% maker
   rebate flat on both venues (QCX/CME-style).
4. **zero** — theoretical zero-fee floor.

Output: `data/processed/exp3b_fee_sweep.md`.

**Findings (PROVISIONAL pending EXP-3c multi-snapshot sweep):**
- **Takeable count by tier:** retail 0/15 → pm_rebate 0/15 →
  **institutional 8/15** → zero 8/15. The fee cliff is between
  retail and institutional, *not* between institutional and zero.
- The 8 takeable markets at institutional are exactly the 8 with a
  crossed book at the snapshot. Lowering fees further to zero adds
  zero new markets — the 7 non-crossed names stay $0 takeable at any
  fee. Fees can't conjure a cross.
- **~$73 total executable @ institutional** (~$93 @ zero); Peru
  (`pe_rpal` $39.76) and Colombia (`co_aesp` $23.33) drive the
  headline. These are *genuinely* takeable — both legs cross-side,
  instant lock — not the flow-contingent LP edges that EXP-3a's
  direction-blind Scenario D had assigned the same magnitudes to.
  *(See errata below — this ~$73 is ex-NYK on the D.2 fetch; median
  over 1,748 polls is **$190.82**, EXP-3c.)*
- **New market `nba_finals_nyk` joins the takeable set** at
  institutional ($1.13, 282c). NYK wasn't in EXP-3a's C/D flip list
  (its 0.4c crossed spread was too tight for the retail/D scenarios
  with the books it had); at 0.30% taker the round-trip fee
  (~0.17c) clears the 0.4c paper edge.
- **LP column observation:** activating the PM 25% maker rebate
  flips `intl_president_co_aesp` from −0.000c to +0.670c per
  contract — the rebate has real magnitude for an LP strategy on
  central-priced (≈ 0.5) politics markets, even though it leaves
  the takeable column untouched.

**Caveats:** single snapshot (Peru reflects the pre-14:00Z regime
per `exp3a_peru_depth_check.md`); institutional 0.30%/0.20% is
counterfactual (neither venue offers it today, this is a
sensitivity boundary not a quote); adverse selection / queue
priority not modeled (exclusive-fill assumption); the sweep
characterizes what fee unlocks the *existing* crossed subset, it
does not discover new arbs.

**Lean-relevant reframing:** combining EXP-3a + EXP-3b, the
project's headline is now precise: *no takeable cross-venue arb at
retail fees on any of the 15 markets; an institutional 0.30% tier
would unlock takeable arb on every crossed-book market in the
panel; the LP edge (flow-contingent) is real at every tier and is
enhanced by PM maker rebates on central-priced names.* All three
statements are simultaneously true and were not separable before
the fee engine fix.

**Tests:** 51/51 green; no source code changed (EXP-3b is a script
that parameterizes the existing engine, no `fees.py` / `arb.py`
edits).

> **Errata — institutional $ (2026-06-03):** The **~$73** above is the
> **single-snapshot sum of the seven non-`nyk` markets** at D.2
> (`snapshot_20260528T022943Z`, 02:29Z), with `nyk` logged separately at
> **$1.13** — ex-NYK / pre-NYK-dislocation, not the full eight-market
> panel. Recomputing that snapshot today: NYK **~$56**, eight-market sum
> **~$129**. The time-median aggregate is **$190.82** (EXP-3c: sum of
> 8-market institutional takeable $ per 30s poll, **n=1,748**, 14.8h).
> Public-facing copy and `fig_fee_cliff_substack.png` use the median.

### EXP-3c — multi-snapshot persistence (2026-05-28)
Convert the EXP-3b single-snapshot $73-at-institutional result into a
frequency-characterized one across the full E.1 daemon history.

`scripts/exp3c_persistence.py` walks 13,960 (market × snapshot)
records from `data/raw/timeofday/` — 1,745 distinct 30-second
timestamps over ~14.5h (2026-05-28T04:01Z → 18:46Z) — for the 8
EXP-3b takeable-subset markets. For each snapshot, reconstructs
full orderbooks from gzipped raw dumps and runs the direction-
enforced take-take walker at the institutional (0.30% taker flat)
tier. Output: `data/processed/exp3c_persistence.{md,csv}`,
`figures/exp3c_crossed_by_hour.png`,
`figures/exp3c_correlation_heatmap.png`.

**Findings (PROVISIONAL pending adverse-selection / queue-priority
modeling):**
- **100% of snapshots have ≥1 of the 8 markets crossed** at
  institutional fees. Median total takeable $ when something is
  crossed: **$190.82** (mean $189.79, max $407.48). Excluding
  `nyk` (which dominates): median **$17.45**.
- **Persistence verdicts:** 5 PERSISTENT (`nyk`, `kelce`,
  `co_pval`, `pe_rpal`, `la_kbas`); 2 INTERMITTENT (`kr_oseh`,
  `arod`); 1 RARE (`co_aesp`); 0 SNAPSHOT-ONLY. `co_aesp`'s D.2
  2c-paper $23 figure does **not** replicate intraday — only 4.3%
  of subsequent snapshots are crossed (72.8% in the 04Z hour only,
  then 0% for the rest of the window).
- **Cross-market correlation:** median |corr| across 15 pairs
  (excluding always-crossed `nyk`/`kelce`) = **0.15**. Edges are
  largely independent, not one liquidity regime. Strongest positive
  `kr_oseh`↔`co_pval` (+0.38); strongest negative `co_aesp`↔
  `co_pval` (−0.39).
- **Time-of-day:** `co_aesp` shows the cleanest TOD signal (04Z
  only). `arod` high in 04Z–07Z, drops 09Z–11Z, partial recovery
  13Z–16Z. See `figures/exp3c_crossed_by_hour.png`.

**Adverse-selection caveat (load-bearing):** `nyk` is 100%
crossed for the entire 14.5h window at median $165.89/snapshot
(max $406.35). No real institutional arbitrageur with 0.30% access
would let that persist for seconds, much less hours. Either (a) no
actor currently has the 0.30%/0.20% access modeled, or (b) the
resting K bid 0.30 / PM ask 0.285 are informed quotes and lifting
them is adversely selected. The exclusive-fill assumption is the
load-bearing one for all headline dollar figures. **All EXP-3c
dollar magnitudes are PROVISIONAL pending adverse-selection /
queue-priority modeling.**

**Lean-relevant update:** EXP-3b's "institutional tier unlocks
takeable arb on every crossed-book market" is confirmed as a
*structural* finding (crossed books persist), but the *economic*
magnitude and exploitability remain unvalidated. The project
headline is now: *no takeable arb at retail; crossed-book edges
exist at institutional fees but may be adversely selected; LP edge
(flow-contingent) is real at every tier.*

**Tests:** 51/51 green; no source code changed (EXP-3c is analysis
script only).

### Stage-1 closure (post-EXP-3a/b/c + fee-tier reality check) (2026-05-28)
Stage-1 question: *is there takeable cross-venue arbitrage between
Kalshi and Polymarket on the curated panel?* Answer: **no, at any
accessible fee tier.**

**Fee-tier sweep (EXP-3a/b/c, consolidated):**
- **Retail (corrected):** 0/15 takeable. Kalshi parabolic
  7c·C·(1−C) + Polymarket category 3–4% taker exceeds the
  at-the-touch crossed spread on every market in the panel.
- **PM maker-rebate active:** 0/15 takeable (rebate affects
  add-side LP only; take-take path unchanged).
- **Institutional 0.30% taker / 0.20% maker rebate:** both venues
  offer **no such tier** (verified by external check 2026-05-28).
  EXP-3b/3c institutional and zero-fee tiers are **counterfactual
  sensitivity bounds**, not accessible execution paths.
- **Zero-fee floor:** 8/15 crossed at the D.2 snapshot (the 8 with
  a crossed book); 7 non-crossed stay $0 at any fee. Fees can't
  conjure a cross.

**Persistence (EXP-3c):** of the 8 zero-fee crossed markets,
`nyk` and `kelce` are persistently crossed for the full 14.5h
daemon window (100% of snapshots). That persistence is itself
evidence the displayed depth is **not freely takeable** — informed
quotes / adverse selection — because no actor with the modeled fee
access exists on either venue. The exclusive-fill dollar figures
from EXP-3b/3c are structural upper bounds, not realized PnL.

**LP edges (EXP-3a direction-corrected):** 8 markets show
flow-contingent provideable spread (maker on add-side only; cross-
side legs pay taker). PM maker rebate flips `co_aesp`'s LP edge
from ~0c to +0.67c per contract on central-priced politics names.
These are liquidity-provision edges, not arbitrage.

**Live theses going forward:**
- **EXP-12** — liquidity provision (flow-contingent LP edges,
  PM maker rebate upside, queue/fill modeling).
- **EXP-4** — latency / lead-lag (cross-venue price discovery,
  event-window overlay from F.1 harness).

**Arb-as-taking-the-cross is dead** for Stage-1. The project pivots
from "find executable arb" to "characterize microstructure edges
(LP + latency) that survive fees and adverse selection."

> _Note: the formal Stage-1 closure below supersedes this interim
> summary; both retained per append-only discipline._

## Stage-1 closure — no takeable cross-venue arb at accessible fee tiers
**Date:** 2026-05-28
**Builds:** EXP-3a (fee correction + direction enforcement), EXP-3b (fee-tier
sweep), EXP-3c (persistence), external fee-tier check.

**Result:** No takeable cross-venue arbitrage exists on Kalshi/Polymarket
at any accessible fee tier.
- Retail (corrected, taker): 0/15 markets.
- PM maker rebate active: 0/15 markets.
- Institutional (0.30% taker / 0.20% rebate): 8/15 markets crossed at
  counterfactual tier; **median ~$191/snapshot** over 1,748 polls (EXP-3c;
  see EXP-3b errata — prior **~$73** was ex-NYK on one D.2 fetch). Persistence:
  5 PERSISTENT / 2 INTERMITTENT / 1 RARE / 0 snapshot-only across 14.5h.
- External check 2026-05-28: neither Kalshi nor Polymarket offers a 0.30%
  fee tier to any participant. Institutional and zero-fee scenarios are
  counterfactual.

**Interpretation:** The persistence of nyk's $165 median crossed spread for
14h is itself evidence the displayed depth is not freely takeable — no
actor with the modeled fee access exists, so the cross sits. The load-
bearing assumption on all LP-edge dollar figures is exclusive-fill at
displayed depth (adverse selection / queue priority NOT modeled).

**Live edges (LP / flow-contingent, EXP-3a direction-corrected):** 8 markets
show provideable spread under direction-enforced maker mode. PM rebate
activation flips co_aesp's LP edge from ~0 to +0.67c per contract,
illustrating real magnitude for LP strategies on central politics markets.

**Forward theses:**
- EXP-12 (liquidity provision) — 8 concrete provideable-spread markets as
  anchor. Agent is market-making + inventory, not arb-taking.
- EXP-4 (latency / lead-lag) — NYK confirmed Kalshi-leads-Polymarket; June
  3 / May 31 Colombia capture is second independent test. Edge does not
  require fee-tier access.

**Killed:**
- Cross-venue arb-as-taking-the-cross thesis at retail and at any accessible
  tier.
- EXP-1 (trader sim) as originally specified — would simulate a dead
  strategy. Could be re-scoped as LP sim later.
- EXP-10 (triangular/synthetic arb) — same execution constraints; deprioritized.

### EXP-12a — fill-realism + adverse-selection markout (2026-05-28)
Replace the load-bearing "exclusive-fill at displayed depth" assumption
behind the EXP-3a/3b/3c LP-edge dollar figures with a probabilistic fill
model + post-fill markout, calibrated on the full E.1 daemon history
(~2,244 snapshots × 8 markets).

New module: `src/pm_micro/fills.py` (fill-probability primitives, markout
sign convention, minimal logistic regression). Script:
`scripts/exp12a_fill_realism.py`. Output:
`data/processed/exp12a_fill_realism.md`,
`data/processed/exp12a_fill_summary.csv`,
`data/processed/exp12a_markout_samples.csv`,
`figures/exp12a_fill_prob_vs_distance.png`,
`figures/exp12a_markout_by_market.png`.

**Findings (PROVISIONAL pending regime-sliced markout analysis):**
- **All 8 LP-edge markets show negative 5min net markout.** The cross-
  venue LP "edge" is largely adverse-selection-paid spread, not free
  money. Exclusive-fill figures from EXP-3a/3b/3c overstate realized
  edge by ~1–2c/contract of markout plus a fill-probability haircut.
- **Survivor count:** 1 REAL_EDGE / 2 MARGINAL / 3 ADVERSE-SELECTED /
  2 SUB-FILL.
  - **REAL_EDGE:** `co_aesp` only — gross +2.67c survives −1.67c markout
    to +0.34c/contract adjusted, but **provisional**: only 4 genuine fill
    events in the window (book crossed 4.3% of the time per EXP-3c).
  - **MARGINAL:** `pe_rpal`, `kelce` — positive central adjusted edge but
    below the 0.05c/contract floor.
  - **ADVERSE-SELECTED:** `la_kbas` (most adverse: −1.98c net markout
    eats +1.70c gross), `co_pval`, `nyk` (maker-fee-bind: gross −0.39c).
  - **SUB-FILL:** `arod`, `kr_oseh` — P(both legs fill @5min) < 5%.
- Fill model: logistic on `distance_c, queue_ahead, imbalance, vol_c,
  days_to_cat`; `distance_c` dominates (|coef|≈1.4–1.6). P(fill) is an
  upper bound (queue-depletion proxy over-counts at-touch fills).

**Markout is unconditional** — not yet sliced by crossed/uncrossed regime,
time-of-day, or catalyst proximity. A regime-sliced re-run (especially
for `co_aesp`, which is crossed only 4.3% of the time) is the next
disciplining step before treating any REAL_EDGE as actionable.

**Lean-relevant update:** the LP thesis (EXP-12) survives only
provisionally on one market with the widest gross edge; adverse selection
is the default, not the exception. The honest LP headline is now: *flow-
contingent provideable spread exists at the maker margin, but realized
edge after fill probability and markout is near-zero or negative on 7/8
markets.*

**Tests:** 79/79 green (51 prior + 28 new in `tests/test_fills.py`).

### EXP-12a-regime — regime-sliced markout (2026-05-28)
Follow-on to EXP-12a: slice the 5min net markout by regime to test
whether adverse selection is *conditional* — i.e. whether any market
has an hour, catalyst window, or volatility state where net markout turns
non-negative with enough fills to trust (≥20 genuine fills per leg).

Script: `scripts/exp12a_regime.py`. Output:
`data/processed/exp12a_regime.md`. Reuses `fills.py` markout primitives
and EXP-12a window loaders; does not change the unconditional verdicts.

**Findings:**
- **0/8 markets have a tradeable regime.** Across 24 UTC hour bins +
  low/high volatility splits with ≥20 fills per leg, **zero** show
  non-negative net 5min markout. The conditional-LP hypothesis fails
  on current data: adverse selection is **unconditional** within the
  daemon window, not concentrated in avoidable hours or vol states.
- **Hour-of-day slice underpowered:** no market clears ≥20 fills on
  both legs in any single hour bin (fills too sparse across 24 bins on
  one UTC date).
- **Volatility slice:** only `co_pval` (96/25 high-vol, −0.633c) and
  `kr_oseh` (79/25 high-vol, −0.785c) clear the fill floor; both firmly
  negative. Where high-vol markout is evaluable, it is adverse.
- **Catalyst proximity slice degenerate:** 0 fills within 2h of any
  catalyst. Nearest events (Colombia 1st round 2026-05-31, Seoul
  2026-06-03) are ≥2.5 days after the May 28 daemon window. Note:
  `markets.yaml` `resolution_date` is year-offset (2027/2028); real
  F.1 event dates used for slicing.

**Thesis A (LP) — CLOSED** pending only near-catalyst data. Unconditional
EXP-12a + regime slice together: cross-venue LP edge is adverse-selection-
paid spread on 8/8 markets in all evaluable regimes. The lone EXP-12a
REAL_EDGE (`co_aesp`) is not rescued by any regime. **The only remaining
open question is near-catalyst LP behavior**, which requires the F.1
dense captures (May 31 Colombia, June 3 Seoul) — not yet folded in.
Until then, Thesis A is closed as "no actionable LP edge on current
evidence." Forward thesis is **EXP-4 (latency / lead-lag)** only.

**Tests:** 79/79 green; read-only analysis script only.

---

## Build EXP-4b-symmetric — Authenticated Kalshi WS + symmetric capture (2026-06-01)
**Goal:** Add a genuine authenticated Kalshi WEBSOCKET path for sub-second
cross-venue lead-lag capture, while keeping the existing 1.5s REST poll as
automatic degradation. Validate against PROD read-only credentials before
NBA Finals G1 deploy (Wed Jun 3).

**Implementation:**
- `scripts/ws_leadlag.py`: hand-rolled RSA-PSS SHA256 signing (Kalshi docs
  `sign_pss_text`; `kalshi-python` SDK not used — broken import in venv,
  WS client fights our asyncio reconnect/heartbeat pattern). Authenticated
  `orderbook_delta` on `wss://external-api-ws.kalshi.com/trade-api/ws/v2`.
  Local book state from snapshot + deltas; best_bid/best_ask reconstruction
  reuses `normalize_kalshi_orderbook` complementarity (bid-only → both sides).
  WS-first via `kalshi_capture_task`; auto-degrades to `REST_POLL` on auth
  rejection or repeated connect failure. Fresh re-auth headers on every
  reconnect. `--calibrate` writes network-latency differential report.
  Env-aware creds: `KALSHI_PROD_*` / `KALSHI_DEMO_*` with generic fallback;
  inline key material supported (not just file path).
- `tests/test_ws_leadlag.py`: +17 unit tests (book delta application,
  complementarity reconstruction, signing, credential loading).
- `data/processed/network_latency_calibration.md`: RTT sample from this host.

**Validation (PROD read-only, not yet deployed live):**
- Kalshi WS authenticates; `mode=WEBSOCKET` in STATUS; snapshot + deltas
  across 8 markets; tz-aware timestamps; exchange_ts on deltas.
- **WS book vs REST book:** MATCH on all sampled markets through a live
  `co_aesp` price move (0.75/0.76 → 0.76/0.79) — delta-application logic
  verified against reality, not just unit tests.
- Kalshi WS `--test-reconnect`: re-auth + re-subscribe + resume (0.59s gap);
  Polymarket path unaffected.
- Forced bad-auth: HTTP 401 → `MODE_DEGRADE` → `REST_POLL`, no crash.
- Polymarket WS path, heartbeat, append-only flush, graceful SIGINT unchanged.

**Findings (PROVISIONAL until Wednesday's NBA Finals G1 capture):**
- **Network differential (this host, 2026-06-01):** Kalshi RTT ~19.7 ms
  median / 33.8 ms p90; Polymarket ~95.0 ms / 109.9 ms. Kalshi edge is
  **~38 ms one-way closer** (RTT differential −75 ms → one-way −37.7 ms).
- **Resolution floor for lead-lag claims:** sub-~100 ms apparent leads on
  the local-receive clock are **network skew, not information flow** —
  must subtract the ~38 ms one-way differential (plus PM p90 jitter ~110 ms)
  before attributing venue A leading venue B. EXP-4/F.2 analysis must use
  both this calibration and the exchange-timestamp cross-check.

**Deploy target:** NBA Finals G1, Wed Jun 3 — symmetric WS capture ready;
F.1 REST remains capture of record until clock-sync cross-check passes.

**Tests:** 114/114 green (97 prior + 17 new).


## Reconciliation — fig_a3 bottom-panel bars vs $/contract annotation (2026-06-08T04:30:16Z)

Read-only probe (`batch_counterfactual/arms/_recon_fig_a3.py`) of the flagship NYK first-clearance episode. Verifies whether the bottom-panel per-contract ¢ bars reconcile with the annotated size-weighted $ / executable-contract figure.

```
==============================================================================
fig_a3 RECONCILIATION — flagship NYK first-clearance episode
==============================================================================
  episode_id = nba_finals_nyk#0000
  start_ts   = 2026-05-28 04:01:57.339434+00:00
  duration   = 15.15 h / 1787 cycles
  pm_fee_category = sports
  top-of-book: Kalshi bid/ask = 0.300/0.310   Polymarket bid/ask = 0.284/0.285
  ladder levels in band (both venues): 13

------------------------------------------------------------------------------
(a) TOTAL EXECUTABLE CONTRACTS at the clearing price (sized clear, max_volume)
    = ClearingResult.total_qty = min(participating demand, supply) at p_clear
------------------------------------------------------------------------------
    gross              contracts=  132,291.89   clear_px=0.29   n_fills=7
    retail             contracts=        0.00   clear_px=None   n_fills=0
    retail_pm_rebate   contracts=        0.00   clear_px=None   n_fills=0
    institutional      contracts=  132,253.44   clear_px=0.289   n_fills=6

------------------------------------------------------------------------------
(b) THE $ TOTAL PRICE-IMPROVEMENT FIGURE (the annotation; '$468' = gross tier)
------------------------------------------------------------------------------
    gross-tier agg_pi (annotated $) = $468.14
    Source: ClearingResult.agg_pi from auction._allocate, in DOLLARS (price units).
    Exact formula — summed over BOTH legs, over ALL filled contracts:
        agg_pi = Σ_{filled buys}  (limit_i − p_eff_i) · qty_i
               + Σ_{filled sells} (p_eff_i − limit_i) · qty_i
      where p_eff includes the per-leg fee (fee=0 at the gross/ZERO tier),
      limit_i is each RESTING ladder order's own quote (NOT a single touch),
      and the sum runs across EVERY filled level on BOTH venues — i.e. it is
      size-weighted over the whole crossing band, both legs, not one leg and
      not (clearing_price − single resting touch).
    Implied size-weighted avg total PI = agg_pi/contracts = 0.3539 ¢/contract (both legs combined).

------------------------------------------------------------------------------
(c) THE PER-CONTRACT ¢ BAR HEIGHTS (bottom-panel bars)
------------------------------------------------------------------------------
    Source: clearance_bounds(...).pi_kalshi_c / .pi_polymarket_c.
    Definition: TOP-OF-BOOK / MARGINAL per-contract PI of EACH SIDE at the
    midpoint of the price-only feasible interval, using ONLY the best quotes:
        midpoint m = mid(feasible_range)
        pi_kalshi_c     = (k_best_bid − buy_cost(m, kalshi)) · 100        [buy_k_… side]
                       or (sell_proceeds(m, kalshi) − k_best_ask) · 100
        pi_polymarket_c = (sell_proceeds(m, pm) − p_best_ask) · 100        [resp.]
                       or (p_best_bid − buy_cost(m, pm)) · 100
    => single-contract PI at the TOUCH; NOT size-weighted, NOT averaged over fills.
    gross              pi_kalshi=0.7000¢  pi_polymarket=0.8000¢  (sum=1.5000¢)  bounds_clear_px=0.293
    retail             pi_kalshi=0.0000¢  pi_polymarket=0.0000¢  (sum=0.0000¢)  bounds_clear_px=None
    retail_pm_rebate   pi_kalshi=0.0000¢  pi_polymarket=0.0000¢  (sum=0.0000¢)  bounds_clear_px=None
    institutional      pi_kalshi=0.6121¢  pi_polymarket=0.7121¢  (sum=1.3242¢)  bounds_clear_px=0.293

------------------------------------------------------------------------------
ASSERTION  bar_height_cents * contracts / 100 == annotated_dollars  (per tier, both sides)
------------------------------------------------------------------------------
    gross          kalshi     bar= 0.7000¢ *     132,292 /100 = $      926.04  vs annotated $    468.14   FAIL  (lhs/rhs= 1.978)
    gross          polymarket bar= 0.8000¢ *     132,292 /100 = $    1,058.34  vs annotated $    468.14   FAIL  (lhs/rhs= 2.261)
    retail             not clearable (no bars / no annotation) — skipped
    retail_pm_rebate   not clearable (no bars / no annotation) — skipped
    institutional  kalshi     bar= 0.6121¢ *     132,253 /100 = $      809.52  vs annotated $    238.80   FAIL  (lhs/rhs= 3.390)
    institutional  polymarket bar= 0.7121¢ *     132,253 /100 = $      941.78  vs annotated $    238.80   FAIL  (lhs/rhs= 3.944)

  RESULT: ASSERTION FAILS

  Cross-check with BOTH sides summed (pi_k+pi_p), still vs the same annotation:
    gross          (pi_k+pi_p)=1.5000¢ -> $    1,984.38 vs $    468.14  (lhs/rhs= 4.239)
    institutional  (pi_k+pi_p)=1.3242¢ -> $    1,751.30 vs $    238.80  (lhs/rhs= 7.334)

------------------------------------------------------------------------------
DIAGNOSIS — what the bars actually represent
------------------------------------------------------------------------------
  The assertion FAILS by construction: the two quantities are not the same metric.
  * BARS  = TOP-OF-BOOK MARGINAL per-contract PI of ONE side at the best-quote
            midpoint (clearance_bounds, price-only; the panel has no sizes).
  * ANNOTATION = SIZE-WEIGHTED TOTAL agg_pi summed over BOTH legs across every
            filled level of the FULL extracted ladder (auction.clear, max_volume).
  Three independent reasons they cannot reconcile, even after unit conversion:
    1. one leg (bar) vs both legs (agg_pi);
    2. touch-only marginal PI (bar) vs depth-averaged PI over the whole band
       (deeper ladder levels earn far less PI, diluting agg_pi/contract well
       below the top-of-book value);
    3. the clearing price itself differs — clearance_bounds midpoint uses only
       the best quotes, while clear() prices the full crossing band.
  bar_height_cents * contracts / 100 therefore OVERSTATES agg_pi (lhs/rhs > 1):
  it applies a touch-level per-contract edge to the entire size-weighted volume.
  The bars are a PER-CONTRACT (top-of-book) statistic; the annotation is an
  AGGREGATE (size-weighted, both-legs) statistic. They share an episode, not a
  formula, and should be labelled as distinct axes — not multiplied together.
```


## fig_a3 bottom panel — per-tier TOTAL price improvement (2026-06-08T04:40:36Z)

Regenerated ONLY fig_a3 (frozen set + other figures untouched). The bottom panel now plots ClearingResult.agg_pi (both legs, depth-integrated) from the SAME clear() / max_volume call that produces the headline numbers, replacing the prior per-side per-contract clearance_bounds bars. Per-tier table:

```
fig_a3 bottom panel regenerated: per-tier TOTAL price improvement (clear, max_volume)
flagship NYK#0000  15.15h  single uniform-price call on full extracted ladders
tier                   agg_pi ($)      total_qty   agg_pi/total_qty (¢)
-----------------------------------------------------------------------
gross                      468.14     132,291.89                 0.3539
retail                       0.00           0.00    n/a (not clearable)
retail_pm_rebate             0.00           0.00    n/a (not clearable)
institutional              238.80     132,253.44                 0.1806
```
