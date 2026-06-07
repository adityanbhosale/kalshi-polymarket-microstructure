"""Arm A — SIZE-WEIGHTED first-clearance on extracted ladders (Phase 3).

Where per-episode gz ladders exist (extract_ladders.py), build real cross-venue
Orders from EVERY YES-side level on BOTH venues and run the full uniform-price
call auction (auction.clear, joint) under BOTH objectives x all fee tiers.

This is the SIZE-WEIGHTED companion to the per-contract first-clearance in
arm_a_clearance.py. Outputs are labelled metric='size_weighted' and must never be
mixed with per-contract numbers without that column.

Performance: the full ladders span the whole [0,1] grid, but only orders inside
the gross crossing band [lowest_ask, highest_bid] can participate at any in-band
uniform clearing price. We prune to that band before clearing — this never drops
a participant (fee-feasibility is still checked inside clear()), only the deep,
non-crossing levels that contribute zero volume at the optimum.

$ PI inherits the published normalizer's size convention (src/pm_micro/normalize.py
treats Kalshi `*_dollars` level sizes as the contract-size field). Polymarket sizes
are shares. Kalshi `*_dollars` may be notional rather than contracts, so absolute
size-weighted $ are convention-dependent and labelled accordingly; executable
CONTRACTS and clearing PRICES are robust to that ambiguity.

Output: results/arm_a/sized_clearance.parquet
  one row per (episode x tier): clearing price / executable contracts / $ PI for
  each objective + objective_disagree flag.

Run:
    uv run python batch_counterfactual/arms/arm_a_sized.py
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from _common import FEE_CATEGORY, INCLUDED_PAIRS, LADDERS, RESULTS
from auction import Order, clear
from fees import Tier

TIERS: list[tuple[str, Tier]] = [
    ("gross", Tier.ZERO),
    ("retail", Tier.RETAIL),
    ("retail_pm_rebate", Tier.RETAIL_PM_REBATE),
    ("institutional", Tier.INSTITUTIONAL),
]
OBJECTIVES = ("max_volume", "max_agg_pi")


def _orders_from_ladder(lad: pd.DataFrame) -> list[Order]:
    """All YES-side levels (both venues) -> resting Orders. side: bid->buy, ask->sell."""
    orders: list[Order] = []
    for r in lad.itertuples(index=False):
        side = "buy" if r.side == "bid" else "sell"
        oid = f"{r.venue}-{r.side}-{r.level}"
        orders.append(Order(oid, r.venue, r.venue, side,
                            Decimal(str(r.price)), Decimal(str(r.qty))))
    return orders


def _prune_to_band(orders: list[Order]) -> list[Order]:
    """Keep only orders that can participate at some in-band clearing price.

    band_hi = highest buy limit, band_lo = lowest sell limit. A buy below band_lo
    (resp. a sell above band_hi) cannot trade at any p in [band_lo, band_hi].
    """
    buys = [o for o in orders if o.side == "buy"]
    sells = [o for o in orders if o.side == "sell"]
    if not buys or not sells:
        return []
    band_hi = max(o.price for o in buys)
    band_lo = min(o.price for o in sells)
    if band_lo > band_hi:
        return []  # gross-uncrossed: no in-band volume
    return ([o for o in buys if o.price >= band_lo]
            + [o for o in sells if o.price <= band_hi])


def main() -> int:
    ep = pd.read_parquet(RESULTS / "episodes.parquet")
    episodes = (ep.drop_duplicates("episode_id")[["episode_id", "pair", "start_ts",
                                                   "duration_s", "duration_bucket",
                                                   "max_gross_c"]]
                .reset_index(drop=True))

    ladders: dict[str, pd.DataFrame] = {}
    for pair in INCLUDED_PAIRS:
        path = LADDERS / f"{pair}.parquet"
        if path.exists():
            ladders[pair] = pd.read_parquet(path)

    rows: list[dict] = []
    n_cleared = n_disagree = 0
    for e in episodes.itertuples(index=False):
        lad = ladders.get(e.pair)
        rec_base = {
            "episode_id": e.episode_id, "pair": e.pair, "start_ts": e.start_ts,
            "duration_s": e.duration_s, "duration_bucket": e.duration_bucket,
            "max_gross_c": e.max_gross_c, "metric": "size_weighted",
        }
        if lad is None:
            continue
        snap = lad[lad["ts"] == pd.Timestamp(e.start_ts)]
        if snap.empty:
            continue
        orders = _prune_to_band(_orders_from_ladder(snap))
        cat = FEE_CATEGORY[e.pair]
        for tlabel, tier in TIERS:
            rec = dict(rec_base)
            rec["tier"] = tlabel
            prices: dict[str, Decimal | None] = {}
            for obj in OBJECTIVES:
                res = clear(orders, obj, tier, category=cat) if orders else None
                tag = "vol" if obj == "max_volume" else "pi"
                if res is None or res.clearing_price is None:
                    rec[f"clearing_price_{tag}"] = None
                    rec[f"contracts_{tag}"] = 0.0
                    rec[f"pi_usd_{tag}"] = 0.0
                    prices[tag] = None
                else:
                    rec[f"clearing_price_{tag}"] = float(res.clearing_price)
                    rec[f"contracts_{tag}"] = float(res.total_qty)
                    rec[f"pi_usd_{tag}"] = float(res.agg_pi)
                    prices[tag] = res.clearing_price
            cp_v, cp_p = prices.get("vol"), prices.get("pi")
            disagree = (cp_v is not None and cp_p is not None and cp_v != cp_p)
            rec["objective_disagree"] = bool(disagree)
            rec["clearable"] = bool(rec["contracts_vol"] > 0)
            if tlabel == "gross" and rec["clearable"]:
                n_cleared += 1
            if disagree:
                n_disagree += 1
            rows.append(rec)

    out = pd.DataFrame(rows)
    out.to_parquet(RESULTS / "sized_clearance.parquet", index=False)

    # Quick per-tier headline (size-weighted, all episodes with ladders).
    print("=" * 72)
    print("ARM A — size-weighted clearance (extracted ladders)")
    print("=" * 72)
    print(f"  episodes with ladders : {out['episode_id'].nunique()}")
    print(f"  gross-clearable starts: {n_cleared}")
    for tlabel, _ in TIERS:
        sub = out[out["tier"] == tlabel]
        frac = (sub["clearable"].mean() if len(sub) else 0.0)
        med_ctr = sub.loc[sub["clearable"], "contracts_vol"].median() if sub["clearable"].any() else 0.0
        med_pi = sub.loc[sub["clearable"], "pi_usd_vol"].median() if sub["clearable"].any() else 0.0
        print(f"    {tlabel:18s} clearable={frac:6.3f}  "
              f"median contracts(vol)={med_ctr:,.0f}  median $PI(vol)={med_pi:,.2f}")
    print(f"  objective-disagreement rows: {n_disagree}")
    print(f"  wrote sized_clearance.parquet ({len(out)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
