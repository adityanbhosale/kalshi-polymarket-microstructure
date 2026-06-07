"""Arm A — SCOPED raw-gz ladder extraction (decision #5, Phase 3).

For EPISODE FIRST-CYCLE timestamps ONLY (all included pairs), locate the matching
raw gz bundle and extract the FULL YES-side ladders for both venues into
results/arm_a/ladders/. We do NOT extract the full panel (1.06M rows) — only the
~1.3k episode-start snapshots Arm A actually clears.

YES-side convention + Kalshi reconstruction mirror src/pm_micro/normalize.py
VERBATIM (the published pipeline's normalizer):
  * Kalshi YES bids = orderbook_fp.yes_dollars  (price, size as-is)
  * Kalshi YES asks = {(1 - p, size) for (p, size) in orderbook_fp.no_dollars}
  * Polymarket YES bids/asks = polymarket_yes_orderbook.{bids,asks} (price, size)
Sizes are carried through unchanged (the normalizer treats Kalshi `*_dollars`
size fields as the contract-size field; we preserve that convention so sized
clearing ties out with book.py top-of-book).

Output: results/arm_a/ladders/{pair}.parquet
  columns: pair, venue, ts, side ('bid'|'ask'), level (0=best), price, qty
Plus results/arm_a/ladders/coverage.json (both-venue coverage of episode starts).

Run:
    uv run python batch_counterfactual/arms/extract_ladders.py
"""

from __future__ import annotations

import gzip
import json

import pandas as pd

from _common import INCLUDED_PAIRS, LADDERS, RESULTS, gz_path


def _kalshi_yes_ladder(kob: dict | None) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """(yes_bids, yes_asks) as sorted [(price, qty)] lists. Mirrors normalize.py."""
    if not kob:
        return [], []
    ob = kob.get("orderbook_fp") or kob.get("orderbook") or {}
    yes_bids_raw = ob.get("yes_dollars") or []
    no_bids_raw = ob.get("no_dollars") or []
    yes_bids = sorted(((float(p), float(s)) for p, s in yes_bids_raw),
                      key=lambda x: -x[0])
    yes_asks = sorted((((round(1.0 - float(p), 4)), float(s)) for p, s in no_bids_raw),
                      key=lambda x: x[0])
    return yes_bids, yes_asks


def _pm_yes_ladder(pob: dict | None) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """(bids, asks) as sorted [(price, qty)] lists from polymarket_yes_orderbook."""
    if not pob:
        return [], []
    bids = sorted(((float(b["price"]), float(b["size"])) for b in (pob.get("bids") or [])),
                  key=lambda x: -x[0])
    asks = sorted(((float(a["price"]), float(a["size"])) for a in (pob.get("asks") or [])),
                  key=lambda x: x[0])
    return bids, asks


def _rows_for(pair: str, ts: pd.Timestamp) -> tuple[list[dict], bool, bool]:
    """Extract both-venue YES ladders for one (pair, ts). Returns (rows, k_ok, p_ok)."""
    path = gz_path(pair, ts)
    if not path.exists():
        return [], False, False
    with gzip.open(path, "rt") as f:
        d = json.load(f)
    kb, ka = _kalshi_yes_ladder(d.get("kalshi_orderbook"))
    pb, pa = _pm_yes_ladder(d.get("polymarket_yes_orderbook"))
    k_ok = bool(kb and ka)
    p_ok = bool(pb and pa)
    rows: list[dict] = []
    tsv = pd.Timestamp(ts)
    for venue, bids, asks in (("kalshi", kb, ka), ("polymarket", pb, pa)):
        for lvl, (price, qty) in enumerate(bids):
            rows.append({"pair": pair, "venue": venue, "ts": tsv,
                         "side": "bid", "level": lvl, "price": price, "qty": qty})
        for lvl, (price, qty) in enumerate(asks):
            rows.append({"pair": pair, "venue": venue, "ts": tsv,
                         "side": "ask", "level": lvl, "price": price, "qty": qty})
    return rows, k_ok, p_ok


def main() -> int:
    ep = pd.read_parquet(RESULTS / "episodes.parquet")
    starts = (ep[["pair", "start_ts"]].drop_duplicates()
              .sort_values(["pair", "start_ts"]).reset_index(drop=True))

    coverage: dict[str, dict] = {}
    n_both = n_k = n_p = n_starts = 0
    for pair in INCLUDED_PAIRS:
        sub = starts[starts["pair"] == pair]
        rows: list[dict] = []
        c = {"episode_starts": int(len(sub)), "kalshi_found": 0,
             "polymarket_found": 0, "both_found": 0, "bundle_missing": 0}
        for ts in sub["start_ts"]:
            r, k_ok, p_ok = _rows_for(pair, ts)
            n_starts += 1
            if not r and not gz_path(pair, ts).exists():
                c["bundle_missing"] += 1
                continue
            rows.extend(r)
            c["kalshi_found"] += int(k_ok)
            c["polymarket_found"] += int(p_ok)
            c["both_found"] += int(k_ok and p_ok)
            n_k += int(k_ok); n_p += int(p_ok); n_both += int(k_ok and p_ok)
        if rows:
            pd.DataFrame(rows).to_parquet(LADDERS / f"{pair}.parquet", index=False)
        c["both_found_pct"] = (round(100.0 * c["both_found"] / c["episode_starts"], 1)
                               if c["episode_starts"] else 0.0)
        coverage[pair] = c

    overall = {
        "episode_starts_total": n_starts,
        "kalshi_found": n_k, "polymarket_found": n_p, "both_found": n_both,
        "both_found_pct": round(100.0 * n_both / n_starts, 1) if n_starts else 0.0,
    }
    (LADDERS / "coverage.json").write_text(
        json.dumps({"overall": overall, "per_pair": coverage}, indent=2)
    )

    print("=" * 72)
    print("ARM A — scoped gz ladder extraction")
    print("=" * 72)
    print(f"  episode starts        : {n_starts}")
    print(f"  both-venue ladders    : {n_both}  ({overall['both_found_pct']}%)")
    print(f"  kalshi-only found     : {n_k}   polymarket found: {n_p}")
    print(f"  wrote ladders/*.parquet ({len([p for p in coverage if coverage[p]['both_found']])} pairs)"
          f" + coverage.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
