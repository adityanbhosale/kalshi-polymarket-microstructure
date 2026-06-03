"""Substack figure: net 5-minute post-fill markout, all 8 LP-edge markets.

Resolves *why* the crossed cross-venue spread sits there untaken: post-fill
markout is negative on every one of the 8 markets at the 5-minute horizon.
The displayed edge is adverse-selection-paid spread, not free money.

DATA (read-only, values used as computed by EXP-12a — NOT recomputed):
  * data/processed/exp12a_fill_summary.csv   — net 5-min markout per market
        (markout_net_mean_5min_c), EXP-12a verdict classification.
  * data/processed/exp12a_markout_samples.csv — per-leg fill counts at the
        5-min horizon (buy_n_fills + sell_n_fills).

Output: data/processed/fig_markout_substack.png   (new file only)
No edits to src/, markets.yaml, or existing figures.

Run:
    uv run python scripts/fig_markout.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="mpl-"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FILL_SUMMARY = ROOT / "data" / "processed" / "exp12a_fill_summary.csv"
MARKOUT_SAMPLES = ROOT / "data" / "processed" / "exp12a_markout_samples.csv"
OUT_PNG = ROOT / "data" / "processed" / "fig_markout_substack.png"

# Readable labels for the 8-market panel.
LABELS = {
    "co_aesp": "Colombia pres. (AESP)",
    "co_pval": "Colombia pres. (PVAL)",
    "pe_rpal": "Peru pres. (RPAL)",
    "kr_oseh": "Seoul mayor (OSEH)",
    "la_kbas": "LA mayor (KBAS)",
    "nyk": "NBA Finals (NYK)",
    "arod": "A. Rodgers retire (AROD)",
    "kelce": "T. Kelce retire (KELCE)",
}

# Classification -> (display, color). REAL_EDGE is green but flagged thin.
CLASS_STYLE = {
    "REAL_EDGE": ("Real edge (thin)", "#2da44e"),
    "MARGINAL": ("Marginal", "#d4a72c"),
    "ADVERSE-SELECTED": ("Adverse-selected", "#cf222e"),
    "SUB-FILL": ("Sub-fill (won't fill)", "#8c959f"),
}


def load() -> pd.DataFrame:
    summ = pd.read_csv(FILL_SUMMARY)
    samp = pd.read_csv(MARKOUT_SAMPLES)
    samp5 = samp[samp["horizon"] == "5min"].copy()
    samp5["n_fills"] = (
        samp5["buy_n_fills"].fillna(0) + samp5["sell_n_fills"].fillna(0)
    ).astype(int)
    fills = samp5.set_index("market")["n_fills"]
    summ = summ.copy()
    summ["n_fills"] = summ["market"].map(fills)
    # The plotted quantity: net 5-min markout (mean), as computed by EXP-12a.
    summ["markout"] = summ["markout_net_mean_5min_c"]
    summ["markout_median"] = summ["markout_net_median_5min_c"]
    return summ[[
        "market", "markout", "markout_median", "verdict", "n_fills",
        "gross_edge_c", "p_fill_5min",
    ]]


def make_figure(df: pd.DataFrame) -> None:
    plt.rcParams.update({
        "font.size": 15,
        "axes.titlesize": 19,
        "axes.labelsize": 16,
        "xtick.labelsize": 13,
        "ytick.labelsize": 14,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })

    # Sort least-negative (top) to most-negative (bottom).
    d = df.sort_values("markout", ascending=True).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(16, 9), dpi=100)
    ypos = range(len(d))
    colors = [CLASS_STYLE[v][1] for v in d["verdict"]]

    ax.barh(list(ypos), d["markout"], color=colors, height=0.66, zorder=3)

    ax.set_yticks(list(ypos))
    ax.set_yticklabels([LABELS.get(m, m) for m in d["market"]])

    # Emphasized zero line.
    ax.axvline(0, color="#24292f", lw=2.2, zorder=4)

    xmin = d["markout"].min()
    ax.set_xlim(xmin * 1.42, abs(xmin) * 0.34)

    # Per-bar annotation: value + n fills (+ thin-edge flag).
    for i, row in d.iterrows():
        val = row["markout"]
        label = f"{val:.2f}¢   (n={int(row['n_fills'])} fills)"
        if row["verdict"] == "REAL_EDGE":
            label += "  ⚠ thin"
        ax.annotate(
            label,
            xy=(val, i), xytext=(-8, 0), textcoords="offset points",
            ha="right", va="center", fontsize=12.5, color="#24292f",
        )

    ax.set_xlabel("Net 5-minute post-fill markout (cents per contract)")
    ax.set_title(
        "Why the spread sits there: post-fill markout is negative on all 8 markets",
        pad=36, fontweight="bold",
    )
    # Red subtitle: the takeaway, full-width so it never collides with bars.
    fig.text(
        0.5, 0.902,
        "negative markout = the fill moves against you  →  the displayed spread is "
        "adverse-selection-paid, not free money",
        ha="center", va="center", fontsize=13.5, color="#cf222e", style="italic",
    )

    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", alpha=0.18, zorder=0)

    # Legend by EXP-12a classification (counts in label).
    counts = d["verdict"].value_counts()
    order = ["REAL_EDGE", "MARGINAL", "ADVERSE-SELECTED", "SUB-FILL"]
    handles = [
        mpatches.Patch(
            color=CLASS_STYLE[v][1],
            label=f"{CLASS_STYLE[v][0]} ({int(counts.get(v, 0))})",
        )
        for v in order
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=12.5,
              frameon=True, framealpha=0.95, title="EXP-12a classification",
              bbox_to_anchor=(0.005, 0.985))

    fig.text(
        0.5, 0.045,
        "EXP-12a fill-realism: daemon window 2026-05-28 (~14.5 h, 30 s polls)  ·  "
        "8 direction-enforced LP-edge markets (institutional tier)",
        ha="center", fontsize=12.5, color="#555555",
    )
    fig.text(
        0.5, 0.016,
        "Net markout = mean of (buy-leg + sell-leg) price drift 5 min after a modeled fill, "
        "per-leg fill-probability weighted; net of fees",
        ha="center", fontsize=11.5, color="#888888", style="italic",
    )

    fig.subplots_adjust(left=0.20, right=0.97, top=0.875, bottom=0.135)
    fig.savefig(OUT_PNG, dpi=100)
    plt.close(fig)


def main() -> int:
    df = load()
    make_figure(df)

    d = df.sort_values("markout", ascending=True)
    print("=" * 74)
    print("EXP-12a net 5-minute post-fill markout (mean), per market")
    print("=" * 74)
    n_pos = (d["markout"] > 0).sum()
    for _, r in d.iterrows():
        flag = "  <-- POSITIVE!" if r["markout"] > 0 else ""
        print(f"  {LABELS.get(r['market'], r['market']):26s} "
              f"{r['markout']:7.3f}c  (median {r['markout_median']:6.2f}c)  "
              f"n={int(r['n_fills']):>3d}  {r['verdict']:16s}{flag}")
    print("-" * 74)
    print(f"  markets with NEGATIVE net 5-min markout: "
          f"{int((d['markout'] <= 0).sum())} of {len(d)}")
    if n_pos:
        print(f"  WARNING: {n_pos} market(s) computed POSITIVE — narrative says all ≤0!")
    else:
        print("  all 8 ≤ 0 — consistent with the toxic-spread narrative.")
    print("  classification counts:",
          dict(d["verdict"].value_counts()))
    print("=" * 74)
    print(f"  wrote {OUT_PNG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
