"""Task-2 spike: raw top-of-book for the NYK (Knicks) crossed window.

Loads the RAW stored rows for the 2026-05-28 NYK window identified in
DATA_AUDIT.md section 9 and plots both venues' YES top-of-book on one figure,
marking the crossed region. This is a sanity spike only:

  * NO auction logic, NO fee modeling, NO book.py/auction.py/fees.py.
  * Raw rows -> figure. The only computation is best_bid/best_ask differencing
    to locate the crossed region (the same pre-fee cross used in the audit).

Source rows: data/processed/timeofday_poll.csv — the E.1 30s panel's stored
per-venue top-of-book (venue in {kalshi_yes, polymarket_yes}). This is the
panel's primary processed store; the equivalent ladders live in the raw gz
bundles but top-of-book is exactly what we plot here.

Output: batch_counterfactual/knicks_spike.png

Run:
    uv run python batch_counterfactual/spike_knicks.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="mpl-"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PANEL_CSV = ROOT / "data" / "processed" / "timeofday_poll.csv"
OUT_PNG = Path(__file__).resolve().parent / "knicks_spike.png"

MARKET = "nba_finals_nyk"
WIN_LO = pd.Timestamp("2026-05-28T04:01:00Z")
WIN_HI = pd.Timestamp("2026-05-28T18:52:00Z")


def load_window() -> pd.DataFrame:
    df = pd.read_csv(PANEL_CSV)
    df["ts"] = pd.to_datetime(df["utc_ts"], utc=True, errors="coerce")
    m = df[(df["market_id"] == MARKET) & (df["ts"] >= WIN_LO) & (df["ts"] <= WIN_HI)]
    ky = (m[m["venue"] == "kalshi_yes"][["ts", "best_bid", "best_ask"]]
          .rename(columns={"best_bid": "k_bid", "best_ask": "k_ask"}))
    py = (m[m["venue"] == "polymarket_yes"][["ts", "best_bid", "best_ask"]]
          .rename(columns={"best_bid": "p_bid", "best_ask": "p_ask"}))
    w = ky.merge(py, on="ts", how="inner").sort_values("ts").reset_index(drop=True)
    # Pre-fee cross in cents (both directions); >0 means books cross.
    w["crossA_c"] = (w["k_bid"] - w["p_ask"]) * 100.0   # buy PM, sell Kalshi
    w["crossB_c"] = (w["p_bid"] - w["k_ask"]) * 100.0   # buy Kalshi, sell PM
    w["cross_c"] = w[["crossA_c", "crossB_c"]].max(axis=1)
    w["is_crossed"] = w["cross_c"] > 0
    return w


def make_figure(w: pd.DataFrame) -> dict:
    plt.rcParams.update({
        "font.size": 13, "axes.titlesize": 16, "axes.labelsize": 13,
        "figure.facecolor": "white", "axes.facecolor": "white",
    })
    fig, ax = plt.subplots(figsize=(16, 9), dpi=100)

    t = w["ts"].dt.tz_convert("UTC")
    # Shade contiguous crossed spans.
    crossed = w["is_crossed"].values
    start = None
    shaded_label_used = False
    for i in range(len(w)):
        if crossed[i] and start is None:
            start = t.iloc[i]
        is_last = i == len(w) - 1
        if (not crossed[i] or is_last) and start is not None:
            end = t.iloc[i] if not crossed[i] else t.iloc[i]
            ax.axvspan(start, end, color="#cf222e", alpha=0.07,
                       label=("crossed (raw, pre-fee)" if not shaded_label_used else None))
            shaded_label_used = True
            start = None

    ax.step(t, w["k_bid"], where="post", color="#1f6feb", lw=1.6, label="Kalshi YES bid")
    ax.step(t, w["k_ask"], where="post", color="#1f6feb", lw=1.6, ls="--", label="Kalshi YES ask")
    ax.step(t, w["p_bid"], where="post", color="#bc4c00", lw=1.6, label="Polymarket YES bid")
    ax.step(t, w["p_ask"], where="post", color="#bc4c00", lw=1.6, ls="--", label="Polymarket YES ask")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=None))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    ax.set_xlabel("2026-05-28 UTC")
    ax.set_ylabel("YES price (dollars)")

    frac = w["is_crossed"].mean() * 100.0
    med = w.loc[w["is_crossed"], "cross_c"].median()
    ax.set_title(
        f"NYK (Knicks) cross-venue YES top-of-book — raw 30s panel\n"
        f"crossed {frac:.1f}% of {len(w)} snapshots, median cross {med:.2f}c "
        f"(pre-fee, displayed top-of-book)",
        fontweight="bold",
    )
    ax.legend(loc="upper right", fontsize=11, framealpha=0.95, ncol=2)
    ax.grid(alpha=0.15)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)

    fig.text(0.5, 0.012,
             "Source: data/processed/timeofday_poll.csv (E.1 30s panel, "
             "stored top-of-book). Raw rows -> figure; no auction/fee logic. "
             "See batch_counterfactual/DATA_AUDIT.md sec 9.",
             ha="center", fontsize=10, color="#666666")
    fig.subplots_adjust(left=0.07, right=0.97, top=0.90, bottom=0.10)
    fig.savefig(OUT_PNG, dpi=100)
    plt.close(fig)

    return {
        "rows": len(w),
        "k_bid_nulls": int(w["k_bid"].isna().sum()),
        "k_ask_nulls": int(w["k_ask"].isna().sum()),
        "p_bid_nulls": int(w["p_bid"].isna().sum()),
        "p_ask_nulls": int(w["p_ask"].isna().sum()),
        "frac_crossed_pct": frac,
        "median_cross_c": float(med),
        "max_cross_c": float(w["cross_c"].max()),
    }


def main() -> int:
    w = load_window()
    if w.empty:
        print("ERROR: no NYK rows found in window; check PANEL_CSV / window bounds.")
        return 1
    s = make_figure(w)
    print("=" * 64)
    print("NYK Knicks-window spike (raw top-of-book)")
    print("=" * 64)
    print(f"  window         : {WIN_LO} -> {WIN_HI}")
    print(f"  paired snapshots: {s['rows']}")
    print(f"  top-of-book nulls (k_bid/k_ask/p_bid/p_ask): "
          f"{s['k_bid_nulls']}/{s['k_ask_nulls']}/{s['p_bid_nulls']}/{s['p_ask_nulls']}")
    print(f"  fraction crossed: {s['frac_crossed_pct']:.1f}%")
    print(f"  median cross    : {s['median_cross_c']:.2f}c (when crossed)")
    print(f"  max cross       : {s['max_cross_c']:.2f}c")
    pub_ok = abs(s["frac_crossed_pct"] - 100.0) < 1.0 and abs(s["median_cross_c"] - 0.5) < 0.2
    print("-" * 64)
    if pub_ok:
        print("  AGREES with published finding (~100% crossed, median ~0.5c).")
    else:
        print("  *** DISAGREES with published finding — investigate before trusting. ***")
    print(f"  wrote {OUT_PNG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
