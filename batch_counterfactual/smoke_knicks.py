"""Smoke test: rebuild the NYK (Knicks) crossed window THROUGH the book layer.

Unlike `spike_knicks.py` (which reads raw rows straight into a figure), this
reconstructs every cycle's cross-venue book via `book.paired_state` — i.e. it
exercises the Phase-1 layer end to end — and asserts the result matches the
published / audited finding (DATA_AUDIT.md sec 9):

    1,749 cycles resolve on BOTH venues, 0 None inside the window,
    100.0% crossed (gross/pre-fee), median cross 0.50c, max 1.5c.

The only direct panel access is reading the cycle TIMESTAMPS (the time grid) for
the window; all book values flow through `book.paired_state` / `book.cross_size`.

Run:
    uv run python batch_counterfactual/smoke_knicks.py
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

import book  # noqa: E402
from fees import Tier  # noqa: E402

MARKET = "nba_finals_nyk"
WIN_LO = pd.Timestamp("2026-05-28T04:01:00Z")
WIN_HI = pd.Timestamp("2026-05-28T18:52:00Z")

# Published / audited expectations (DATA_AUDIT.md sec 9 + spike_knicks.py).
EXP_CYCLES = 1749
EXP_FRAC_CROSSED = 100.0
EXP_MEDIAN_C = 0.50
EXP_MAX_C = 1.5


def window_cycle_timestamps() -> list[pd.Timestamp]:
    """Distinct cycle timestamps (time grid only) for NYK in the window."""
    df = pd.read_csv(book.PANEL_CSV, usecols=["utc_ts", "market_id", "venue"])
    ts = pd.to_datetime(df["utc_ts"], utc=True, errors="coerce")
    mask = ((df["market_id"] == MARKET) & (df["venue"] == "kalshi_yes")
            & (ts >= WIN_LO) & (ts <= WIN_HI))
    return sorted(pd.Series(ts[mask]).dropna().unique())


def main() -> int:
    panel = book.Panel()  # default frozen panel
    cycles = window_cycle_timestamps()

    resolved = 0
    none_count = 0
    crosses_c: list[float] = []
    for t in cycles:
        pair = panel.paired_state(MARKET, t)
        if pair is None:
            none_count += 1
            continue
        resolved += 1
        c = book.cross_size(pair, Tier.ZERO)   # gross pre-fee cross, cents
        crosses_c.append(float(c))

    n = len(crosses_c)
    frac_crossed = 100.0 * sum(1 for c in crosses_c if c > 0) / n if n else 0.0
    median_c = statistics.median(crosses_c) if crosses_c else float("nan")
    max_c = max(crosses_c) if crosses_c else float("nan")

    print("=" * 66)
    print("NYK Knicks-window smoke test — rebuilt THROUGH book.paired_state")
    print("=" * 66)
    print(f"  window           : {WIN_LO} -> {WIN_HI}")
    print(f"  cycles in grid   : {len(cycles)}")
    print(f"  resolved (paired): {resolved}")
    print(f"  None inside window: {none_count}")
    print(f"  fraction crossed : {frac_crossed:.1f}%")
    print(f"  median cross     : {median_c:.2f}c")
    print(f"  max cross        : {max_c:.2f}c")
    print("-" * 66)

    checks = {
        "1,749 cycles resolve": resolved == EXP_CYCLES and len(cycles) == EXP_CYCLES,
        "0 None inside window": none_count == 0,
        "100.0% crossed gross": abs(frac_crossed - EXP_FRAC_CROSSED) < 1e-9,
        "median cross 0.50c": abs(median_c - EXP_MEDIAN_C) < 1e-9,
        "max cross 1.5c": abs(max_c - EXP_MAX_C) < 1e-9,
    }
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print("-" * 66)

    if all(checks.values()):
        print("  AGREES with spike_knicks.py / DATA_AUDIT.md sec 9.")
        return 0
    print("  *** DISAGREES — layer output diverges from the audited finding. ***")
    return 1


if __name__ == "__main__":
    sys.exit(main())
