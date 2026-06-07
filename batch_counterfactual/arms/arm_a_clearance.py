"""Arm A — episode detection + counterfactual first-clearance (Phase 3).

Walks the FROZEN 30s panel per INCLUDED pair, collapses contiguous GROSS-crossed
cycles into episodes (decision #2), and runs the price-only first-clearance
(auction.clearance_bounds) at each episode's first cycle under every fee tier.

Episode semantics (decision #2 + decision Q2=A, 2026-06-06):
  * begins at the first cycle where the pair is crossed gross (cross_size > 0);
  * extends through CONTIGUOUS crossed cycles; a daemon gap of <= EPISODE_GAP_MAX_S
    (600s) within a crossed run is BRIDGED (the unobserved interval is assumed
    continuously crossed — bridging assumption), decoupled from book.py's 90s
    staleness bound (which is unchanged);
  * ENDS on an OBSERVED uncross / one-sided (None) leg, a gap > EPISODE_GAP_MAX_S,
    or market termination;
  * episodes that bridge any gap (intra-episode delta > 90s book staleness) carry
    gap_adjacent=True and a bridged_gap_seconds tally. The 10.1h outage is excluded
    from the grid.

ASSUMPTION-1 (tie-break) and ASSUMPTION-2 (pro-rata rationing) live in auction.py
and are inherited unchanged; first-clearance here is price-only (per-contract),
so ASSUMPTION-2 does not bind until arm_a_sized.py.

Mechanical-counterfactual caveat: this asks "could a single uniform-price call at
the episode's first crossed quote have cleared, and at what per-contract price
improvement" holding the observed book FIXED (flow-fixed). It does NOT model how
order flow would have responded to the auction. Per-contract only — no quantities
are invented from the panel.

Outputs (results/arm_a/): episodes.parquet (one row per episode x tier),
episodes_summary.csv, stats.json.

Run:
    uv run python batch_counterfactual/arms/arm_a_clearance.py
"""

from __future__ import annotations

import json
import statistics
from decimal import Decimal

import pandas as pd

from _common import (
    BRIDGE_GAP_MIN_S,
    BUCKET_LABELS,
    EPISODE_GAP_MAX_S,
    FEE_CATEGORY,
    INCLUDED_PAIRS,
    RESULTS,
    SENSITIVITY_TOLS,
    compute_inclusion,
    duration_bucket,
    global_cycle_grid,
)
from auction import clearance_bounds
from book import Panel
from fees import Tier

TIERS: list[tuple[str, Tier]] = [
    ("gross", Tier.ZERO),               # ZERO tier == pre-fee gross view
    ("retail", Tier.RETAIL),
    ("retail_pm_rebate", Tier.RETAIL_PM_REBATE),
    ("institutional", Tier.INSTITUTIONAL),
]


def _paired_good(panel: Panel, pair: str) -> dict[pd.Timestamp, tuple[float, float, float, float]]:
    """ts -> (k_bid, k_ask, p_bid, p_ask) for cycles where BOTH legs two-sided."""
    k = panel._leg("kalshi", pair).rename(columns={"best_bid": "kb", "best_ask": "ka"})
    p = panel._leg("polymarket", pair).rename(columns={"best_bid": "pb", "best_ask": "pa"})
    m = k.merge(p, on="ts", how="inner")
    return {
        row.ts: (float(row.kb), float(row.ka), float(row.pb), float(row.pa))
        for row in m.itertuples(index=False)
    }


def _gross_cross_c(vals: tuple[float, float, float, float]) -> float:
    kb, ka, pb, pa = vals
    cross = max(kb - pa, pb - ka)
    return round(cross * 100.0, 4)


def _crossed_arrays(panel: Panel, pair: str, gts: list[pd.Timestamp]):
    """Per-grid-position crossed flag + gross cross (cents) for one pair."""
    good = _paired_good(panel, pair)
    crossed = [False] * len(gts)
    cross_c: list[float | None] = [None] * len(gts)
    for idx, t in enumerate(gts):
        v = good.get(t)
        if v is None:
            continue
        c = _gross_cross_c(v)
        if c > 0:
            crossed[idx] = True
            cross_c[idx] = c
    return crossed, cross_c


