"""Hero figure: NYK cross-venue crossed spread persisting ~14 hours.

Standalone, read-only one-off for a public blog post. Reads the committed
EXP-3c persistence sweep (`data/processed/exp3c_persistence.csv`) and plots
the `nba_finals_nyk` PRE-FEE raw top-of-book cross (paper_spread_c, cents)
over the daemon window.

Y-axis is the PRE-FEE raw book cross — NOT a fee-adjusted "profit". The point
of the figure is that the cross *looked* like free money and was not takeable
at any retail-accessible fee tier (see the post / EXP-3a/b/c).

All headline stats (window, n, fraction crossed, median/max cross in cents and
$ at displayed depth) are COMPUTED from the data here and printed, so the blog
text can be reconciled against the figure.

Output: data/processed/fig_nyk_persistence_substack.png  (new file only)
Does NOT modify src/, other scripts' logic, or any existing figure.

Run:
    uv run python scripts/fig_nyk_persistence.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Keep matplotlib's cache off the (read-only) home dir.
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="mpl-"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC_CSV = ROOT / "data" / "processed" / "exp3c_persistence.csv"
OUT_PNG = ROOT / "data" / "processed" / "fig_nyk_persistence_substack.png"
MARKET_ID = "nba_finals_nyk"

# Daemon cadence is 30s; break the plotted line across gaps wider than this so
# missed-snapshot intervals are shown honestly rather than interpolated over.
GAP_BREAK_S = 90.0


def load_nyk() -> pd.DataFrame:
    df = pd.read_csv(SRC_CSV)
    df = df[df["market_id"] == MARKET_ID].copy()
    # Drop fetch/normalize errors (empty error string == clean row).
    df["error"] = df["error"].fillna("")
    df = df[df["error"] == ""].copy()
    df["utc_ts"] = pd.to_datetime(df["utc_ts"], utc=True)
    df = df.sort_values("utc_ts").reset_index(drop=True)
    return df


def compute_stats(df: pd.DataFrame) -> dict:
    crossed_mask = df["paper_spread_c"] > 0
    crossed = df[crossed_mask]
    span_h = (df["utc_ts"].iloc[-1] - df["utc_ts"].iloc[0]).total_seconds() / 3600.0
    return {
        "start": df["utc_ts"].iloc[0],
        "end": df["utc_ts"].iloc[-1],
        "span_hours": span_h,
        "n_snapshots": int(len(df)),
        "n_crossed_paper": int(crossed_mask.sum()),
        "frac_crossed_paper": float(crossed_mask.mean()),
        "frac_crossed_inst": float(df["is_crossed"].mean()),
        "median_cross_c": float(crossed["paper_spread_c"].median()) if len(crossed) else 0.0,
        "max_cross_c": float(crossed["paper_spread_c"].max()) if len(crossed) else 0.0,
        # takeable_usd is NET of the modeled 0.30% institutional fee in EXP-3c,
        # at displayed depth. Reported for reconciliation with the README's
        # "$165 median crossed spread" figure (which is this column).
        "median_takeable_usd": float(crossed["takeable_usd"].median()) if len(crossed) else 0.0,
        "max_takeable_usd": float(crossed["takeable_usd"].max()) if len(crossed) else 0.0,
        "median_fillable": float(crossed["fillable"].median()) if len(crossed) else 0.0,
    }


def crossed_runs(ts: pd.Series, crossed: np.ndarray) -> list[tuple]:
    """Contiguous (start_ts, end_ts) spans where crossed is True.

    A run is broken either by an uncrossed snapshot or by a temporal gap
    wider than GAP_BREAK_S (so we never shade across unobserved time).
    """
    spans = []
    run_start = None
    prev_t = None
    for t, c in zip(ts, crossed):
        if c:
            if run_start is None:
                run_start = t
            elif prev_t is not None and (t - prev_t).total_seconds() > GAP_BREAK_S:
                spans.append((run_start, prev_t))
                run_start = t
        else:
            if run_start is not None:
                spans.append((run_start, prev_t))
                run_start = None
        prev_t = t
    if run_start is not None:
        spans.append((run_start, prev_t))
    return spans


def y_with_gaps(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return (x, y) with NaN inserted where consecutive snapshots are
    further apart than GAP_BREAK_S, so the line breaks across missed polls."""
    t = df["utc_ts"].to_numpy()
    y = df["paper_spread_c"].to_numpy(dtype=float).copy()
    dt = np.diff(df["utc_ts"].astype("int64").to_numpy()) / 1e9
    # Mark the FIRST point after a gap as NaN to break the connecting segment.
    break_idx = np.where(dt > GAP_BREAK_S)[0] + 1
    y[break_idx] = np.nan
    return t, y


