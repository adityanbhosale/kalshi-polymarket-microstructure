"""
Fetch orderbook snapshots from both venues for every market in markets.yaml.
Normalize, compute microstructure metrics, write to data/raw/ (raw snapshots)
and data/processed/ (CSV of metrics).

Usage: uv run python scripts/fetch_snapshot.py
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from pm_micro.clients import kalshi, polymarket
from pm_micro.microstructure import compute_microstructure
from pm_micro.normalize import (
    normalize_kalshi_orderbook,
    normalize_polymarket_orderbook,
)

REPO_ROOT = Path(__file__).parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main():
    with open(REPO_ROOT / "markets.yaml") as f:
        markets = yaml.safe_load(f)

    snapshot_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = RAW_DIR / f"snapshot_{snapshot_ts}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    all_metrics = []

    for m in markets:
        print(f"\n=== {m['id']} ===")
        fetched_at = utc_now()

        # KALSHI
        try:
            raw_kalshi = kalshi.get_orderbook(m['kalshi']['ticker'])
            with open(snapshot_dir / f"{m['id']}_kalshi.json", "w") as f:
                json.dump(raw_kalshi, f, indent=2)
            yes_book, no_book = normalize_kalshi_orderbook(
                raw_kalshi, m['id'], fetched_at
            )
            yes_metrics = compute_microstructure(yes_book)
            no_metrics = compute_microstructure(no_book)
            all_metrics.append(yes_metrics.to_dict())
            all_metrics.append(no_metrics.to_dict())
            if yes_metrics.spread_bps is not None:
                print(f"  Kalshi YES: bid={yes_metrics.best_bid} ask={yes_metrics.best_ask} spread_bps={yes_metrics.spread_bps:.0f}")
            else:
                print("  Kalshi YES: incomplete book")
        except Exception as e:
            print(f"  ❌ Kalshi {m['kalshi']['ticker']}: {e}")

        time.sleep(1)

        # POLYMARKET - YES token
        try:
            raw_yes = polymarket.get_orderbook(m['polymarket']['yes_token_id'])
            with open(snapshot_dir / f"{m['id']}_polymarket_yes.json", "w") as f:
                json.dump({
                    "bids": [{"price": b.price, "size": b.size} for b in (raw_yes.bids or [])],
                    "asks": [{"price": a.price, "size": a.size} for a in (raw_yes.asks or [])],
                }, f, indent=2)
            yes_pm_book = normalize_polymarket_orderbook(raw_yes, m['id'], "yes", fetched_at)
            yes_pm_metrics = compute_microstructure(yes_pm_book)
            all_metrics.append(yes_pm_metrics.to_dict())
            if yes_pm_metrics.spread_bps is not None:
                print(f"  Polymarket YES: bid={yes_pm_metrics.best_bid} ask={yes_pm_metrics.best_ask} spread_bps={yes_pm_metrics.spread_bps:.0f}")
            else:
                print("  Polymarket YES: incomplete book")
        except Exception as e:
            print(f"  ❌ Polymarket YES: {e}")

        time.sleep(1)

        # POLYMARKET - NO token
        try:
            raw_no = polymarket.get_orderbook(m['polymarket']['no_token_id'])
            with open(snapshot_dir / f"{m['id']}_polymarket_no.json", "w") as f:
                json.dump({
                    "bids": [{"price": b.price, "size": b.size} for b in (raw_no.bids or [])],
                    "asks": [{"price": a.price, "size": a.size} for a in (raw_no.asks or [])],
                }, f, indent=2)
            no_pm_book = normalize_polymarket_orderbook(raw_no, m['id'], "no", fetched_at)
            no_pm_metrics = compute_microstructure(no_pm_book)
            all_metrics.append(no_pm_metrics.to_dict())
            if no_pm_metrics.spread_bps is not None:
                print(f"  Polymarket NO: bid={no_pm_metrics.best_bid} ask={no_pm_metrics.best_ask} spread_bps={no_pm_metrics.spread_bps:.0f}")
            else:
                print("  Polymarket NO: incomplete book")
        except Exception as e:
            print(f"  ❌ Polymarket NO: {e}")

        time.sleep(1)

    df = pd.DataFrame(all_metrics)
    summary_path = PROCESSED_DIR / "microstructure_snapshot.csv"
    df.to_csv(summary_path, index=False)
    print(f"\n✅ Wrote {len(all_metrics)} rows to {summary_path}")
    print(f"✅ Raw snapshots in {snapshot_dir}")


if __name__ == "__main__":
    main()
