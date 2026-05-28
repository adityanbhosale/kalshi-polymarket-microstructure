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
2. Depth binds before fees. sports_retirement_arod paper edge (+5.85c)
   CLEARS the ~3c fee threshold — the first such market in the project —
   yet executable arb is still $0 because Polymarket YES has $0 depth
   within 1c. In thin tail markets the binding constraint is depth, not
   the 2% taker fee. (More Lean-relevant than the fee story: depth-aware
   execution is what a terminal provides.)
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
