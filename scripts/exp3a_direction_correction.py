"""EXP-3a Direction-Correction (post-review fix).

Scenarios C (mixed) and D (both-maker) in the original exp3a output
assumed maker fees on whichever leg the FeeContext said was 'maker',
regardless of the trade direction. That's incoherent: on a crossed
book, the natural take-take execution lifts BOTH inside quotes — both
legs are TAKER. Maker execution is only available on the side you ADD
liquidity to (post a passive order, wait for incoming flow), not on
the side you cross.

This script reclassifies, per market with a C or D flip, which leg
is add-side (maker-eligible) and which is cross-side (taker-forced)
under the actual trade direction, then recomputes the per-contract
edge. Markets that require an add-side leg to capture the edge are
re-verdicted as "provideable / fill-unconfirmed" — the per-contract
edge is real but the dollar figure depends on flow that lifts the
posted order, not on the resting depth the original walker used.

Read-only against snapshot books and metadata; output is a single
markdown file.

Usage:
    uv run python scripts/exp3a_direction_correction.py
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pm_micro.fees import kalshi_fee, polymarket_fee  # noqa: E402
from pm_micro.normalize import (  # noqa: E402
    normalize_kalshi_orderbook,
    normalize_polymarket_orderbook,
)

MARKETS_YAML = ROOT / "markets.yaml"
FEE_META_YAML = ROOT / "data" / "processed" / "market_fee_metadata.yaml"
RAW_DIR = ROOT / "data" / "raw"
OUT_MD = ROOT / "data" / "processed" / "exp3a_direction_correction.md"

# The 7 D-flips + 1 C-flip from exp3a_fee_correction.md
FLIPPED_MARKETS = [
    "sports_retirement_arod",       # both C and D flip
    "sports_retirement_kelce",      # D only
    "intl_president_co_aesp",       # D only
    "intl_president_co_pval",       # D only
    "intl_president_pe_rpal",       # D only
    "intl_mayor_kr_oseh",           # D only
    "us_mayor_la_kbas",             # D only
]
# (No need to enumerate ARod twice; C and D flips are both on ARod
# plus the 6 other D-only flips, for 8 (market, scenario) pairs.)


class _BookShim:
    def __init__(self, d: dict):
        self.bids = [type("L", (), x) for x in d.get("bids", [])]
        self.asks = [type("L", (), x) for x in d.get("asks", [])]


def load_books(snapshot_dir: Path, market_id: str):
    with open(snapshot_dir / f"{market_id}_kalshi.json") as f:
        raw_k = json.load(f)
    k_yes, _ = normalize_kalshi_orderbook(raw_k, market_id, "from_disk")
    with open(snapshot_dir / f"{market_id}_polymarket_yes.json") as f:
        raw_pyes = json.load(f)
    p_yes = normalize_polymarket_orderbook(
        _BookShim(raw_pyes), market_id, "yes", "from_disk"
    )
    p_no = None
    pno_path = snapshot_dir / f"{market_id}_polymarket_no.json"
    if pno_path.exists():
        with open(pno_path) as f:
            raw_pno = json.load(f)
        p_no = normalize_polymarket_orderbook(
            _BookShim(raw_pno), market_id, "no", "from_disk"
        )
    return k_yes, p_yes, p_no


@dataclass
class TradeDirection:
    """A direct cross-venue arb's leg layout at top-of-book."""
    buy_venue: Literal["kalshi", "polymarket"]
    buy_price: float
    buy_size: float
    sell_venue: Literal["kalshi", "polymarket"]
    sell_price: float
    sell_size: float
    paper_spread_cents: float

    def desc(self) -> str:
        return (
            f"BUY {self.buy_venue} @ {self.buy_price:.4f} (size {self.buy_size:.0f}) | "
            f"SELL {self.sell_venue} @ {self.sell_price:.4f} (size {self.sell_size:.0f})"
        )


def classify_direction(k_yes, p_yes) -> TradeDirection | None:
    """Return the natural take-take direction if the book is crossed, else None."""
    if not (k_yes.asks and k_yes.bids and p_yes.bids and p_yes.asks):
        return None
    k_ask, k_ask_sz = k_yes.asks[0].price, k_yes.asks[0].size
    k_bid, k_bid_sz = k_yes.bids[0].price, k_yes.bids[0].size
    p_ask, p_ask_sz = p_yes.asks[0].price, p_yes.asks[0].size
    p_bid, p_bid_sz = p_yes.bids[0].price, p_yes.bids[0].size
    if p_bid > k_ask:
        return TradeDirection("kalshi", k_ask, k_ask_sz, "polymarket", p_bid, p_bid_sz,
                              paper_spread_cents=100 * (p_bid - k_ask))
    if k_bid > p_ask:
        return TradeDirection("polymarket", p_ask, p_ask_sz, "kalshi", k_bid, k_bid_sz,
                              paper_spread_cents=100 * (k_bid - p_ask))
    return None


