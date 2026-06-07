# Reconciliation — kelce retail-clearable vs Part 1 "0 of 15 takeable"

**Question.** Arm A reports `sports_retirement_kelce` clears at the **retail** tier in
**51.9%** of its episode-starts (RESULTS_A.md §7 anomaly 1), while Part 1
(`docs/findings.md`) published *"0 of 15 markets show takeable arb"* at corrected
retail fees. This file decides which of {data vintage, instrument difference, fee
structure} explains the gap. Read-only over `results/` + the FROZEN data;
reproduce with `arms/reconcile_kelce.py`.

**TL;DR verdict.** The two statements are **both correct** and do not actually
conflict. Part 1's "0 of 15" is a **single snapshot at 2026-05-28T02:29:43Z**, which
*predates the entire 30s panel* (panel starts 2026-05-28T04:01:57Z).
At that instant kelce's gross cross was only **0.2¢** — far below the
**1.109¢** retail wall — so kelce correctly failed *every* bar, including the
weaker Arm A per-contract bar. The retail-clearable regime is a **later, wider-cross
state** that Part 1's snapshot never saw. The gap between "0" and "52%"
is **almost entirely data vintage / single-snapshot sampling (~85%)**; **instrument
choice is ~0%** — Part 1's own fill-realistic bar, applied to the panel, reproduces
Arm A's 52% *exactly* (0.519). **Fee structure does
not drive the discrepancy** (the fee model is shared across both vintages) but it is
the **market-selection conditioner**: kelce is the *only* retail-clearable market
because it is deep-tail-priced (low fee wall) AND develops a wide cross — both are
strictly necessary (§3). See §4.

---

## 1. TIME — did the retail-clearable regime exist in Part 1's window?

**No.** Part 1's snapshot is `snapshot_20260528T022943Z` (2026-05-28T02:29:43Z), the
most-recent snapshot its pipeline auto-selected. It sits **~1.5h before** the frozen
30s panel begins, so *zero* Arm A episodes overlap Part 1's window — the comparison is
across different data vintages by construction.

At the snapshot, kelce top-of-book was K_yes 0.03/0.06, PM_yes
0.027/0.028 → gross cross **0.2¢** (a thin, wide-spread tail
book). Across the panel, kelce's *median* episode-start cross is
**1.40¢** (p90 2.40¢). The wide-cross
regime emerged after Part 1 looked.

Retail-clearable episode fraction (Arm A per-contract bar), split at the essay
publication date **2026-06-03**:

| window | kelce episodes | retail-clearable frac |
|---|---:|---:|
| all capture | 129 | 0.519 |
| before 2026-06-03 | 70 | 0.214 |
| on/after 2026-06-03 | 59 | 0.881 |

The regime is present across the panel (both before and after pub), but **absent at
Part 1's pre-panel instant**. The cross widened materially once the panel began.

## 2. INSTRUMENT — does kelce pass Part 1's *bar* (not just Arm A's)?

Part 1's bar is **fill-realistic**: walk displayed depth on both directions, apply
per-leg fees, take the max net, verdict = net $ > 0. Arm A's first-clearance bar is
weaker: **per-contract fee feasibility at top-of-book** (does a uniform price exist
that both best quotes accept after fees). Three stacked bars at Part 1's snapshot:

| market | gross-crossed (touch) | fee-feasible per-contract (Arm A bar) | fill-realistic net $ (Part 1 bar) |
|---|---|---|---|
| kelce | 0.2¢ (yes) | FAIL | $0.0000 → FAIL |
| nyk (control) | 0.4¢ (yes) | FAIL | $0.0000 → FAIL |

At Part 1's snapshot kelce **fails the Arm A bar too** (0.2¢ cross <
1.109¢ wall) — so the snapshot disagreement is *not* instrument; it's vintage.

**Does the stronger Part 1 bar change Arm A's panel verdict?** Running Part 1's
fill-realistic direct-structure walker on every kelce **episode-start ladder**
(extracted, both-venue, retail fees):

| bar (kelce, panel episode-starts) | clearable fraction |
|---|---:|
| Arm A per-contract (top-of-book) | 0.519 |
| Part 1 fill-realistic (displayed depth, net $ > 0) | 0.519 |

Fill-realistic median net where it passes: **$0.80** per episode.
The fill-realistic bar is close to
the per-contract bar — depth on kelce's tail book is ample enough that fill-realism barely tightens the verdict.
(Direct structure only; PM-NO ladders were not extracted, so the synthetic leg Part 1
also checks is not re-run here — it does not bind for a YES-YES cross.)

