"""Substack figure: takeable cross-venue arbitrage by fee tier.

The "fee cliff" story (EXP-3b): zero markets are takeable at any
retail-accessible fee tier; the arb only unlocks at a counterfactual
institutional tier that neither Kalshi nor Polymarket offers.

Recomputes per-tier takeable counts (and the institutional aggregate $)
directly from the D.2 snapshot via the existing fee engine
(`src/pm_micro/fees.py`) and the EXP-3b walker — NOT from remembered
numbers or the .md table. Importing `scripts/exp3b_fee_sweep.py` guarantees
the figure and the experiment use identical logic.

Output: data/processed/fig_fee_cliff_substack.png   (new file only)
Reads only; no edits to src/, markets.yaml, or existing figures.

Run:
    uv run python scripts/fig_fee_cliff.py
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
import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import exp3b_fee_sweep as sweep  # noqa: E402

OUT_PNG = ROOT / "data" / "processed" / "fig_fee_cliff_substack.png"

# Display order + which tiers are real vs counterfactual.
TIER_PLOT_ORDER = ["retail", "pm_rebate", "institutional", "zero"]
TIER_DISPLAY = {
    "retail": "Retail",
    "pm_rebate": "Retail +\nPM maker rebate",
    "institutional": "Institutional\n0.30% / 0.20%",
    "zero": "Zero-fee",
}
TIER_IS_REAL = {
    "retail": True,
    "pm_rebate": True,
    "institutional": False,
    "zero": False,
}


def recompute() -> dict:
    """Re-run the EXP-3b per-tier sweep from the latest snapshot."""
    with open(sweep.MARKETS_YAML) as f:
        markets = yaml.safe_load(f)
    with open(sweep.FEE_META_YAML) as f:
        meta_list = yaml.safe_load(f)
    meta_by_id = {e["market_id"]: e for e in meta_list}
    snapshot_dir = sorted(sweep.RAW_DIR.glob("snapshot_*"))[-1]

    n_computed = 0
    n_skipped = 0
    n_crossed = 0
    takeable_counts = {t: 0 for t in TIER_PLOT_ORDER}
    inst_net_by_market: dict[str, float] = {}

    for m in markets:
        mid = m["id"]
        meta = meta_by_id.get(mid)
        if not meta:
            n_skipped += 1
            continue
        k_yes, p_yes, _ = sweep.load_books(snapshot_dir, mid)
        if k_yes is None or p_yes is None:
            n_skipped += 1
            continue
        n_computed += 1
        direction = sweep.classify(k_yes, p_yes)
        if direction is not None:
            n_crossed += 1
        for tier in TIER_PLOT_ORDER:
            if direction is None:
                continue
            fee_fn = sweep.make_taker_fee_fn(tier, meta)
            tt = sweep.take_take_executable(k_yes, p_yes, mid, fee_fn)
            if tt["verdict"] == "TAKEABLE":
                takeable_counts[tier] += 1
                if tier == "institutional":
                    inst_net_by_market[mid] = tt["net"]

    return {
        "snapshot": snapshot_dir.name,
        "n_computed": n_computed,
        "n_skipped": n_skipped,
        "n_crossed": n_crossed,
        "takeable_counts": takeable_counts,
        "inst_net_by_market": inst_net_by_market,
        "inst_aggregate_usd": sum(inst_net_by_market.values()),
    }


def snapshot_to_utc(name: str) -> str:
    # snapshot_20260528T022943Z -> 2026-05-28 02:29:43 UTC
    core = name.replace("snapshot_", "").rstrip("Z")
    d, t = core.split("T")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:4]}:{t[4:6]} UTC"


def make_figure(s: dict) -> None:
    plt.rcParams.update({
        "font.size": 15,
        "axes.titlesize": 20,
        "axes.labelsize": 16,
        "xtick.labelsize": 14,
        "ytick.labelsize": 13,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })

    fig, ax = plt.subplots(figsize=(16, 9), dpi=100)

    counts = [s["takeable_counts"][t] for t in TIER_PLOT_ORDER]
    n_comp = s["n_computed"]
    x = range(len(TIER_PLOT_ORDER))

    real_color = "#1f6feb"
    cf_color = "#9aa4b2"

    bars = []
    for i, tier in enumerate(TIER_PLOT_ORDER):
        is_real = TIER_IS_REAL[tier]
        b = ax.bar(
            i, counts[i], width=0.62,
            color=real_color if is_real else cf_color,
            hatch="" if is_real else "////",
            edgecolor="white" if is_real else "#5b6573",
            linewidth=0 if is_real else 1.0,
            zorder=3,
        )
        bars.append(b)

    # Bar value labels.
    for i, tier in enumerate(TIER_PLOT_ORDER):
        c = counts[i]
        if c == 0:
            ax.annotate(
                f"0 of {n_comp}",
                xy=(i, 0), xytext=(0, 8), textcoords="offset points",
                ha="center", va="bottom", fontsize=16, fontweight="bold",
                color="#d1242f",
            )
        else:
            ax.annotate(
                f"{c} of {n_comp}",
                xy=(i, c), xytext=(0, 8), textcoords="offset points",
                ha="center", va="bottom", fontsize=16, fontweight="bold",
                color="#0d3b66",
            )

    ax.set_xticks(list(x))
    ax.set_xticklabels([TIER_DISPLAY[t] for t in TIER_PLOT_ORDER])
    ax.set_ylim(0, max(counts) * 1.22 if max(counts) else 1)
    ax.set_ylabel(f"Takeable markets (of {n_comp} computed)")
    ax.set_title("Cross-venue arbitrage by fee tier: the unlock doesn't exist",
                 pad=16, fontweight="bold")

    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.grid(axis="y", alpha=0.18, zorder=0)

    # Divider + shaded band marking the counterfactual region.
    ax.axvspan(1.5, len(TIER_PLOT_ORDER) - 0.5 + 0.12, color="#f1f3f5", zorder=0)
    ax.axvline(1.5, color="#5b6573", lw=1.2, ls=":", zorder=2)
    ymax = max(counts) if max(counts) else 1
    ax.text(0.5, ymax * 0.50, "offered to retail", ha="center", va="center",
            fontsize=13.5, color="#1f6feb", fontweight="bold")
    ax.text(2.5, ymax * 1.12, "not offered by either venue", ha="center", va="center",
            fontsize=13.5, color="#5b6573", fontweight="bold")

    # Institutional aggregate annotation.
    inst_count = s["takeable_counts"]["institutional"]
    inst_idx = TIER_PLOT_ORDER.index("institutional")
    if inst_count:
        ax.annotate(
            f"aggregate edge ≈ ${s['inst_aggregate_usd']:.0f} / snapshot\n"
            f"at displayed depth (exclusive-fill)",
            xy=(inst_idx, inst_count), xytext=(inst_idx - 0.02, inst_count * 0.62),
            ha="center", va="center", fontsize=13, color="#0d3b66",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                      edgecolor="#0d3b66", alpha=0.92, lw=1.1),
            zorder=6,
        )

    # Legend: real vs counterfactual.
    legend_handles = [
        mpatches.Patch(facecolor=real_color, edgecolor="white",
                       label="Real tier (offered to retail today)"),
        mpatches.Patch(facecolor=cf_color, hatch="////", edgecolor="#5b6573",
                       label="Counterfactual tier (not offered by either venue)"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", fontsize=13,
              frameon=True, framealpha=0.95)

    # Footer.
    fig.text(
        0.5, 0.045,
        f"D.2 snapshot {snapshot_to_utc(s['snapshot'])}  ·  single snapshot (n=1)  ·  "
        f"{s['n_computed']} markets computed, {s['n_crossed']} crossed at top-of-book, "
        f"{s['n_skipped']} skipped (books missing)",
        ha="center", fontsize=12.5, color="#555555",
    )
    fig.text(
        0.5, 0.016,
        "Direction-enforced take-take (both legs cross-side), exclusive-fill at displayed depth; "
        "engine: src/pm_micro/fees.py via EXP-3b",
        ha="center", fontsize=11.5, color="#888888", style="italic",
    )

    fig.subplots_adjust(left=0.075, right=0.97, top=0.90, bottom=0.135)
    fig.savefig(OUT_PNG, dpi=100)
    plt.close(fig)


def main() -> int:
    s = recompute()
    make_figure(s)

    print("=" * 70)
    print(f"EXP-3b fee-cliff — recomputed from {s['snapshot']}")
    print("=" * 70)
    print(f"  markets computed:            {s['n_computed']}")
    print(f"  markets crossed (top-of-book): {s['n_crossed']}")
    print(f"  markets skipped:             {s['n_skipped']}")
    print("  takeable count per tier:")
    for t in TIER_PLOT_ORDER:
        real = "real" if TIER_IS_REAL[t] else "counterfactual"
        print(f"    {t:14s} ({real:14s}): {s['takeable_counts'][t]} of {s['n_computed']}")
    print(f"  institutional aggregate $ / snapshot (sum of net, exclusive-fill): "
          f"${s['inst_aggregate_usd']:.2f}")
    print("  institutional per-market net $:")
    for mid, net in sorted(s["inst_net_by_market"].items(), key=lambda kv: -kv[1]):
        print(f"    {mid:32s} ${net:8.2f}")
    print("=" * 70)
    print(f"  wrote {OUT_PNG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