def per_contract_edge(
    direction: TradeDirection,
    k_multiplier: float,
    k_maker_fraction: float,
    pm_rate: float,
    pm_rebate_fraction: float,
    scenario: Literal["B_CORR_TAKER", "C_MIXED_DIR", "D_BOTH_MAKER_DIR"],
    use_rebate: bool = True,
) -> tuple[float, dict]:
    """Return (per_contract_edge_dollars, leg_breakdown).

    Direction-enforced: for any leg that is "maker" under the scenario,
    the strategy must POST passive on that side at the cross-side venue's
    counterpart price. PM maker = post limit at PM's inside quote (sell-
    ask or buy-bid). Kalshi maker = post limit at K's inside quote.
    """
    if scenario == "B_CORR_TAKER":
        k_mode, pm_mode = "taker", "taker"
    elif scenario == "C_MIXED_DIR":
        # PM is the add-side / maker; K is cross-side / taker.
        k_mode, pm_mode = "taker", "maker"
    elif scenario == "D_BOTH_MAKER_DIR":
        # Both legs add-side (= market-making strategy).
        k_mode, pm_mode = "maker", "maker"
    else:
        raise ValueError(scenario)

    def fee_for(venue: str, side: str, price: float, mode: str) -> float:
        if venue == "kalshi":
            return kalshi_fee(price=price, size=1.0, side=side,
                              multiplier=k_multiplier,
                              execution_mode=mode,
                              maker_fraction=k_maker_fraction)
        return polymarket_fee(price=price, size=1.0, side=side,
                              rate=pm_rate,
                              execution_mode=mode,
                              use_rebate=use_rebate,
                              rebate_fraction=pm_rebate_fraction)

    bv, bp = direction.buy_venue, direction.buy_price
    sv, sp = direction.sell_venue, direction.sell_price
    bm = k_mode if bv == "kalshi" else pm_mode
    sm = k_mode if sv == "kalshi" else pm_mode
    buy_fee = fee_for(bv, "buy", bp, bm)
    sell_fee = fee_for(sv, "sell", sp, sm)
    # Buying costs price + fee, selling yields price - fee.
    buy_cost = bp + buy_fee
    sell_proceeds = sp - sell_fee
    edge = sell_proceeds - buy_cost
    return edge, {
        "buy_leg": {
            "venue": bv, "price": bp, "mode": bm, "fee_dollars": buy_fee,
            "role": "cross-side (taker)" if bm == "taker" else "add-side (maker)",
        },
        "sell_leg": {
            "venue": sv, "price": sp, "mode": sm, "fee_dollars": sell_fee,
            "role": "cross-side (taker)" if sm == "taker" else "add-side (maker)",
        },
    }


def format_money(x: float, decimals: int = 4) -> str:
    if abs(x) < 10 ** (-decimals - 1):
        return f"${0.0:.{decimals}f}"
    return f"${x:+.{decimals}f}"


def verdict_for(edge: float, breakdown: dict) -> tuple[str, str]:
    """Return (verdict, why).

    Verdict tiers:
      - takeable: edge > 0 AND both legs cross-side (taker). Instant lock.
      - provideable, fill-unconfirmed: edge > 0 AND at least one leg add-side.
        Per-contract edge exists; size depends on flow.
      - $0 (fees eat edge): edge <= 0 even after the scenario's fee model.
    """
    any_maker = any(leg["mode"] == "maker" for leg in (breakdown["buy_leg"], breakdown["sell_leg"]))
    if edge <= 0:
        return "$0 (fees-bind)", "per-contract edge ≤ 0 after scenario fees"
    if any_maker:
        n_maker = sum(1 for leg in (breakdown["buy_leg"], breakdown["sell_leg"]) if leg["mode"] == "maker")
        return ("provideable, fill-unconfirmed",
                f"{n_maker} maker leg{'s' if n_maker > 1 else ''} — fill is flow-contingent")
    return "TAKEABLE", "both legs cross-side; instant lock"