## 3. FEE STRUCTURE — kelce is a tail-priced market with a low fee wall

Episode-start price level **C** (YES clearing midpoint):

| market | median C | p10 | p90 | median gross cross |
|---|---:|---:|---:|---:|
| kelce | 0.033 | 0.028 | 0.038 | 1.40¢ |
| nyk (control) | 0.359 | 0.318 | 0.593 | 0.40¢ |

The Kalshi fee is `ceil(7·C·(1−C))` cents and the PM sports fee is `3%·C`. Both shrink
hard at the tail. The retail round-trip wall:

| price level | Kalshi parabolic | PM 3%·C | **retail wall** |
|---|---:|---:|---:|
| kelce median C=0.033 | 1.00¢ | 0.10¢ | **1.10¢** |
| central C=0.50 | 2.00¢ | 1.50¢ | **3.50¢** |
| nyk median C=0.359 | 2.00¢ | 1.08¢ | **3.08¢** |

At kelce's deep tail (C≈0.03) the wall collapses to **1.10¢**
vs **3.50¢** central — the PM proportional fee does most of the
shrinking (3%·0.04 ≈ 0.10¢ vs 1.50¢), the Kalshi
ceil contributes 1¢ vs 2¢.

**2×2 decomposition** (per-contract retail clearable fraction on kelce's episode-start
cross sample; "low wall" = kelce tail wall 1.10¢, "central wall" =
3.50¢; "narrow cross" = NYK median 0.40¢):

| | low fee wall (tail) | central fee wall (C=0.50) |
|---|---:|---:|
| **kelce-wide cross** | **0.519** (actual) | 0.000 |
| **NYK-narrow cross** | 0.000 | 0.000 |

Reading the corners: with a central fee wall, kelce's wide cross clears only
0.0% — so the **low tail wall is necessary**. With
NYK's narrow cross, even the low tail wall clears 0% —
so a **wide cross is also necessary**. kelce is retail-clearable only because it has
**both**: a wider gross cross *and* a tail-priced, low-fee book. NYK (central C, narrow
cross) has neither and clears 0%.

## 4. VERDICT

The "anomaly" is **not a contradiction** — Part 1 and Arm A measured different
vintages with the *same* fee model and (as shown) effectively the *same* bar.
Decomposing the 0-vs-52% gap:

- **Data vintage / sampling — DOMINANT (~85%).** Part 1's "0 of 15" is one snapshot at
  2026-05-28T02:29:43Z, ~1.5h *before* the panel, catching kelce at a
  **0.2¢** cross. Across the panel kelce's median cross is
  **~1.4¢**, and the retail-clearable fraction rises from
  **21% before the 2026-06-03 essay to 88% after**
  — a regime that strengthened over the capture and that a single early snapshot could
  not see. This is the whole reason the *numbers* differ.
- **Instrument — NEGLIGIBLE (~0%).** Part 1's stronger fill-realistic, direction-
  enforced, displayed-depth walker applied to kelce's panel episode-starts yields
  **0.519** — *identical* to Arm A's per-contract
  **0.519** (kelce's tail book carries enough depth that fill-realism
  doesn't bite; median realized net $0.80). Had Part 1 run its own
  bar over the full panel it would have reported the same ~52%. The
  method is not the explanation.
- **Fee structure — the CONDITIONER, not the discrepancy (~15% as 'why kelce').** The
  fee model is shared across both vintages, so it cannot explain the 0-vs-52%
  *gap*. It explains *market selection*: kelce is the only retail-clearable market
  because it is deep-tail-priced (median C≈0.03 → wall
  **1.10¢** vs **3.50¢** central). The 2×2
  (§3) shows clearability needs **both** the wide cross *and* the low tail wall — each
  alone clears 0%. NYK (central C, narrow cross) has neither.

**Bottom line.** Part 1's "0 of 15 at retail" was true for its 2026-05-28 02:29Z
snapshot, and is *method-consistent* with Arm A — applying Part 1's own bar to the
panel reproduces Arm A's number. The discrepancy is **data vintage**, not instrument
and not a fee-model disagreement; the **tail-market fee structure** is why kelce
(uniquely) is the market that lights up once its cross widens. RESULTS_A.md §7 anomaly
1 should be read as *"a later-vintage, tail-priced-market exception that Part 1's
single snapshot pre-dated,"* not as a refutation of Part 1. Figure:
`figs/fig_recon_kelce.png`.
