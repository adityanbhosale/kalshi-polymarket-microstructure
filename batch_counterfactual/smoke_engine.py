"""Smoke test: auction engine tie-out on the frozen Knicks window.

Runs ``clearance_bounds`` at every panel cycle via ``book.paired_state`` (no raw
row access for book values). Reports tier-by-tier clearable fractions and
per-contract PI; compares against DATA_AUDIT.md sec 9 and the published Part 1
no-takeable-arb finding.

Run:
    uv run python batch_counterfactual/smoke_engine.py
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

import book  # noqa: E402
from auction import clearance_bounds  # noqa: E402
from fees import Tier  # noqa: E402

MARKET = "nba_finals_nyk"
WIN_LO = pd.Timestamp("2026-05-28T04:01:00Z")
WIN_HI = pd.Timestamp("2026-05-28T18:52:00Z")
PM_CATEGORY = "sports"   # nba_finals_nyk


def window_cycle_timestamps() -> list[pd.Timestamp]:
    df = pd.read_csv(book.PANEL_CSV, usecols=["utc_ts", "market_id", "venue"])
    ts = pd.to_datetime(df["utc_ts"], utc=True, errors="coerce")
    mask = ((df["market_id"] == MARKET) & (df["venue"] == "kalshi_yes")
            & (ts >= WIN_LO) & (ts <= WIN_HI))
    return sorted(pd.Series(ts[mask]).dropna().unique())


def run_tier(panel: book.Panel, tier: Tier) -> dict:
    cycles = window_cycle_timestamps()
    pis_k: list[float] = []
    pis_p: list[float] = []
    clearable = 0
    fee_blocked = 0
    gross_uncrossed = 0
    none_count = 0

    for t in cycles:
        pair = panel.paired_state(MARKET, t)
        if pair is None:
            none_count += 1
            continue
        r = clearance_bounds(pair[0], pair[1], tier, category=PM_CATEGORY)
        if r.clearable:
            clearable += 1
            if r.pi_kalshi_c is not None:
                pis_k.append(float(r.pi_kalshi_c))
            if r.pi_polymarket_c is not None:
                pis_p.append(float(r.pi_polymarket_c))
        elif r.not_clearable:
            if r.not_clearable.reason == "fee_blocked":
                fee_blocked += 1
            else:
                gross_uncrossed += 1

    n = len(cycles) - none_count
    frac = 100.0 * clearable / n if n else 0.0
    med_k = statistics.median(pis_k) if pis_k else float("nan")
    med_p = statistics.median(pis_p) if pis_p else float("nan")
    return {
        "cycles": len(cycles),
        "resolved": n,
        "none": none_count,
        "clearable": clearable,
        "frac_clearable_pct": frac,
        "fee_blocked": fee_blocked,
        "gross_uncrossed": gross_uncrossed,
        "median_pi_k_c": med_k,
        "median_pi_p_c": med_p,
    }


def main() -> int:
    panel = book.Panel()
    tiers = [
        ("ZERO (gross)", Tier.ZERO),
        ("RETAIL", Tier.RETAIL),
        ("RETAIL_PM_REBATE", Tier.RETAIL_PM_REBATE),
        ("INSTITUTIONAL", Tier.INSTITUTIONAL),
    ]

    print("=" * 72)
    print("NYK engine smoke — clearance_bounds tier-by-tier")
    print("=" * 72)
    print(f"  window: {WIN_LO} -> {WIN_HI}")
    print()
    print(f"  {'tier':22s} {'clearable%':>10s} {'med PI_K':>9s} {'med PI_P':>9s} "
          f"{'fee_blk':>8s} {'gross_unc':>9s}")
    print("  " + "-" * 68)

    results: dict[str, dict] = {}
    for label, tier in tiers:
        s = run_tier(panel, tier)
        results[label] = s
        print(f"  {label:22s} {s['frac_clearable_pct']:9.1f}% "
              f"{s['median_pi_k_c']:9.2f}c {s['median_pi_p_c']:9.2f}c "
              f"{s['fee_blocked']:8d} {s['gross_uncrossed']:9d}")

    print("-" * 72)

    gross = results["ZERO (gross)"]
    retail = results["RETAIL"]
    inst = results["INSTITUTIONAL"]

    checks = {
        "~100% gross clearable": gross["frac_clearable_pct"] >= 99.0,
        "0 None in window": gross["none"] == 0,
        "median PI ~0.25c/side (gross)": (
            abs(gross["median_pi_k_c"] - 0.25) < 0.15
            and abs(gross["median_pi_p_c"] - 0.25) < 0.15
        ),
        "retail ~0% clearable": retail["frac_clearable_pct"] <= 5.0,
        "institutional large fraction": inst["frac_clearable_pct"] >= 50.0,
    }
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    print("-" * 72)
    if all(checks.values()):
        print("  AGREES with DATA_AUDIT sec 9 + published no-takeable-arb (retail).")
        return 0
    print("  *** DISAGREES — investigate before trusting engine output. ***")
    return 1


if __name__ == "__main__":
    sys.exit(main())