def main() -> int:
    with open(MARKETS_YAML) as f:
        markets = yaml.safe_load(f)
    with open(FEE_META_YAML) as f:
        meta_list = yaml.safe_load(f)
    by_id = {m["id"]: m for m in markets}
    meta_by_id = {e["market_id"]: e for e in meta_list}
    snapshot_dir = sorted(RAW_DIR.glob("snapshot_*"))[-1]
    print(f"Snapshot: {snapshot_dir.name}\n")

    # (market_id, scenario_to_evaluate, original_direction_blind_$)
    # All 7 markets flip under D; only ARod also flips under C.
    flips = [
        ("sports_retirement_arod", "C_MIXED_DIR", 0.06),
        ("sports_retirement_arod", "D_BOTH_MAKER_DIR", 2.98),
        ("sports_retirement_kelce", "D_BOTH_MAKER_DIR", 0.45),
        ("intl_president_co_aesp", "D_BOTH_MAKER_DIR", 30.23),
        ("intl_president_co_pval", "D_BOTH_MAKER_DIR", 0.43),
        ("intl_president_pe_rpal", "D_BOTH_MAKER_DIR", 50.59),
        ("intl_mayor_kr_oseh", "D_BOTH_MAKER_DIR", 5.00),
        ("us_mayor_la_kbas", "D_BOTH_MAKER_DIR", 2.95),
    ]

    rows = []
    for market_id, scen, old_dollars in flips:
        meta = meta_by_id[market_id]
        k_mult = float(meta["kalshi"]["fee_multiplier"])
        k_maker_frac = float(meta["kalshi"]["maker_fraction"])
        pm_rate = float(meta["polymarket"]["resolved_rate"])
        pm_rebate = float(meta["polymarket"].get("api_rebate_rate") or 0.22)
        k_yes, p_yes, p_no = load_books(snapshot_dir, market_id)
        direction = classify_direction(k_yes, p_yes)
        if direction is None:
            print(f"{market_id} [{scen}]: book not crossed; skipping")
            continue
        edge, breakdown = per_contract_edge(
            direction,
            k_multiplier=k_mult, k_maker_fraction=k_maker_frac,
            pm_rate=pm_rate, pm_rebate_fraction=pm_rebate,
            scenario=scen, use_rebate=True,
        )
        verdict, why = verdict_for(edge, breakdown)
        rows.append({
            "market_id": market_id, "scenario": scen,
            "old_dollars": old_dollars,
            "direction": direction, "edge": edge,
            "breakdown": breakdown, "verdict": verdict, "why": why,
            "meta": meta,
        })
        print(f"{market_id} [{scen}]: edge={edge*100:+.3f}c/ct  verdict={verdict}")

    write_md(rows, snapshot_dir)
    n_takeable = sum(1 for r in rows if r["verdict"] == "TAKEABLE")
    n_provideable = sum(1 for r in rows if r["verdict"].startswith("provideable"))
    n_zero = sum(1 for r in rows if r["verdict"].startswith("$0"))
    print(f"\n=== Survivor count ===")
    print(f"TAKEABLE: {n_takeable}")
    print(f"provideable (fill-unconfirmed): {n_provideable}")
    print(f"$0 (fees-bind): {n_zero}")
    return 0


