"""Day-1 health check for ``scripts/poll_timeofday.py``.

Reads ``data/processed/timeofday_poll.csv`` and reports:

  * total rows, distinct snapshots (``utc_ts`` count), wall-clock span
  * rows-per-market (min/max/median across the 16 markets)
  * real-error rate, excluding ``expected_404`` (CLE/NYK delisted books
    are pre-documented in markets.yaml and shouldn't drive the rate)
  * largest gap between two consecutive snapshots (catches missed cycles)
  * last successful ``utc_ts`` and minutes since now

Exits 1 if no rows in the last ``STALL_THRESHOLD_MIN`` minutes — that's
the "poller is dead" alarm. Otherwise exits 0.

Usage:
    uv run python scripts/check_poll_health.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
CSV_PATH = REPO_ROOT / "data" / "processed" / "timeofday_poll.csv"
STALL_THRESHOLD_MIN = 5


def main() -> int:
    if not CSV_PATH.exists():
        print(f"❌ {CSV_PATH} does not exist; poller has not produced any data yet")
        return 1

    df = pd.read_csv(CSV_PATH)
    if df.empty:
        print(f"❌ {CSV_PATH} exists but contains no rows")
        return 1

    df["utc_ts"] = pd.to_datetime(df["utc_ts"], utc=True, format="ISO8601")
    snapshots = sorted(df["utc_ts"].unique())
    n_rows = len(df)
    n_snapshots = len(snapshots)
    span = snapshots[-1] - snapshots[0]
    rows_per_market = df.groupby("market_id").size().sort_values()

    expected_404_mask = df["error"].fillna("") == "expected_404"
    real_errors = df[df["error"].notna() & ~expected_404_mask]
    real_err_rate = len(real_errors) / n_rows if n_rows else 0.0

    if n_snapshots > 1:
        ts_series = pd.Series(pd.to_datetime(snapshots, utc=True))
        gaps = ts_series.diff().dropna()
        largest_gap = gaps.max()
        median_gap = gaps.median()
    else:
        largest_gap = timedelta(0)
        median_gap = timedelta(0)

    last_ts = pd.Timestamp(snapshots[-1])
    minutes_since = (datetime.now(timezone.utc) - last_ts.to_pydatetime()).total_seconds() / 60.0

    print(f"=== Poller health ({CSV_PATH.name}) ===")
    print(f"  total rows:                      {n_rows:,}")
    print(f"  distinct snapshots:              {n_snapshots:,}")
    print(f"  wall-clock span:                 {span}")
    print(
        f"  rows/market (min/median/max):    "
        f"{int(rows_per_market.min())} / {int(rows_per_market.median())} / "
        f"{int(rows_per_market.max())}  (across {rows_per_market.size} markets)"
    )
    print(
        f"  real-error rate (excl. expected_404): "
        f"{len(real_errors):,}/{n_rows:,} = {real_err_rate:.2%}"
    )
    if not real_errors.empty:
        top = real_errors["error"].value_counts().head(5)
        for err, cnt in top.items():
            err_str = str(err)
            print(f"      {cnt}× {err_str[:80]}")
    print(f"  median gap between snapshots:    {median_gap}")
    print(f"  largest gap between snapshots:   {largest_gap}")
    print(f"  last successful utc_ts:          {last_ts.isoformat()}")
    print(f"  minutes since last snapshot:     {minutes_since:.2f}")

    if minutes_since > STALL_THRESHOLD_MIN:
        print(
            f"\n❌ STALLED — no rows in the last {STALL_THRESHOLD_MIN} min "
            f"(last snapshot {minutes_since:.1f} min ago). "
            "Check `logs/poll.err` and `launchctl list | grep pmmicro`."
        )
        return 1
    print("\n✅ poller healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