def make_figure(df: pd.DataFrame, s: dict) -> None:
    plt.rcParams.update({
        "font.size": 15,
        "axes.titlesize": 19,
        "axes.labelsize": 16,
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })

    fig, ax = plt.subplots(figsize=(16, 9), dpi=100)

    kalshi_blue = "#1f6feb"
    cross_fill = "#1f6feb"
    median_red = "#d1242f"

    # Shade contiguous crossed runs (paper cross > 0), gap-aware.
    crossed = (df["paper_spread_c"] > 0).to_numpy()
    for (a, b) in crossed_runs(df["utc_ts"], crossed):
        ax.axvspan(a, b, color=cross_fill, alpha=0.08, lw=0)

    # The pre-fee raw cross series, with line breaks across polling gaps.
    x, y = y_with_gaps(df)
    ax.plot(x, y, color=kalshi_blue, lw=1.6, label="Raw cross (pre-fee)")
    ax.scatter(df["utc_ts"], df["paper_spread_c"], s=6, color=kalshi_blue,
               alpha=0.35, zorder=3, edgecolors="none")

    # Median line + annotation (computed, not hardcoded).
    med = s["median_cross_c"]
    ax.axhline(med, color=median_red, lw=1.8, ls="--", zorder=4)
    ax.annotate(
        f"median crossed cross = {med:.2f}¢\n"
        f"(≈ ${s['median_takeable_usd']:.0f} at displayed depth, "
        f"net of modeled 0.30% inst. fee)",
        xy=(0.985, med), xycoords=("axes fraction", "data"),
        xytext=(0, 14), textcoords="offset points",
        ha="right", va="bottom", color=median_red, fontsize=14, fontweight="bold",
    )

    ax.set_ylim(0, s["max_cross_c"] * 1.18)
    ax.set_xlabel("Time (UTC)")
    ax.set_ylabel("Cross-venue crossed spread (cents, pre-fee)")
    ax.set_title("NYK championship market: cross-venue spread, crossed for ~14 hours",
                 pad=14, fontweight="bold")

    # X axis: readable hourly labels.
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=None))
    ax.xaxis_date()

    # Light spines / minimal gridline clutter.
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.grid(axis="y", alpha=0.18)

    # Venue label inside the panel.
    ax.text(0.012, 0.965,
            "Kalshi YES  vs  Polymarket YES  (top-of-book cross, whichever venue is richer)",
            transform=ax.transAxes, fontsize=14, va="top", color="#444444")

    # Footer: data window + n, split across two lines so nothing overflows.
    start_s = s["start"].strftime("%Y-%m-%d %H:%M")
    end_s = s["end"].strftime("%H:%M")
    fig.text(
        0.5, 0.052,
        f"Daemon window {start_s}–{end_s} UTC ({s['span_hours']:.1f} h)  ·  "
        f"30 s snapshots, n = {s['n_snapshots']:,}  ·  "
        f"crossed in {s['frac_crossed_paper']*100:.1f}% of snapshots",
        ha="center", fontsize=12.5, color="#555555",
    )
    fig.text(
        0.5, 0.020,
        "Raw pre-fee top-of-book cross at displayed depth — "
        "not takeable at any retail-accessible fee tier (see post)",
        ha="center", fontsize=12, color="#888888", style="italic",
    )

    fig.subplots_adjust(left=0.07, right=0.97, top=0.91, bottom=0.135)
    fig.savefig(OUT_PNG, dpi=100)
    plt.close(fig)


def main() -> int:
    if not SRC_CSV.exists():
        print(f"ERROR: {SRC_CSV} not found", file=sys.stderr)
        return 1
    df = load_nyk()
    if df.empty:
        print(f"ERROR: no clean {MARKET_ID} rows in {SRC_CSV}", file=sys.stderr)
        return 1
    s = compute_stats(df)
    make_figure(df, s)

    print("=" * 68)
    print(f"NYK cross-venue persistence — stats computed from {SRC_CSV.name}")
    print("=" * 68)
    print(f"  window start (UTC):     {s['start']}")
    print(f"  window end   (UTC):     {s['end']}")
    print(f"  span:                   {s['span_hours']:.2f} hours")
    print(f"  total clean snapshots:  {s['n_snapshots']:,}")
    print(f"  snapshots crossed (paper cross > 0): "
          f"{s['n_crossed_paper']:,}  ({s['frac_crossed_paper']*100:.2f}%)")
    print(f"  snapshots crossed (institutional net > $0.005): "
          f"{s['frac_crossed_inst']*100:.2f}%")
    print(f"  median cross when crossed:  {s['median_cross_c']:.3f} cents")
    print(f"  max cross when crossed:     {s['max_cross_c']:.3f} cents")
    print(f"  median takeable $ at displayed depth (net 0.30% inst. fee): "
          f"${s['median_takeable_usd']:.2f}")
    print(f"  max takeable $ at displayed depth (net 0.30% inst. fee):    "
          f"${s['max_takeable_usd']:.2f}")
    print(f"  median fillable size when crossed: {s['median_fillable']:,.0f} contracts")
    print("=" * 68)
    print(f"  wrote {OUT_PNG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
