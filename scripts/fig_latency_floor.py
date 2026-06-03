"""Substack figure: cross-venue network differential and the ~100ms floor.

Kalshi (AWS us-east-2, Ohio) vs Polymarket (AWS eu-west-2, London) HTTP RTT
from the capture host (PA), measured across two independent calibration runs.
The point: the transatlantic path skew (~35-38ms one-way, Kalshi closer) is
stable run-to-run even as absolute RTTs drift, so any apparent cross-venue
"lead" under ~100ms from this vantage is geography, not information.

DATA (given; not re-measured here):
  * Run 1 (2026-05-31, committed in network_latency_calibration.md):
        Kalshi 19.7ms med / 33.8 p90 (n=35); PM 95.0 / 109.9 (n=35).
  * Run 2 (2026-06-01, from the task prompt):
        Kalshi 36.6 / 45.0; PM 106.7 / 116.3 (n=51).

Output: data/processed/fig_latency_floor_substack.png   (new file only)

Run:
    uv run python scripts/fig_latency_floor.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="mpl-"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_PNG = ROOT / "data" / "processed" / "fig_latency_floor_substack.png"
FLOOR_MS = 100  # lead-lag resolution floor (systematic offset + jitter)

# Given calibration results (median RTT, p90 RTT, n) per venue per run.
RUNS = {
    "Run 1\n2026-05-31": {
        "kalshi": {"median": 19.7, "p90": 33.8, "n": 35},
        "polymarket": {"median": 95.0, "p90": 109.9, "n": 35},
    },
    "Run 2\n2026-06-01": {
        "kalshi": {"median": 36.6, "p90": 45.0, "n": 51},
        "polymarket": {"median": 106.7, "p90": 116.3, "n": 51},
    },
}

VENUES = {
    "kalshi": ("Kalshi", "AWS us-east-2 · Ohio", "#1f6feb"),
    "polymarket": ("Polymarket", "AWS eu-west-2 · London", "#bc4c00"),
}


def one_way_diff(run: dict) -> float:
    """Implied one-way differential (ms): (PM_median - Kalshi_median) / 2."""
    return (run["polymarket"]["median"] - run["kalshi"]["median"]) / 2.0


def make_figure() -> dict:
    plt.rcParams.update({
        "font.size": 15,
        "axes.titlesize": 19,
        "axes.labelsize": 16,
        "xtick.labelsize": 14,
        "ytick.labelsize": 14,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })

    fig, ax = plt.subplots(figsize=(16, 9), dpi=100)

    run_names = list(RUNS.keys())
    venue_keys = ["kalshi", "polymarket"]

    # Two venue clusters; within each, one bar per run (median RTT, p90 whisker).
    cluster_x = {"kalshi": 0.0, "polymarket": 2.0}
    bar_w = 0.62
    offsets = {run_names[0]: -bar_w / 2 - 0.02, run_names[1]: bar_w / 2 + 0.02}
    run_alpha = {run_names[0]: 0.55, run_names[1]: 1.0}

    xticks, xticklabels = [], []
    for vk in venue_keys:
        name, region, color = VENUES[vk]
        for rn in run_names:
            x = cluster_x[vk] + offsets[rn]
            med = RUNS[rn][vk]["median"]
            p90 = RUNS[rn][vk]["p90"]
            ax.bar(x, med, width=bar_w, color=color, alpha=run_alpha[rn],
                   zorder=3, edgecolor="white", linewidth=1.2)
            # p90 whisker: cap line from median to p90.
            ax.plot([x, x], [med, p90], color="#24292f", lw=1.8, zorder=4)
            ax.plot([x - 0.12, x + 0.12], [p90, p90], color="#24292f",
                    lw=1.8, zorder=4)
            ax.annotate(f"{med:.1f}", xy=(x, med), xytext=(0, 4),
                        textcoords="offset points", ha="center", va="bottom",
                        fontsize=12.5, fontweight="bold", color="#24292f")
            ax.annotate(f"p90 {p90:.1f}", xy=(x, p90), xytext=(0, 4),
                        textcoords="offset points", ha="center", va="bottom",
                        fontsize=10.5, color="#57606a")
            xticks.append(x)
            xticklabels.append(rn)
        # Venue label centered under the cluster.
        ax.annotate(f"{name}\n{region}", xy=(cluster_x[vk], 0),
                    xytext=(0, -52), textcoords="offset points",
                    ha="center", va="top", fontsize=15, fontweight="bold",
                    color=color, annotation_clip=False)

    ax.set_xticks(xticks)
    ax.set_xticklabels(xticklabels, fontsize=12.5, color="#57606a")
    ax.set_ylabel("HTTP round-trip time from capture host (ms)")
    ax.set_ylim(0, 150)
    ax.set_xlim(-1.1, 3.1)

    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.grid(axis="y", alpha=0.18, zorder=0)

    # ~100 ms lead-lag resolution floor (offset + jitter vs plausible information lead).
    ax.axhspan(0, FLOOR_MS, facecolor="#8250df", alpha=0.10, zorder=0.5)
    ax.axhline(FLOOR_MS, color="#8250df", lw=2.0, ls=(0, (6, 4)), zorder=1)
    ax.text(
        3.02, FLOOR_MS + 4,
        f"~{FLOOR_MS} ms lead-lag\nresolution floor",
        ha="right", va="bottom", fontsize=12, color="#8250df", fontweight="bold",
    )

    d1 = one_way_diff(RUNS[run_names[0]])
    d2 = one_way_diff(RUNS[run_names[1]])
    rtt_d1 = RUNS[run_names[0]]["polymarket"]["median"] - RUNS[run_names[0]]["kalshi"]["median"]
    rtt_d2 = RUNS[run_names[1]]["polymarket"]["median"] - RUNS[run_names[1]]["kalshi"]["median"]

    # Differential bracket between the two venue clusters (use Run-2 medians).
    k_med = RUNS[run_names[1]]["kalshi"]["median"]
    pm_med = RUNS[run_names[1]]["polymarket"]["median"]
    bracket_x = 1.0
    ax.annotate("", xy=(bracket_x, pm_med), xytext=(bracket_x, k_med),
                arrowprops=dict(arrowstyle="<->", color="#cf222e", lw=2.2))
    ax.annotate(
        f"one-way differential\n~35–38 ms (Kalshi closer)\n"
        f"Run 1 {d1:.1f} · Run 2 {d2:.1f} ms",
        xy=(bracket_x, (k_med + pm_med) / 2),
        xytext=(bracket_x - 0.14, (k_med + pm_med) / 2),
        ha="right", va="center", fontsize=12.5, color="#cf222e",
        fontweight="bold",
    )

    fig.suptitle(
        "The transatlantic floor: venue server geography bounds what's measurable",
        y=0.965, fontsize=19, fontweight="bold",
    )
    fig.text(
        0.5, 0.915,
        "Median RTT nearly doubled for Kalshi between runs, yet the cross-venue "
        "differential held — the path skew is structural, not noise",
        ha="center", va="center", fontsize=13, color="#57606a", style="italic",
    )

    # Conclusion callout box (empty upper-left region).
    ax.text(
        0.015, 0.965,
        "Any cross-venue \"lead\" under ~100 ms\n"
        "from this vantage is network geography,\n"
        "not information.",
        transform=ax.transAxes, ha="left", va="top",
        fontsize=14, color="#24292f", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#fff8c5",
                  edgecolor="#d4a72c", linewidth=1.5),
    )

    fig.text(
        0.5, 0.052,
        "Method: persistent-client HTTP GET RTT to each venue's public edge, "
        "~40 s @ 1 Hz; one-way ≈ RTT/2 (symmetric-path assumption)",
        ha="center", fontsize=12, color="#555555",
    )
    fig.text(
        0.5, 0.022,
        "Capture host in Pennsylvania, USA  ·  Run 1 n=35/venue (2026-05-31)  ·  "
        "Run 2 n=51/venue (2026-06-01)  ·  HTTPS edge may differ from WS ingress",
        ha="center", fontsize=11, color="#888888", style="italic",
    )

    fig.subplots_adjust(left=0.075, right=0.97, top=0.865, bottom=0.20)
    fig.savefig(OUT_PNG, dpi=100)
    plt.close(fig)

    return {
        "run1_oneway": d1, "run2_oneway": d2,
        "run1_rtt_diff": rtt_d1, "run2_rtt_diff": rtt_d2,
    }


def main() -> int:
    s = make_figure()
    print("=" * 70)
    print("Cross-venue network differential (Kalshi Ohio vs Polymarket London)")
    print("=" * 70)
    for rn, run in RUNS.items():
        label = rn.replace("\n", " ")
        print(f"  {label}")
        print(f"    Kalshi      {run['kalshi']['median']:5.1f} ms med / "
              f"{run['kalshi']['p90']:5.1f} p90  (n={run['kalshi']['n']})")
        print(f"    Polymarket  {run['polymarket']['median']:5.1f} ms med / "
              f"{run['polymarket']['p90']:5.1f} p90  (n={run['polymarket']['n']})")
    print("-" * 70)
    print(f"  RTT differential (PM - Kalshi):  Run 1 {s['run1_rtt_diff']:+.1f} ms  ·  "
          f"Run 2 {s['run2_rtt_diff']:+.1f} ms")
    print(f"  Implied one-way differential:    Run 1 {s['run1_oneway']:.1f} ms  ·  "
          f"Run 2 {s['run2_oneway']:.1f} ms")
    print(f"  -> stable ~35-38 ms one-way; resolution floor ~100 ms.")
    print("=" * 70)
    print(f"  wrote {OUT_PNG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