def detect_episodes(
    panel: Panel,
    pair: str,
    grid: pd.DatetimeIndex,
    *,
    gap_max_s: float = EPISODE_GAP_MAX_S,
) -> list[dict]:
    """Contiguous gross-crossed episodes for one pair over the global grid.

    Bridging (decision Q2=A): a daemon gap of <= ``gap_max_s`` within a crossed
    run is BRIDGED (assumed continuously crossed); an OBSERVED uncross/one-sided
    cycle, or a gap > ``gap_max_s``, ends the episode. Intra-episode deltas above
    BRIDGE_GAP_MIN_S (book staleness, 90s) are tallied as bridged gaps.
    """
    n = len(grid)
    gts = list(grid)
    crossed, cross_c = _crossed_arrays(panel, pair, gts)
    deltas = [None] + [(gts[i] - gts[i - 1]).total_seconds() for i in range(1, n)]

    episodes: list[dict] = []
    i = 0
    eid = 0
    while i < n:
        if not crossed[i]:
            i += 1
            continue
        j = i
        bridged_gap_s = 0.0
        n_bridged = 0
        while j + 1 < n and crossed[j + 1] and deltas[j + 1] <= gap_max_s:
            if deltas[j + 1] > BRIDGE_GAP_MIN_S:
                bridged_gap_s += deltas[j + 1]
                n_bridged += 1
            j += 1
        start_after_gap = i > 0 and deltas[i] is not None and deltas[i] > BRIDGE_GAP_MIN_S
        end_before_gap = j < n - 1 and deltas[j + 1] is not None and deltas[j + 1] > BRIDGE_GAP_MIN_S
        vals_c = [cross_c[k] for k in range(i, j + 1) if cross_c[k] is not None]
        dur = (gts[j] - gts[i]).total_seconds()
        episodes.append({
            "pair": pair,
            "episode_id": f"{pair}#{eid:04d}",
            "start_ts": gts[i],
            "end_ts": gts[j],
            "n_cycles": j - i + 1,
            "duration_s": dur,
            "duration_bucket": duration_bucket(dur),
            "max_gross_c": max(vals_c),
            "median_gross_c": float(statistics.median(vals_c)),
            "n_bridged_gaps": int(n_bridged),
            "bridged_gap_seconds": round(bridged_gap_s, 1),
            "start_after_gap": bool(start_after_gap),
            "end_before_gap": bool(end_before_gap),
            "gap_adjacent": bool(n_bridged > 0 or start_after_gap or end_before_gap),
        })
        eid += 1
        i = j + 1
    return episodes


def sensitivity_table(panel: Panel, grid: pd.DatetimeIndex) -> pd.DataFrame:
    """Episode count + longest-episode duration per pair across gap tolerances."""
    rows = []
    for pair in INCLUDED_PAIRS:
        row = {"pair": pair}
        for tol in SENSITIVITY_TOLS:
            eps = detect_episodes(panel, pair, grid, gap_max_s=tol)
            longest_h = (max(e["duration_s"] for e in eps) / 3600.0) if eps else 0.0
            row[f"n_episodes_{int(tol)}s"] = len(eps)
            row[f"longest_h_{int(tol)}s"] = round(longest_h, 2)
        rows.append(row)
    return pd.DataFrame(rows)


def first_clearance_rows(panel: Panel, ep: dict) -> list[dict]:
    """One row per tier: clearance_bounds at the episode's first cycle."""
    pair = ep["pair"]
    cat = FEE_CATEGORY[pair]
    pair_state = panel.paired_state(pair, ep["start_ts"])
    rows: list[dict] = []
    for tier_label, tier in TIERS:
        base = dict(ep)
        base["tier"] = tier_label
        base["pm_fee_category"] = cat
        if pair_state is None:
            # Should never happen at an episode start (crossed => paired); flag.
            base.update(clearable=None, feasible_lo=None, feasible_hi=None,
                        clearing_price=None, pi_kalshi_c=None, pi_polymarket_c=None,
                        gross_cross_c=None, direction=None,
                        not_clearable_reason="paired_state_none_BUG")
            rows.append(base)
            continue
        k_book, p_book = pair_state
        r = clearance_bounds(k_book, p_book, tier, category=cat)
        base.update(
            clearable=bool(r.clearable),
            feasible_lo=(float(r.feasible_range[0]) if r.feasible_range else None),
            feasible_hi=(float(r.feasible_range[1]) if r.feasible_range else None),
            clearing_price=(float(r.clearing_price) if r.clearing_price is not None else None),
            pi_kalshi_c=(float(r.pi_kalshi_c) if r.pi_kalshi_c is not None else None),
            pi_polymarket_c=(float(r.pi_polymarket_c) if r.pi_polymarket_c is not None else None),
            gross_cross_c=(float(r.gross_cross_c) if r.gross_cross_c is not None else None),
            direction=r.direction,
            not_clearable_reason=(r.not_clearable.reason if r.not_clearable else None),
        )
        rows.append(base)
    return rows