def write_md(rows: list[dict], snapshot_dir: Path) -> None:
    n = len(rows)
    n_take = sum(1 for r in rows if r["verdict"] == "TAKEABLE")
    n_prov = sum(1 for r in rows if r["verdict"].startswith("provideable"))
    n_zero = sum(1 for r in rows if r["verdict"].startswith("$0"))

    md: list[str] = []
    md.append("# EXP-3a Direction Correction (Scenarios C & D)")
    md.append("")
    md.append(f"**Snapshot:** `{snapshot_dir.name}`  ")
    md.append("**Scope:** the 7 D-flips and 1 C-flip from "
              "`data/processed/exp3a_fee_correction.md` (8 (market, scenario) pairs).")
    md.append("")
    md.append("## The bug being fixed")
    md.append("")
    md.append(
        "The original Scenarios C (mixed) and D (both-maker) applied the "
        "`execution_mode='maker'` fee on a venue regardless of which side "
        "of the cross the trade had to hit. That's incoherent: on a "
        "crossed book, the take-take execution lifts BOTH inside quotes "
        "— both legs are *taker*. Maker pricing is only available on the "
        "side where the strategy ADDS liquidity (posts a passive order, "
        "waits for incoming flow). The original walker also reported a "
        "dollar figure tied to the resting depth on the venue's book — "
        "but as a maker you can't fill against resting depth at maker "
        "rates; you only fill when incoming flow crosses your post."
    )
    md.append("")
    md.append("## Direction-enforced verdict tiers")
    md.append("")
    md.append(
        "* **TAKEABLE** — per-contract edge > 0 AND both legs cross-side "
        "(taker on both venues). Instant lock-in; dollar figure is "
        "(per-contract edge) × min(top-of-book size on each leg).")
    md.append(
        "* **provideable, fill-unconfirmed** — per-contract edge > 0 BUT "
        "at least one leg is add-side (maker). Edge is real *if filled*; "
        "size depends on incoming taker flow lifting the posted order, "
        "not on the resting depth on the opposite side.")
    md.append(
        "* **$0 (fees-bind)** — per-contract edge ≤ 0 even with the "
        "scenario's most favorable fee assumption.")
    md.append("")
    md.append("## Per-market diff")
    md.append("")
    md.append(
        "| market | scen | direction | leg roles (buy / sell) | old $ "
        "(dir-blind) | new edge/ct (dir-enforced) | new verdict | why |"
    )
    md.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        bd = r["breakdown"]
        roles = (f"{bd['buy_leg']['venue']}@{bd['buy_leg']['price']:.4f} "
                 f"({bd['buy_leg']['role']}) / "
                 f"{bd['sell_leg']['venue']}@{bd['sell_leg']['price']:.4f} "
                 f"({bd['sell_leg']['role']})")
        edge_c = r["edge"] * 100
        md.append(
            f"| `{r['market_id']}` | {r['scenario']} | "
            f"{r['direction'].desc()} | {roles} | "
            f"${r['old_dollars']:.2f} | "
            f"{edge_c:+.3f}c | "
            f"{r['verdict']} | {r['why']} |"
        )
    md.append("")
    md.append("## Summary")
    md.append("")
    md.append(f"Of {n} flipped (market, scenario) pairs from the original C/D analysis:")
    md.append("")
    md.append(f"* **TAKEABLE under direction-enforced model: {n_take}.**")
    md.append(f"* Provideable, fill-unconfirmed: {n_prov}.")
    md.append(f"* $0 under fees: {n_zero}.")
    md.append("")
    if n_take == 0:
        md.append(
            "**None of the 8 original flips survive as genuinely takeable.** "
            "Every C/D scenario that produced a positive headline number "
            "required the strategy to be add-side (maker) on at least one "
            "venue. That doesn't make the per-contract edges fake — the "
            "fee improvement from maker mode is real (PM 4% → 0%; Kalshi "
            "1c parabolic → 0c for quadratic markets / 25% × 1c for "
            "quadratic_with_maker_fees) — but extracting it requires "
            "POSTING passive and getting filled by incoming flow, not "
            "lifting resting depth. The honest count of true cross-venue "
            "arbitrage opportunities on the D.2 snapshot remains "
            "**0 of 15** (matches Scenario B, corrected taker)."
        )
    else:
        md.append(f"{n_take} flip(s) remain genuinely takeable; see table above.")
    md.append("")
    md.append("## Why the per-contract edges still matter")
    md.append("")
    md.append(
        "The provideable-class markets quantify what an LP strategy could "
        "earn IF they could attract incoming flow to lift their post. For "
        "example: a strategy that posts a passive ASK on Polymarket at "
        "ARod's inside quote (0.051) and dynamically hedges by lifting "
        "Kalshi's YES ask (0.04) on fill, earns ~0.1c/contract gross before "
        "considering rebate. That's the *liquidity-provision* edge the "
        "project has been gesturing at — small per-contract, accessible "
        "only at the maker margin, and conditional on the strategy being "
        "able to source incoming flow on its posted side. The headline "
        "dollar figures from the direction-blind D scenario "
        "($30.23 Colombia AESP, $50.59 Peru RPAL, etc.) over-stated this "
        "by pretending the LP could ALSO sweep the contra-venue's resting "
        "depth as a maker — that's a category error, not a realistic "
        "execution path."
    )
    md.append("")
    md.append("## Notes on Peru specifically")
    md.append("")
    md.append(
        "The $50.59 Peru figure had two compounding errors:"
    )
    md.append(
        "1. The depth (3225 contracts at PM YES ASK 0.271) was real and "
        "persistent within the snapshot's regime "
        "(`data/processed/exp3a_peru_depth_check.md`, 100% large-level "
        "presence in early window). The 14:00Z price regime shift "
        "subsequently dissolved that level."
    )
    md.append(
        "2. Even with the depth real, Scenario D modeled buying that PM "
        "ask as a maker fill (0% fee). Buying PM means *lifting* the ask "
        "— that's TAKER (4%), not maker. The maker-eligible alternative "
        "is *posting* a bid on PM at 0.27+, waiting for sell flow. With "
        "the regime shift, that posted bid would now be above the new "
        "consensus (0.22) and immediately be lifted by sellers at a loss."
    )
    md.append("")
    md.append("Both corrections kill the $50.59 number independently.")
    md.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md))
    print(f"\nWrote {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
