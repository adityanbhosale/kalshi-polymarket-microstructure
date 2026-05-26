"""
Compute cross-venue arb across all markets in markets.yaml.

Usage:
  uv run python scripts/compute_arb.py              # uses most recent snapshot
  uv run python scripts/compute_arb.py --fresh      # re-fetches before computing
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from pm_micro.arb import (
    compute_crossed_book_arb_direct,
    compute_crossed_book_arb_synthetic,
    compute_executable_arb_direct,
    compute_executable_arb_synthetic,
    compute_mid_discrepancy,
)
from pm_micro.clients import kalshi, polymarket
from pm_micro.normalize import (
    normalize_kalshi_orderbook,
    normalize_polymarket_orderbook,
)

REPO_ROOT = Path(__file__).parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_most_recent_snapshot() -> Path:
    """Find the most recent snapshot directory under data/raw/."""
    candidates = sorted(RAW_DIR.glob("snapshot_*"))
    if not candidates:
        raise RuntimeError("No snapshots found. Run scripts/fetch_snapshot.py first.")
    return candidates[-1]


class _BookShim:
    """Mimic the Polymarket OrderBookSummary structure from a saved JSON dict."""
    def __init__(self, d: dict):
        self.bids = [type("L", (), x) for x in d.get("bids", [])]
        self.asks = [type("L", (), x) for x in d.get("asks", [])]


def load_books_from_snapshot(snapshot_dir: Path, market: dict):
    """Load Kalshi and Polymarket books from disk for a single market."""
    mid = market["id"]
    fetched_at = "from_disk"

    with open(snapshot_dir / f"{mid}_kalshi.json") as f:
        raw_k = json.load(f)
    k_yes, k_no = normalize_kalshi_orderbook(raw_k, mid, fetched_at)

    with open(snapshot_dir / f"{mid}_polymarket_yes.json") as f:
        raw_pyes = json.load(f)
    p_yes = normalize_polymarket_orderbook(_BookShim(raw_pyes), mid, "yes", fetched_at)

    p_no = None
    no_path = snapshot_dir / f"{mid}_polymarket_no.json"
    if no_path.exists():
        with open(no_path) as f:
            raw_pno = json.load(f)
        p_no = normalize_polymarket_orderbook(_BookShim(raw_pno), mid, "no", fetched_at)

    return k_yes, p_yes, p_no


def fetch_books_fresh(market: dict):
    """Fetch fresh books from APIs."""
    mid = market["id"]
    fetched_at = utc_now()

    raw_k = kalshi.get_orderbook(market["kalshi"]["ticker"])
    k_yes, k_no = normalize_kalshi_orderbook(raw_k, mid, fetched_at)
    time.sleep(1)

    raw_pyes = polymarket.get_orderbook(market["polymarket"]["yes_token_id"])
    p_yes = normalize_polymarket_orderbook(raw_pyes, mid, "yes", fetched_at)
    time.sleep(1)

    p_no = None
    if market["polymarket"].get("no_token_orderbook_status") != "404_unlisted":
        try:
            raw_pno = polymarket.get_orderbook(market["polymarket"]["no_token_id"])
            p_no = normalize_polymarket_orderbook(raw_pno, mid, "no", fetched_at)
        except Exception as e:
            print(f"  ⚠ Polymarket NO fetch failed for {mid}: {e}")
    time.sleep(1)

    return k_yes, p_yes, p_no


def main(fresh: bool = False):
    with open(REPO_ROOT / "markets.yaml") as f:
        markets = yaml.safe_load(f)

    snapshot_dir = None
    if fresh:
        print("Fetching fresh data from APIs...")
        # Load snapshot dir lazily so we have a fallback target for fresh failures.
        try:
            snapshot_dir = find_most_recent_snapshot()
            print(f"Snapshot fallback available at {snapshot_dir}")
        except RuntimeError:
            print("⚠ No snapshot fallback available — fresh fetch failures will be skipped.")
    else:
        snapshot_dir = find_most_recent_snapshot()
        print(f"Using snapshot at {snapshot_dir}")

    rows = []
    for market in markets:
        mid = market["id"]
        print(f"\n=== {mid} ===")
        source = "snapshot"
        try:
            if fresh:
                try:
                    k_yes, p_yes, p_no = fetch_books_fresh(market)
                    source = "fresh"
                except Exception as e:
                    print(f"  ⚠ Fresh fetch failed for {mid}: {e}")
                    if snapshot_dir is None:
                        print(f"  ❌ No snapshot fallback for {mid}; skipping.")
                        continue
                    print(f"  ↳ Falling back to snapshot data for {mid}")
                    k_yes, p_yes, p_no = load_books_from_snapshot(snapshot_dir, market)
                    source = "snapshot_fallback"
            else:
                k_yes, p_yes, p_no = load_books_from_snapshot(snapshot_dir, market)
        except Exception as e:
            print(f"  ❌ Failed to load books: {e}")
            continue

        md = compute_mid_discrepancy(k_yes, p_yes, p_no, mid)
        cb_direct = compute_crossed_book_arb_direct(k_yes, p_yes, mid)
        cb_synth = compute_crossed_book_arb_synthetic(k_yes, p_no, mid)
        ex_direct = compute_executable_arb_direct(k_yes, p_yes, mid)
        ex_synth = compute_executable_arb_synthetic(k_yes, p_no, mid)

        row = {
            "market_id": mid,
            "data_source": source,
            "kalshi_mid": md.kalshi_mid,
            "polymarket_yes_mid": md.polymarket_yes_mid,
            "polymarket_no_mid": md.polymarket_no_mid,
            "discrepancy_direct_cents": md.discrepancy_direct_cents,
            "discrepancy_synthetic_cents": md.discrepancy_synthetic_cents,
            "crossed_direct": cb_direct.crossed,
            "crossed_direct_lockable_cents": cb_direct.lockable_spread_cents,
            "crossed_synthetic": cb_synth.crossed,
            "crossed_synthetic_lockable_cents": cb_synth.lockable_spread_cents,
            "exec_direct_fillable_size": ex_direct.fillable_size,
            "exec_direct_net_profit": ex_direct.net_profit_dollars,
            "exec_direct_per_contract": ex_direct.net_profit_per_contract,
            "exec_synthetic_fillable_size": ex_synth.fillable_size,
            "exec_synthetic_net_profit": ex_synth.net_profit_dollars,
            "exec_synthetic_per_contract": ex_synth.net_profit_per_contract,
        }
        rows.append(row)

        if md.discrepancy_direct_cents is not None:
            synth_str = f"{md.discrepancy_synthetic_cents:.2f}¢" if md.discrepancy_synthetic_cents is not None else "n/a"
            print(f"  mid_disc direct={md.discrepancy_direct_cents:.2f}¢  synthetic={synth_str}")
        else:
            print("  mid_disc incomplete")
        print(f"  crossed direct={cb_direct.crossed}  synthetic={cb_synth.crossed}")
        print(f"  exec direct: size={ex_direct.fillable_size:.0f} net=${ex_direct.net_profit_dollars:.2f}")
        print(f"  exec synthetic: size={ex_synth.fillable_size:.0f} net=${ex_synth.net_profit_dollars:.2f}")
        if source != "fresh" and fresh:
            print(f"  (data source: {source})")

    df = pd.DataFrame(rows)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "_fresh" if fresh else ""
    outpath = PROCESSED_DIR / f"arb_results{suffix}.csv"
    df.to_csv(outpath, index=False)
    print(f"\n✅ Wrote {len(rows)} rows to {outpath}")

    if fresh:
        ledger_path = REPO_ROOT / "data" / "processed" / "snapshot_ledger.yaml"
        ledger = []
        if ledger_path.exists():
            with open(ledger_path) as f:
                ledger = yaml.safe_load(f) or []

        okc_row = next((r for r in rows if r["market_id"] == "nba_finals_okc"), None)
        nyk_row = next((r for r in rows if r["market_id"] == "nba_finals_nyk"), None)

        if okc_row:
            new_entry = {
                "timestamp_utc": utc_now(),
                "source": "compute_arb_fresh",
                "okc_kalshi_mid": float(okc_row["kalshi_mid"]) if okc_row.get("kalshi_mid") is not None else None,
                "okc_polymarket_yes_mid": float(okc_row["polymarket_yes_mid"]) if okc_row.get("polymarket_yes_mid") is not None else None,
                "okc_discrepancy_cents": float(okc_row["discrepancy_direct_cents"]) if okc_row.get("discrepancy_direct_cents") is not None else None,
                "nyk_polymarket_yes_status": (
                    "404" if (nyk_row is None
                              or nyk_row.get("polymarket_yes_mid") is None
                              or nyk_row.get("data_source") == "snapshot_fallback")
                    else "active"
                ),
                "notes": "Auto-appended by compute_arb.py --fresh",
            }
            ledger.append(new_entry)
            with open(ledger_path, "w") as f:
                yaml.dump(ledger, f, sort_keys=False, default_flow_style=False)
            print(f"\nAppended entry to {ledger_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true", help="Re-fetch from APIs instead of using snapshot")
    args = parser.parse_args()
    main(fresh=args.fresh)