def _dist(values: list[float]) -> dict:
    if not values:
        return {"median": None, "p90": None, "max": None}
    s = sorted(values)
    p90 = s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))]
    return {"median": float(statistics.median(s)), "p90": float(p90), "max": float(max(s))}


TIER_LABELS = [t for t, _ in TIERS]


def _agg(sub: pd.DataFrame, label: str) -> dict:
    """Aggregate one slice of episodes (one row per episode)."""
    durs = sub["duration_s"].tolist()
    d = _dist(durs)
    crossed_min = sum(durs) / 60.0
    active_days = sub["start_day"].nunique() if ("start_day" in sub and len(sub)) else 0
    row = {
        "scope": label,
        "n_episodes": len(sub),
        "crossed_cycles": int(sub["n_cycles"].sum()) if len(sub) else 0,
        "dur_median_s": d["median"], "dur_p90_s": d["p90"], "dur_max_s": d["max"],
        "crossed_minutes": round(crossed_min, 2),
        "active_market_days": int(active_days),
        "crossed_min_per_market_day": (round(crossed_min / active_days, 2)
                                       if active_days else None),
        "gap_adjacent_episodes": int(sub["gap_adjacent"].sum()) if len(sub) else 0,
    }
    # duration-stratified episode counts + crossed-minutes
    for b in BUCKET_LABELS:
        bsub = sub[sub["duration_bucket"] == b] if len(sub) else sub
        row[f"n_episodes_{b}"] = len(bsub)
        row[f"crossed_min_{b}"] = round(bsub["duration_s"].sum() / 60.0, 2) if len(bsub) else 0.0
    # clearable fraction + median total per-contract PI by tier (overall)
    for t in TIER_LABELS:
        col = f"clearable_{t}"
        row[f"clearable_frac_{t}"] = (round(float(sub[col].mean()), 4)
                                      if (col in sub and len(sub)) else None)
        pcol = f"pi_total_{t}_c"
        if pcol in sub:
            vals = sub[pcol].dropna().tolist()
            row[f"median_pi_total_{t}_c"] = (round(statistics.median(vals), 4)
                                             if vals else None)
    return row


