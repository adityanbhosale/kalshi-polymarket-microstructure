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
