# EXP-3a Direction Correction (Scenarios C & D)

**Snapshot:** `snapshot_20260528T022943Z`  
**Scope:** the 7 D-flips and 1 C-flip from `data/processed/exp3a_fee_correction.md` (8 (market, scenario) pairs).

## The bug being fixed

The original Scenarios C (mixed) and D (both-maker) applied the `execution_mode='maker'` fee on a venue regardless of which side of the cross the trade had to hit. That's incoherent: on a crossed book, the take-take execution lifts BOTH inside quotes — both legs are *taker*. Maker pricing is only available on the side where the strategy ADDS liquidity (posts a passive order, waits for incoming flow). The original walker also reported a dollar figure tied to the resting depth on the venue's book — but as a maker you can't fill against resting depth at maker rates; you only fill when incoming flow crosses your post.

## Direction-enforced verdict tiers

* **TAKEABLE** — per-contract edge > 0 AND both legs cross-side (taker on both venues). Instant lock-in; dollar figure is (per-contract edge) × min(top-of-book size on each leg).
* **provideable, fill-unconfirmed** — per-contract edge > 0 BUT at least one leg is add-side (maker). Edge is real *if filled*; size depends on incoming taker flow lifting the posted order, not on the resting depth on the opposite side.
* **$0 (fees-bind)** — per-contract edge ≤ 0 even with the scenario's most favorable fee assumption.

## Per-market diff

| market | scen | direction | leg roles (buy / sell) | old $ (dir-blind) | new edge/ct (dir-enforced) | new verdict | why |
|---|---|---|---|---|---|---|---|
| `sports_retirement_arod` | C_MIXED_DIR | BUY kalshi @ 0.0400 (size 695) | SELL polymarket @ 0.0510 (size 60) | kalshi@0.0400 (cross-side (taker)) / polymarket@0.0510 (add-side (maker)) | $0.06 | +0.138c | provideable, fill-unconfirmed | 1 maker leg — fill is flow-contingent |
| `sports_retirement_arod` | D_BOTH_MAKER_DIR | BUY kalshi @ 0.0400 (size 695) | SELL polymarket @ 0.0510 (size 60) | kalshi@0.0400 (add-side (maker)) / polymarket@0.0510 (add-side (maker)) | $2.98 | +1.138c | provideable, fill-unconfirmed | 2 maker legs — fill is flow-contingent |
| `sports_retirement_kelce` | D_BOTH_MAKER_DIR | BUY polymarket @ 0.0280 (size 200) | SELL kalshi @ 0.0300 (size 250) | polymarket@0.0280 (add-side (maker)) / kalshi@0.0300 (add-side (maker)) | $0.45 | +0.221c | provideable, fill-unconfirmed | 2 maker legs — fill is flow-contingent |
| `intl_president_co_aesp` | D_BOTH_MAKER_DIR | BUY polymarket @ 0.6700 (size 2723) | SELL kalshi @ 0.6900 (size 1328) | polymarket@0.6700 (add-side (maker)) / kalshi@0.6900 (add-side (maker)) | $30.23 | +2.670c | provideable, fill-unconfirmed | 2 maker legs — fill is flow-contingent |
| `intl_president_co_pval` | D_BOTH_MAKER_DIR | BUY polymarket @ 0.0170 (size 251) | SELL kalshi @ 0.0200 (size 81) | polymarket@0.0170 (add-side (maker)) / kalshi@0.0200 (add-side (maker)) | $0.43 | +0.317c | provideable, fill-unconfirmed | 2 maker legs — fill is flow-contingent |
| `intl_president_pe_rpal` | D_BOTH_MAKER_DIR | BUY polymarket @ 0.2710 (size 3225) | SELL kalshi @ 0.2800 (size 10200) | polymarket@0.2710 (add-side (maker)) / kalshi@0.2800 (add-side (maker)) | $50.59 | +1.171c | provideable, fill-unconfirmed | 2 maker legs — fill is flow-contingent |
| `intl_mayor_kr_oseh` | D_BOTH_MAKER_DIR | BUY kalshi @ 0.1800 (size 500) | SELL polymarket @ 0.1900 (size 1283) | kalshi@0.1800 (add-side (maker)) / polymarket@0.1900 (add-side (maker)) | $5.00 | +1.190c | provideable, fill-unconfirmed | 2 maker legs — fill is flow-contingent |
| `us_mayor_la_kbas` | D_BOTH_MAKER_DIR | BUY kalshi @ 0.6900 (size 26314) | SELL polymarket @ 0.7000 (size 295) | kalshi@0.6900 (add-side (maker)) / polymarket@0.7000 (add-side (maker)) | $2.95 | +1.700c | provideable, fill-unconfirmed | 2 maker legs — fill is flow-contingent |

## Summary

Of 8 flipped (market, scenario) pairs from the original C/D analysis:

* **TAKEABLE under direction-enforced model: 0.**
* Provideable, fill-unconfirmed: 8.
* $0 under fees: 0.

**None of the 8 original flips survive as genuinely takeable.** Every C/D scenario that produced a positive headline number required the strategy to be add-side (maker) on at least one venue. That doesn't make the per-contract edges fake — the fee improvement from maker mode is real (PM 4% → 0%; Kalshi 1c parabolic → 0c for quadratic markets / 25% × 1c for quadratic_with_maker_fees) — but extracting it requires POSTING passive and getting filled by incoming flow, not lifting resting depth. The honest count of true cross-venue arbitrage opportunities on the D.2 snapshot remains **0 of 15** (matches Scenario B, corrected taker).

## Why the per-contract edges still matter

The provideable-class markets quantify what an LP strategy could earn IF they could attract incoming flow to lift their post. For example: a strategy that posts a passive ASK on Polymarket at ARod's inside quote (0.051) and dynamically hedges by lifting Kalshi's YES ask (0.04) on fill, earns ~0.1c/contract gross before considering rebate. That's the *liquidity-provision* edge the project has been gesturing at — small per-contract, accessible only at the maker margin, and conditional on the strategy being able to source incoming flow on its posted side. The headline dollar figures from the direction-blind D scenario ($30.23 Colombia AESP, $50.59 Peru RPAL, etc.) over-stated this by pretending the LP could ALSO sweep the contra-venue's resting depth as a maker — that's a category error, not a realistic execution path.

## Notes on Peru specifically

The $50.59 Peru figure had two compounding errors:
1. The depth (3225 contracts at PM YES ASK 0.271) was real and persistent within the snapshot's regime (`data/processed/exp3a_peru_depth_check.md`, 100% large-level presence in early window). The 14:00Z price regime shift subsequently dissolved that level.
2. Even with the depth real, Scenario D modeled buying that PM ask as a maker fill (0% fee). Buying PM means *lifting* the ask — that's TAKER (4%), not maker. The maker-eligible alternative is *posting* a bid on PM at 0.27+, waiting for sell flow. With the regime shift, that posted bid would now be above the new consensus (0.22) and immediately be lifted by sellers at a loss.

Both corrections kill the $50.59 number independently.