def build_summary(ep_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Per-pair + overall aggregates, plus a (scope x bucket x tier) clearable table.

    ``ep_df`` is one row per episode (deduped across tiers).
    """
    rows = [_agg(ep_df[ep_df["pair"] == p], p) for p in INCLUDED_PAIRS]
    rows.append(_agg(ep_df, "OVERALL"))
    summary = pd.DataFrame(rows)

    # Duration-stratified clearable fractions (decision Q1=A: stratify everywhere).
    strat_rows = []
    scopes = [(p, ep_df[ep_df["pair"] == p]) for p in INCLUDED_PAIRS] + [("OVERALL", ep_df)]
    for scope, sdf in scopes:
        for b in BUCKET_LABELS:
            bsub = sdf[sdf["duration_bucket"] == b] if len(sdf) else sdf
            r = {"scope": scope, "duration_bucket": b, "n_episodes": len(bsub)}
            for t in TIER_LABELS:
                col = f"clearable_{t}"
                r[f"clearable_frac_{t}"] = (round(float(bsub[col].mean()), 4)
                                            if (col in bsub and len(bsub)) else None)
            strat_rows.append(r)
    strat = pd.DataFrame(strat_rows)

    stats = {
        "n_pairs": len(INCLUDED_PAIRS),
        "n_episodes_total": int(len(ep_df)),
        "overall": rows[-1],
    }
    return summary, strat, stats


def main() -> int:
    panel = Panel()
    grid = global_cycle_grid(panel)

    # All episode-tier rows.
    tier_rows: list[dict] = []
    # One row per episode (clearance pivoted to columns) for the summary.
    ep_records: list[dict] = []

    for pair in INCLUDED_PAIRS:
        eps = detect_episodes(panel, pair, grid)
        for ep in eps:
            rows = first_clearance_rows(panel, ep)
            tier_rows.extend(rows)
            rec = dict(ep)
            rec["start_day"] = pd.Timestamp(ep["start_ts"]).strftime("%Y-%m-%d")
            by_tier = {r["tier"]: r for r in rows}
            for tlabel in (t for t, _ in TIERS):
                tr = by_tier.get(tlabel, {})
                rec[f"clearable_{tlabel}"] = tr.get("clearable")
                pk = tr.get("pi_kalshi_c"); pp = tr.get("pi_polymarket_c")
                rec[f"pi_total_{tlabel}_c"] = (
                    (pk + pp) if (pk is not None and pp is not None) else None
                )
            ep_records.append(rec)

    episodes_df = pd.DataFrame(tier_rows)
    ep_df = pd.DataFrame(ep_records)

    # ---- SANITY GATE (reframed, decision Q1=A): NYK's LONGEST episode is the
    #      flagship (~15h) and gross-clearable / retail-blocked / inst-clearable.
    #      Total episode count is NOT gated — the full population is the result. ----
    nyk = ep_df[ep_df["pair"] == "nba_finals_nyk"].sort_values("duration_s", ascending=False)
    gate = {"pair": "nba_finals_nyk", "n_episodes": int(len(nyk))}
    if len(nyk):
        longest = nyk.iloc[0]
        gate["longest_duration_h"] = round(longest["duration_s"] / 3600.0, 2)
        gate["longest_n_cycles"] = int(longest["n_cycles"])
        nyk_crossed, _ = _crossed_arrays(panel, "nba_finals_nyk", list(grid))
        nyk_good = _paired_good(panel, "nba_finals_nyk")
        nyk_present = sum(1 for t in grid if t in nyk_good)
        gate["crossed_cycle_fraction_pct"] = (round(100.0 * sum(nyk_crossed) / nyk_present, 1)
                                              if nyk_present else None)
        lr = episodes_df[episodes_df["episode_id"] == longest["episode_id"]]
        gate["longest_clearable"] = {r["tier"]: bool(r["clearable"]) for _, r in lr.iterrows()}

    lc = gate.get("longest_clearable", {})
    gate_pass = (len(nyk) >= 1
                 and gate.get("longest_duration_h", 0) >= 14.0
                 and lc.get("gross") is True
                 and lc.get("retail") is False
                 and lc.get("institutional") is True)

    print("=" * 72)
    print("ARM A — episode clearance")
    print("=" * 72)
    print(f"  included pairs : {len(INCLUDED_PAIRS)}")
    print(f"  total episodes : {len(ep_df)}  (episode-tier rows: {len(episodes_df)})")
    print(f"  NYK episodes   : {gate['n_episodes']}  (full-capture population)")
    print(f"  NYK LONGEST    : {gate.get('longest_duration_h')}h / "
          f"{gate.get('longest_n_cycles')} cycles  clearable={lc}")

    if not gate_pass:
        print("-" * 72)
        print("  *** SANITY GATE FAILED — NYK's LONGEST episode is not the flagship")
        print("      (>=14h, gross-clearable / retail-blocked / institutional-clearable).")
        print("      STOPPING before writing results.")
        (RESULTS / "GATE_FAILURE.json").write_text(json.dumps(gate, indent=2, default=str))
        return 2

    print("  [PASS] sanity gate: NYK longest episode = flagship, clearability correct.")
    print("-" * 72)

    # ---- write outputs ----
    summary, strat, stats = build_summary(ep_df)
    sens = sensitivity_table(panel, grid)
    stats["sanity_gate"] = gate
    stats["episode_gap_max_s"] = EPISODE_GAP_MAX_S
    stats["inclusion"] = compute_inclusion(panel).to_dict(orient="records")
    stats["sensitivity"] = sens.to_dict(orient="records")

    episodes_df.to_parquet(RESULTS / "episodes.parquet", index=False)
    summary.to_csv(RESULTS / "episodes_summary.csv", index=False)
    strat.to_csv(RESULTS / "clearable_by_bucket.csv", index=False)
    sens.to_csv(RESULTS / "sensitivity.csv", index=False)
    (RESULTS / "stats.json").write_text(json.dumps(stats, indent=2, default=str))

    ov = stats["overall"]
    print(f"  duration buckets (overall episodes): "
          + " ".join(f"{b}={ov['n_episodes_'+b]}" for b in BUCKET_LABELS))
    print(f"  clearable fraction — gross {ov['clearable_frac_gross']} | "
          f"retail {ov['clearable_frac_retail']} | "
          f"rebate {ov['clearable_frac_retail_pm_rebate']} | "
          f"inst {ov['clearable_frac_institutional']}")
    print(f"  wrote episodes.parquet ({len(episodes_df)} rows), episodes_summary.csv, "
          f"clearable_by_bucket.csv, sensitivity.csv, stats.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
