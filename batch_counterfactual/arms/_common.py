"""Shared constants/helpers for Arm A (episode clearance) — Phase 3.

Consumes the Phase 1/2 modules (book/fees/auction/cutoffs). All work runs on the
FROZEN set. Nothing here invents quantities; per-contract is the only real-data
output unless ladders are extracted (extract_ladders.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Make the Phase 1/2 modules (one dir up) importable when run as scripts.
_BC_DIR = Path(__file__).resolve().parents[1]
if str(_BC_DIR) not in sys.path:
    sys.path.insert(0, str(_BC_DIR))

from book import (  # noqa: E402
    DEFAULT_GAP_TOLERANCE_S,
    FROZEN_CUTOFF,
    OUTAGE_10H,
    Panel,
    venue_tick,
)

ROOT = _BC_DIR.parent

# ---- Episode contiguity (decision Q2=A, 2026-06-06) ----------------------
# EPISODE_GAP_MAX_S is the episode-contiguity tolerance, DECOUPLED from book.py's
# staleness bound (DEFAULT_GAP_TOLERANCE_S = 90s, UNCHANGED). A daemon gap of
# <= EPISODE_GAP_MAX_S WITHIN a crossed run is BRIDGED — the unobserved interval
# is assumed continuously crossed (bridging assumption). A gap > this, or any
# OBSERVED uncross/one-sided cycle, ends the episode. Intra-episode deltas above
# BRIDGE_GAP_MIN_S (= book staleness) are counted as bridged gaps.
EPISODE_GAP_MAX_S = 600.0          # 10 min
BRIDGE_GAP_MIN_S = DEFAULT_GAP_TOLERANCE_S   # 90s: above this = a bridged gap
NOMINAL_CADENCE_S = 30.0
SENSITIVITY_TOLS = (90.0, 300.0, 600.0)

# Duration strata (seconds): label, lo (inclusive), hi (exclusive).
DURATION_BUCKETS: list[tuple[str, float, float]] = [
    ("<1min", 0.0, 60.0),
    ("1-5min", 60.0, 300.0),
    ("5-30min", 300.0, 1800.0),
    (">30min", 1800.0, float("inf")),
]
BUCKET_LABELS = [b[0] for b in DURATION_BUCKETS]


def duration_bucket(seconds: float) -> str:
    for label, lo, hi in DURATION_BUCKETS:
        if lo <= seconds < hi:
            return label
    return DURATION_BUCKETS[-1][0]


RESULTS = _BC_DIR / "results" / "arm_a"
LADDERS = RESULTS / "ladders"
FIGS = RESULTS / "figs"
RAW_TIMEOFDAY = ROOT / "data" / "raw" / "timeofday"

for _d in (RESULTS, LADDERS, FIGS):
    _d.mkdir(parents=True, exist_ok=True)


# =========================================================================
# Inclusion — conditional-with-floor denominator (Appendix A, decision #4)
# =========================================================================
# A pair is INCLUDED iff, over frozen cycles EXCLUDING the 10.1h outage:
#   (1) FLOOR: both venues quote (any side) in >= 80% of all frozen cycles, AND
#   (2) CONDITIONAL: among cycles where both venues quote, both are two-sided
#       in >= 80%.
# This reconciles to Appendix A's all-cycles list (kr_oseh's 79.1% presence sits
# just under the floor; okc/icas/co_pval fail the floor; rhua/cle fail (2)).
INCLUSION_FLOOR = 0.80
INCLUSION_CONDITIONAL = 0.80

# Canonical included set (sorted, deterministic). 10 pairs.
INCLUDED_PAIRS: list[str] = sorted([
    "intl_president_co_aesp",
    "intl_president_pe_kfuj",
    "intl_president_pe_rpal",
    "ma_acquisition_wb_psky",
    "nba_finals_nyk",
    "nba_finals_sas",
    "sports_retirement_arod",
    "sports_retirement_kelce",
    "us_mayor_la_kbas",
    "us_senate_ak_mpel",
])

# Polymarket fee category per included pair (markets.yaml `category` -> fee key).
# politics 0.04 / sports 0.03 / tech 0.04 (WB Gamma feeType=tech_fees, audit Q8).
FEE_CATEGORY: dict[str, str] = {
    "intl_president_co_aesp": "politics",
    "intl_president_pe_kfuj": "politics",
    "intl_president_pe_rpal": "politics",
    "ma_acquisition_wb_psky": "tech",
    "nba_finals_nyk": "sports",
    "nba_finals_sas": "sports",
    "sports_retirement_arod": "sports",
    "sports_retirement_kelce": "sports",
    "us_mayor_la_kbas": "politics",
    "us_senate_ak_mpel": "politics",
}


def in_outage(ts: pd.Timestamp) -> bool:
    lo, hi = OUTAGE_10H
    return lo < ts < hi


def gz_path(pair: str, ts: pd.Timestamp) -> Path:
    """Raw gz bundle path for one (market, cycle). Filename embeds utc_ts."""
    ts = pd.Timestamp(ts)
    stamp = ts.strftime("%Y-%m-%dT%H%M%S.%f") + "+0000"
    day = ts.strftime("%Y-%m-%d")
    return RAW_TIMEOFDAY / day / f"{stamp}_{pair}.json.gz"


def compute_inclusion(panel: Panel) -> pd.DataFrame:
    """Reproduce the conditional-with-floor inclusion table (transparency)."""
    df = panel._load()
    lo, hi = OUTAGE_10H
    df = df[~((df["ts"] > lo) & (df["ts"] < hi))]
    all_cycles = df["ts"].nunique()
    rows = []
    for mid, g in df.groupby("market_id"):
        ky = g[g.venue == "kalshi_yes"].set_index("ts")
        py = g[g.venue == "polymarket_yes"].set_index("ts")
        k_any = ky["best_bid"].notna() | ky["best_ask"].notna()
        p_any = py["best_bid"].notna() | py["best_ask"].notna()
        k_two = ky["best_bid"].notna() & ky["best_ask"].notna()
        p_two = py["best_bid"].notna() & py["best_ask"].notna()
        j = pd.concat([k_any.rename("ka"), p_any.rename("pa"),
                       k_two.rename("kt"), p_two.rename("pt")], axis=1).fillna(False)
        both_present = int((j["ka"] & j["pa"]).sum())
        both_two = int((j["kt"] & j["pt"]).sum())
        presence = both_present / all_cycles if all_cycles else 0.0
        r_cond = both_two / both_present if both_present else 0.0
        included = presence >= INCLUSION_FLOOR and r_cond >= INCLUSION_CONDITIONAL
        rows.append({
            "pair": mid, "presence_both_pct": round(presence * 100, 1),
            "conditional_two_sided_pct": round(r_cond * 100, 1),
            "included": included,
        })
    out = pd.DataFrame(rows).sort_values(
        ["included", "conditional_two_sided_pct"], ascending=[False, False]
    ).reset_index(drop=True)
    return out


def global_cycle_grid(panel: Panel) -> pd.DatetimeIndex:
    """Sorted unique daemon cycle timestamps in the frozen set, EXCLUDING the
    10.1h outage. Daemon-down periods are absent here -> show as >tolerance gaps."""
    df = panel._load()
    lo, hi = OUTAGE_10H
    ts = df.loc[~((df["ts"] > lo) & (df["ts"] < hi)), "ts"]
    return pd.DatetimeIndex(sorted(ts.unique()))
