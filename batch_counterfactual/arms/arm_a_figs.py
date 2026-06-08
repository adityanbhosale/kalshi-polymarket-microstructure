"""Arm A — figures (Phase 3, decision Q1=A adds stratification + fig_a5).

Reads the Arm A outputs (episodes.parquet, episodes_summary.csv,
clearable_by_bucket.csv, sized_clearance.parquet, stats.json) and renders:

  fig_a1  stratified episode-duration distribution (log-x), all pairs
  fig_a2  clearable-fraction by fee tier x duration bucket (fee cliff, episodes)
  fig_a3  FLAGSHIP Knicks window: crossed top-of-book + counterfactual first call
  fig_a4  minutes-in-crossed-state per market-day, per pair
  fig_a5  episode count + total crossed-minutes by duration bucket, per pair

Run:
    uv run python batch_counterfactual/arms/arm_a_figs.py
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from _common import BUCKET_LABELS, FEE_CATEGORY, FIGS, INCLUDED_PAIRS, LADDERS, RESULTS
from arm_a_clearance import TIERS
from arm_a_sized import _orders_from_ladder, _prune_to_band
from auction import clear
from book import Panel
from fees import Tier

TIER_LABELS = [t for t, _ in TIERS]
TIER_COLORS = {
    "gross": "#1b9e77", "retail": "#d95f02",
    "retail_pm_rebate": "#7570b3", "institutional": "#e7298a",
}
BUCKET_COLORS = {
    "<1min": "#cfe8f3", "1-5min": "#7fb9d6", "5-30min": "#3a7fb0", ">30min": "#0b3954",
}
plt.rcParams.update({"figure.dpi": 130, "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.25})


def _load():
    ep = pd.read_parquet(RESULTS / "episodes.parquet").drop_duplicates("episode_id")
    summ = pd.read_csv(RESULTS / "episodes_summary.csv")
    strat = pd.read_csv(RESULTS / "clearable_by_bucket.csv")
    stats = json.loads((RESULTS / "stats.json").read_text())
    sized = None
    sp = RESULTS / "sized_clearance.parquet"
    if sp.exists():
        sized = pd.read_parquet(sp)
    return ep, summ, strat, stats, sized


# -------------------------------------------------------------------------
def fig_a1(ep: pd.DataFrame) -> None:
    dur = ep["duration_s"].to_numpy(dtype=float)
    dur_plot = np.clip(dur, 1.0, None)  # single-cycle (0s) episodes -> 1s for log-x
    bins = np.logspace(0, np.log10(max(dur_plot.max(), 10)), 40)
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    # color each episode by its duration bucket
    for b in BUCKET_LABELS:
        d = dur_plot[ep["duration_bucket"].to_numpy() == b]
        if len(d):
            ax.hist(d, bins=bins, stacked=True, color=BUCKET_COLORS[b],
                    label=f"{b} (n={len(d)})", edgecolor="white", linewidth=0.3,
                    alpha=0.95, histtype="stepfilled")
    for x in (60, 300, 1800):
        ax.axvline(x, color="0.4", ls="--", lw=0.8)
    ax.set_xscale("log")
    ax.set_xlabel("episode duration (s, log) — single-cycle episodes clamped to 1s")
    ax.set_ylabel("episodes")
    ax.set_title("fig_a1 — episode duration distribution, all included pairs\n"
                 "(the flagship window is the extreme right tail, not the typical state)")
    ax.legend(title="duration bucket", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_a1_duration_distribution.png")
    plt.close(fig)


# -------------------------------------------------------------------------
def fig_a2(strat: pd.DataFrame) -> None:
    ov = strat[strat["scope"] == "OVERALL"].set_index("duration_bucket")
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    x = np.arange(len(TIER_LABELS))
    w = 0.2
    for i, b in enumerate(BUCKET_LABELS):
        vals = [ov.loc[b, f"clearable_frac_{t}"] if b in ov.index else np.nan
                for t in TIER_LABELS]
        ax.bar(x + (i - 1.5) * w, vals, w, color=BUCKET_COLORS[b], label=b,
               edgecolor="white", linewidth=0.4)
    ax.set_xticks(x)
    ax.set_xticklabels(["gross\n(zero-fee)", "retail", "retail\n+PM rebate", "institutional\n(0.30/0.20%)"])
    ax.set_ylabel("fraction of episode-starts clearable")
    ax.set_ylim(0, 1.05)
    ax.set_title("fig_a2 — episode-start clearable fraction by fee tier x duration bucket\n"
                 "(the fee cliff: gross-crossed everywhere, but retail eats almost none)")
    ax.legend(title="duration bucket", fontsize=8, ncol=4, loc="upper right")
    fig.tight_layout()
    fig.savefig(FIGS / "fig_a2_clearable_by_tier.png")
    plt.close(fig)


# -------------------------------------------------------------------------
def _window_quotes(panel: Panel, pair: str, t0, t1) -> pd.DataFrame:
    k = panel._leg("kalshi", pair).rename(columns={"best_bid": "kb", "best_ask": "ka"})
    p = panel._leg("polymarket", pair).rename(columns={"best_bid": "pb", "best_ask": "pa"})
    m = k.merge(p, on="ts", how="inner")
    m = m[(m["ts"] >= pd.Timestamp(t0)) & (m["ts"] <= pd.Timestamp(t1))]
    return m.sort_values("ts")


def fig_a3(ep: pd.DataFrame, sized: pd.DataFrame | None) -> list[tuple]:
    panel = Panel()
    nyk = ep[ep["pair"] == "nba_finals_nyk"].sort_values("duration_s", ascending=False).iloc[0]
    t0, t1 = nyk["start_ts"], nyk["end_ts"]
    q = _window_quotes(panel, "nba_finals_nyk", t0, t1)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.5, 7.2),
                                   gridspec_kw={"height_ratios": [2.0, 1.0]})
    ax1.plot(q["ts"], q["kb"] * 100, color="#1f77b4", lw=0.8, label="Kalshi YES bid")
    ax1.plot(q["ts"], q["ka"] * 100, color="#1f77b4", lw=0.8, ls="--", label="Kalshi YES ask")
    ax1.plot(q["ts"], q["pb"] * 100, color="#d62728", lw=0.8, label="Polymarket YES bid")
    ax1.plot(q["ts"], q["pa"] * 100, color="#d62728", lw=0.8, ls="--", label="Polymarket YES ask")
    ax1.axvline(pd.Timestamp(t0), color="green", lw=1.2)
    ax1.annotate("episode start\n(first call)", (pd.Timestamp(t0), ax1.get_ylim()[1]),
                 fontsize=8, color="green", va="top", ha="left")
    ax1.set_ylabel("YES price (¢)")
    ax1.set_title(f"fig_a3 — FLAGSHIP: NYK crossed window {round(nyk['duration_s']/3600,2)}h "
                  f"({int(nyk['n_cycles'])} cycles), Kalshi bid > Polymarket ask")
    ax1.legend(fontsize=8, ncol=2)

    # Bottom: per-tier TOTAL price improvement from the SAME clear() that drives
    # the headline numbers (max_volume objective on the full extracted ladder).
    cat = FEE_CATEGORY["nba_finals_nyk"]
    lad = pd.read_parquet(LADDERS / "nba_finals_nyk.parquet")
    snap = lad[lad["ts"] == pd.Timestamp(t0)]
    orders = _prune_to_band(_orders_from_ladder(snap))

    labels, agg_pis, qtys, blended = [], [], [], []
    tier_table: list[tuple[str, float, float, float | None]] = []
    for tlabel, tier in TIERS:
        res = clear(orders, "max_volume", tier, category=cat) if orders else None
        if res is None or res.clearing_price is None:
            agg, qty, blend = 0.0, 0.0, None
        else:
            agg, qty = float(res.agg_pi), float(res.total_qty)
            blend = (agg / qty * 100.0) if qty else None
        labels.append(tlabel)
        agg_pis.append(agg)
        qtys.append(qty)
        blended.append(blend)
        tier_table.append((tlabel, agg, qty, blend))

    x = np.arange(len(labels))
    ax2.bar(x, agg_pis, 0.6, color=[TIER_COLORS[t] for t in labels], edgecolor="white")
    ymax = max(agg_pis + [1.0])
    ax2.set_ylim(0, ymax * 1.30)
    for i, (agg, qty, blend) in enumerate(zip(agg_pis, qtys, blended)):
        if agg > 0 and blend is not None:
            ax2.annotate(f"${agg:,.0f}\n{qty:,.0f} ctr\n{blend:.3f}¢/ctr",
                         (i, agg + ymax * 0.03), fontsize=7.5, ha="center", va="bottom")
        else:
            ax2.annotate("$0\n(not clearable)", (i, ymax * 0.03), fontsize=7.5,
                         ha="center", va="bottom", color="0.4")
    ax2.set_xticks(x)
    ax2.set_xticklabels(["gross", "retail", "retail+rebate", "institutional"])
    ax2.set_ylabel("total price improvement at first-clearance ($)")
    ax2.set_title("single uniform-price call on full extracted ladders — "
                  "both legs, depth-integrated", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_a3_knicks_flagship.png", bbox_inches="tight")
    plt.close(fig)
    return tier_table


# -------------------------------------------------------------------------
def fig_a4(summ: pd.DataFrame) -> None:
    s = summ[summ["scope"].isin(INCLUDED_PAIRS)].copy()
    s = s.sort_values("crossed_min_per_market_day", ascending=True)
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    ax.barh(s["scope"], s["crossed_min_per_market_day"], color="#3a7fb0",
            edgecolor="white")
    for y, (v, md) in enumerate(zip(s["crossed_min_per_market_day"], s["active_market_days"])):
        ax.annotate(f"{v:.0f} min/day  ({int(md)}d)", (v, y), fontsize=8,
                    va="center", ha="left", xytext=(3, 0), textcoords="offset points")
    ax.set_xlabel("minutes in gross-crossed state per active market-day "
                  "(outage + per-pair gap time excluded)")
    ax.set_title("fig_a4 — time-in-crossed-state intensity, per pair")
    ax.margins(x=0.18)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_a4_minutes_crossed_per_day.png")
    plt.close(fig)


# -------------------------------------------------------------------------
def fig_a5(summ: pd.DataFrame) -> None:
    s = summ[summ["scope"].isin(INCLUDED_PAIRS)].set_index("scope")
    pairs = [p for p in INCLUDED_PAIRS]
    fig, (axc, axm) = plt.subplots(1, 2, figsize=(13.5, 5.6))
    x = np.arange(len(pairs))
    bot_c = np.zeros(len(pairs))
    bot_m = np.zeros(len(pairs))
    for b in BUCKET_LABELS:
        cnt = np.array([s.loc[p, f"n_episodes_{b}"] if p in s.index else 0 for p in pairs], float)
        mins = np.array([s.loc[p, f"crossed_min_{b}"] if p in s.index else 0 for p in pairs], float)
        axc.bar(x, cnt, bottom=bot_c, color=BUCKET_COLORS[b], label=b, edgecolor="white", linewidth=0.4)
        axm.bar(x, mins, bottom=bot_m, color=BUCKET_COLORS[b], label=b, edgecolor="white", linewidth=0.4)
        bot_c += cnt
        bot_m += mins
    for ax, ttl in ((axc, "episode count"), (axm, "total crossed-minutes")):
        ax.set_xticks(x)
        ax.set_xticklabels(pairs, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel(ttl)
        ax.legend(title="duration bucket", fontsize=8)
    axm.set_yscale("log")
    axc.set_title("fig_a5 — episode count by duration bucket, per pair")
    axm.set_title("fig_a5 — total crossed-minutes by duration bucket, per pair (log-y)")
    fig.suptitle("fig_a5 — episodes vs crossed-minutes by duration bucket "
                 "(few long episodes dominate the time-in-state)", y=1.02)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_a5_buckets_per_pair.png", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    ep, summ, strat, stats, sized = _load()
    fig_a1(ep)
    fig_a2(strat)
    fig_a3(ep, sized)
    fig_a4(summ)
    fig_a5(summ)
    print("wrote figs:", ", ".join(sorted(p.name for p in FIGS.glob("fig_a*.png"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
