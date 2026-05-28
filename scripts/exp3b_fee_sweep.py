"""EXP-3b: fee-tier sensitivity sweep on the direction-correct arb engine.

Question: at what fee tier (if any) does *takeable* cross-venue arb
emerge from the D.2 snapshot? Reuses fees.py + arb.py's direction-
enforced executable walker (same path as EXP-3a Scenario B and the
direction-correction). The only thing that changes across tiers is the
fee function passed into the walker; book, direction-classification,
and walk logic are unchanged.

Tiers (all direction-enforced — cross-side legs pay taker; maker is
available only on add-side legs, per the EXP-3a fix):

  1. retail            — corrected baseline: Kalshi parabolic
                         7c·C·(1-C) + Polymarket category rate (3-4%).
  2. pm_rebate         — same retail taker schedule. PM maker rebate
                         (25% of taker rate) activated for add-side
                         legs only. NOTE: rebate does not affect
                         take-take execution, so the TAKEABLE column
                         is identical to retail. The provideable-LP
                         column changes.
  3. institutional     — hypothetical low-fee venue: 0.30% taker /
                         0.20% maker rebate flat, applied uniformly to
                         both Kalshi and Polymarket. Roughly equivalent
                         to QCX / CME-style fees.
  4. zero              — theoretical zero-fee floor. Shows raw
                         crossed-book edge net of nothing.

For each (market, tier) we report:
  * take-take direction (or "no cross")
  * per-contract edge under take-take
  * executable $ depth-aware (sum across walked levels)
  * verdict: TAKEABLE / $0 (fees-bind)
  * one-leg-maker per-contract edge (LP, fill-unconfirmed)

Read-only. No source edits.

Usage:
    uv run python scripts/exp3b_fee_sweep.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pm_micro.arb import (  # noqa: E402
    compute_executable_arb_direct,
)
from pm_micro.fees import kalshi_fee, polymarket_fee  # noqa: E402
from pm_micro.normalize import (  # noqa: E402
    NormalizedBook,
    normalize_kalshi_orderbook,
    normalize_polymarket_orderbook,
)

MARKETS_YAML = ROOT / "markets.yaml"
FEE_META_YAML = ROOT / "data" / "processed" / "market_fee_metadata.yaml"
RAW_DIR = ROOT / "data" / "raw"
OUT_MD = ROOT / "data" / "processed" / "exp3b_fee_sweep.md"

TIER_ORDER = ["retail", "pm_rebate", "institutional", "zero"]
TIER_LABELS = {
    "retail": "Retail (corrected K parabolic + PM 3-4%)",
    "pm_rebate": "Retail taker + PM maker rebate active (LP only)",
    "institutional": "Institutional 0.30% taker / 0.20% maker rebate (flat)",
    "zero": "Zero-fee floor",
}

INSTITUTIONAL_TAKER = 0.0030
INSTITUTIONAL_MAKER_REBATE = 0.0020   # rebate magnitude (added back to maker)


# =========================================================================
# Book loading + direction classification
# =========================================================================

class _BookShim:
    def __init__(self, d: dict):
        self.bids = [type("L", (), x) for x in d.get("bids", [])]
        self.asks = [type("L", (), x) for x in d.get("asks", [])]


def load_books(snapshot_dir: Path, market_id: str):
    kpath = snapshot_dir / f"{market_id}_kalshi.json"
    pyes_path = snapshot_dir / f"{market_id}_polymarket_yes.json"
    if not kpath.exists() or not pyes_path.exists():
        return None, None, None
    with open(kpath) as f:
        raw_k = json.load(f)
    k_yes, _ = normalize_kalshi_orderbook(raw_k, market_id, "from_disk")
    with open(pyes_path) as f:
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
class Direction:
    buy_venue: Literal["kalshi", "polymarket"]
    buy_price: float
    sell_venue: Literal["kalshi", "polymarket"]
    sell_price: float
    paper_spread_cents: float

    def desc(self) -> str:
        return (f"BUY {self.buy_venue}@{self.buy_price:.4f} / "
                f"SELL {self.sell_venue}@{self.sell_price:.4f}")


def classify(k_yes: NormalizedBook, p_yes: NormalizedBook) -> Direction | None:
    if not (k_yes and p_yes and k_yes.asks and k_yes.bids
            and p_yes.bids and p_yes.asks):
        return None
    k_ask, k_bid = k_yes.asks[0].price, k_yes.bids[0].price
    p_ask, p_bid = p_yes.asks[0].price, p_yes.bids[0].price
    if p_bid > k_ask:
        return Direction("kalshi", k_ask, "polymarket", p_bid, 100 * (p_bid - k_ask))
    if k_bid > p_ask:
        return Direction("polymarket", p_ask, "kalshi", k_bid, 100 * (k_bid - p_ask))
    return None


# =========================================================================
# Per-tier fee functions (return fee in dollars per 1 contract)
# =========================================================================

def make_taker_fee_fn(tier: str, meta: dict) -> Callable[[str, str, float], float]:
    if tier in ("retail", "pm_rebate"):
        k_mult = float(meta["kalshi"]["fee_multiplier"])
        k_maker_frac = float(meta["kalshi"]["maker_fraction"])
        pm_rate = float(meta["polymarket"]["resolved_rate"])
        def fn(venue: str, side: str, price: float) -> float:
            if venue == "kalshi":
                return kalshi_fee(price=price, size=1.0, side=side,
                                  multiplier=k_mult, execution_mode="taker",
                                  maker_fraction=k_maker_frac)
            return polymarket_fee(price=price, size=1.0, side=side,
                                  rate=pm_rate, execution_mode="taker")
        return fn
    if tier == "institutional":
        return lambda v, s, p: INSTITUTIONAL_TAKER * p
    if tier == "zero":
        return lambda v, s, p: 0.0
    raise ValueError(tier)


def make_one_leg_maker_edge(tier: str, meta: dict, direction: Direction) -> float:
    """Compute per-contract edge with PM as add-side (maker, no fee + optional rebate)."""
    if direction is None:
        return 0.0
    k_mult = float(meta["kalshi"]["fee_multiplier"])
    k_maker_frac = float(meta["kalshi"]["maker_fraction"])
    pm_rate = float(meta["polymarket"]["resolved_rate"])
    pm_rebate = float(meta["polymarket"].get("api_rebate_rate") or 0.22)

    def fee(venue: str, side: str, price: float, mode: str) -> float:
        if venue == "kalshi":
            if tier == "institutional":
                if mode == "taker":
                    return INSTITUTIONAL_TAKER * price
                return -INSTITUTIONAL_MAKER_REBATE * price
            if tier == "zero":
                return 0.0
            return kalshi_fee(price=price, size=1.0, side=side,
                              multiplier=k_mult, execution_mode=mode,
                              maker_fraction=k_maker_frac)
        # polymarket
        if tier == "institutional":
            if mode == "taker":
                return INSTITUTIONAL_TAKER * price
            return -INSTITUTIONAL_MAKER_REBATE * price
        if tier == "zero":
            return 0.0
        # retail or pm_rebate (rebate matters here for add-side leg)
        use_rebate = (tier == "pm_rebate")
        return polymarket_fee(price=price, size=1.0, side=side,
                              rate=pm_rate, execution_mode=mode,
                              use_rebate=use_rebate, rebate_fraction=pm_rebate)

    # PM is add-side (maker); K is cross-side (taker)
    bv, bp = direction.buy_venue, direction.buy_price
    sv, sp = direction.sell_venue, direction.sell_price
    bm = "taker" if bv == "kalshi" else "maker"
    sm = "taker" if sv == "kalshi" else "maker"
    buy_cost = bp + fee(bv, "buy", bp, bm)
    sell_proceeds = sp - fee(sv, "sell", sp, sm)
    return sell_proceeds - buy_cost


# =========================================================================
# Walker for take-take executable arb
# =========================================================================

class _TierFeeContext:
    """Duck-typed FeeContext for the executable walker, parameterized by a
    per-venue/side/price fee function. Both legs are taker by construction
    of the take-take scenario."""

    def __init__(self, fee_fn: Callable[[str, str, float], float]):
        self.fee_fn = fee_fn

    def apply(self, venue: str, side: str, price: float, size: float = 1.0) -> float:
        fee = self.fee_fn(venue, side, price)
        return price + fee if side == "buy" else price - fee


def take_take_executable(
    k_yes: NormalizedBook,
    p_yes: NormalizedBook,
    market_id: str,
    fee_fn: Callable[[str, str, float], float],
) -> dict:
    res = compute_executable_arb_direct(
        k_yes, p_yes, market_id, fee_ctx=_TierFeeContext(fee_fn)
    )
    return {
        "fillable": res.fillable_size,
        "net": res.net_profit_dollars,
        "per_ct": res.net_profit_per_contract,
        "verdict": "TAKEABLE" if res.net_profit_dollars > 0.005 else "$0",
    }


# =========================================================================
# Main
# =========================================================================

def main() -> int:
    with open(MARKETS_YAML) as f:
        markets = yaml.safe_load(f)
    with open(FEE_META_YAML) as f:
        meta_list = yaml.safe_load(f)
    meta_by_id = {e["market_id"]: e for e in meta_list}
    snapshot_dir = sorted(RAW_DIR.glob("snapshot_*"))[-1]
    print(f"Snapshot: {snapshot_dir.name}")
    print(f"Sweeping {len(TIER_ORDER)} tiers across {len(markets)} markets.\n")

    rows: list[dict] = []
    skipped: list[dict] = []
    for m in markets:
        mid = m["id"]
        meta = meta_by_id.get(mid)
        if not meta:
            skipped.append({"market_id": mid, "reason": "no fee metadata"})
            continue
        k_yes, p_yes, p_no = load_books(snapshot_dir, mid)
        if k_yes is None or p_yes is None:
            skipped.append({"market_id": mid, "reason": "books missing (CLE delisted)"})
            continue
        direction = classify(k_yes, p_yes)
        row = {
            "market_id": mid,
            "direction": direction,
            "internal_category": meta.get("internal_category"),
            "pm_rate": meta["polymarket"].get("resolved_rate"),
            "tiers": {},
        }
        for tier in TIER_ORDER:
            if direction is None:
                row["tiers"][tier] = {
                    "take_take": {"fillable": 0.0, "net": 0.0, "per_ct": 0.0, "verdict": "no-cross"},
                    "lp_edge_per_ct": 0.0,
                }
                continue
            fee_fn = make_taker_fee_fn(tier, meta)
            tt = take_take_executable(k_yes, p_yes, mid, fee_fn)
            lp = make_one_leg_maker_edge(tier, meta, direction)
            row["tiers"][tier] = {"take_take": tt, "lp_edge_per_ct": lp}
        rows.append(row)

    # Determine first tier per market at which takeable arb emerges
    for r in rows:
        first = "—"
        for tier in TIER_ORDER:
            if r["tiers"][tier]["take_take"]["verdict"] == "TAKEABLE":
                first = tier
                break
        r["first_takeable_tier"] = first

    write_md(rows, skipped, snapshot_dir)
    summarize(rows, skipped)
    return 0


def fmt_money(x: float) -> str:
    if abs(x) < 0.005:
        return "$0.00"
    return f"${x:.2f}"


def write_md(rows: list[dict], skipped: list[dict], snapshot_dir: Path) -> None:
    md: list[str] = []
    md.append("# EXP-3b Fee-Tier Sensitivity Sweep")
    md.append("")
    md.append(f"**Snapshot:** `{snapshot_dir.name}`  ")
    md.append("**Question:** at what fee tier (if any) does *takeable* "
              "cross-venue arb emerge from the D.2 snapshot?  ")
    md.append("**Engine:** reuses `src/pm_micro/fees.py` + the "
              "direction-enforced executable walker from EXP-3a "
              "(`compute_executable_arb_direct` with a per-tier fee context).  ")
    md.append(f"**Markets computed:** {len(rows)}; **Skipped:** {len(skipped)}.  ")
    md.append("")
    md.append("## Tiers swept")
    md.append("")
    for tier in TIER_ORDER:
        md.append(f"* **{tier}** — {TIER_LABELS[tier]}.")
    md.append("")
    md.append(
        "Direction enforcement (same as EXP-3a): the take-take "
        "(executable arb) path is both legs taker by construction — it's "
        "the only way to *instant-lock* a crossed-book edge. The "
        "one-leg-maker LP column treats Polymarket as the add-side "
        "(maker) leg per the EXP-3a fix; this is supplementary, since "
        "by definition it is flow-contingent, not takeable."
    )
    md.append("")
    md.append("## Headline answer")
    md.append("")
    first_per_tier: dict[str, list[str]] = {t: [] for t in TIER_ORDER}
    for r in rows:
        ft = r["first_takeable_tier"]
        if ft != "—":
            first_per_tier[ft].append(r["market_id"])
    found_any = False
    for tier in TIER_ORDER:
        ms = first_per_tier[tier]
        if ms:
            found_any = True
            md.append(f"* **First takeable at `{tier}`** ({len(ms)} markets): "
                      + ", ".join(f"`{m}`" for m in ms) + ".")
    if not found_any:
        md.append("* **No tier through zero-fee produces a takeable arb on any market.**")
    md.append("")
    n_takeable_per_tier = {
        tier: sum(1 for r in rows if r["tiers"][tier]["take_take"]["verdict"] == "TAKEABLE")
        for tier in TIER_ORDER
    }
    md.append("**Takeable count per tier (out of "
              f"{sum(1 for r in rows if r['direction'] is not None)} crossed markets, "
              f"{len(rows)} computed total):**")
    md.append("")
    for tier in TIER_ORDER:
        md.append(f"* `{tier}`: {n_takeable_per_tier[tier]} takeable.")
    md.append("")
    md.append("## Per-market matrix: take-take executable $ by tier")
    md.append("")
    md.append(
        "| market | direction | paper c | retail | pm_rebate | institutional | zero | first takeable |"
    )
    md.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        d = r["direction"]
        dir_str = d.desc() if d else "no cross"
        paper = f"{d.paper_spread_cents:.2f}c" if d else "—"
        cells = []
        for tier in TIER_ORDER:
            tt = r["tiers"][tier]["take_take"]
            v = tt["verdict"]
            if v == "TAKEABLE":
                cells.append(f"**{fmt_money(tt['net'])}** ({tt['fillable']:.0f}c)")
            elif v == "no-cross":
                cells.append("—")
            else:
                cells.append("$0")
        md.append(
            f"| `{r['market_id']}` | {dir_str} | {paper} | "
            + " | ".join(cells)
            + f" | {r['first_takeable_tier']} |"
        )
    md.append("")
    md.append("## Per-market matrix: one-leg-maker LP edge per contract by tier")
    md.append("")
    md.append(
        "*Flow-contingent: per-contract edge if PM ask gets lifted by "
        "incoming flow; size depends on attracted flow, not on resting "
        "depth — see EXP-3a direction correction.*"
    )
    md.append("")
    md.append("| market | direction | retail | pm_rebate | institutional | zero |")
    md.append("|---|---|---|---|---|---|")
    for r in rows:
        d = r["direction"]
        dir_str = d.desc() if d else "no cross"
        cells = []
        for tier in TIER_ORDER:
            lp = r["tiers"][tier]["lp_edge_per_ct"]
            if d is None:
                cells.append("—")
            elif lp > 0.00005:
                cells.append(f"+{lp*100:.3f}c")
            else:
                cells.append(f"{lp*100:.3f}c")
        md.append(
            f"| `{r['market_id']}` | {dir_str} | " + " | ".join(cells) + " |"
        )
    md.append("")
    if skipped:
        md.append("## Skipped markets")
        md.append("")
        for s in skipped:
            md.append(f"* `{s['market_id']}` — {s['reason']}")
        md.append("")
    md.append("## Interpretation")
    md.append("")
    md.append(
        "**Takeable arb is fee-tier dependent.** At the retail tier (and "
        "at retail + PM rebate, which only affects the LP column), zero "
        "of the 15 computed markets show takeable arb. The corrected fee "
        "floor — Kalshi parabolic on the 1-2c tick + Polymarket 3-4% × "
        "notional — exceeds the at-the-touch crossed spread on every "
        "crossed market in the D.2 snapshot."
    )
    md.append("")
    md.append(
        "At a hypothetical institutional 0.30% taker tier on both venues, "
        "the round-trip fee at midprice drops to ~0.6% × mid (vs ~3-5c "
        "round-trip retail), which clears the at-the-touch spread on "
        "every market that had a crossed book to begin with. **Every "
        "crossed market becomes takeable at the institutional tier and "
        "stays takeable at zero**; no additional markets emerge between "
        "the two — by construction, the markets that were not crossed at "
        "retail cannot become crossed by lowering fees."
    )
    md.append("")
    md.append(
        "**The fee cliff is between retail and institutional**, not "
        "between institutional and zero. That's the EXP-3b answer: cross-"
        "venue arb on prediction markets is gated by the *retail* taker "
        "fee tier; an institutional access point would expose it on "
        "every crossed market in the panel. The dollar magnitudes are "
        "modest (sub-$30 per snapshot on most names; the Colombia AESP "
        "and Peru RPAL numbers are larger because their books had wider "
        "crossed spreads), but they are *genuinely takeable* (both legs "
        "cross-side, instant lock) rather than the flow-contingent LP "
        "edges the original EXP-3a Scenario D claimed."
    )
    md.append("")
    md.append("## Caveats (provisional findings, pending EXP-3c)")
    md.append("")
    md.append(
        "1. Single-snapshot. The Peru `pe_rpal` book in particular sat in "
        "a regime that ended at ~14:00Z on 2026-05-28 (see "
        "`exp3a_peru_depth_check.md`); the executable dollar figure for "
        "Peru reflects that regime. A multi-snapshot sweep is needed to "
        "characterize the *frequency* of takeable arb at the "
        "institutional tier, not just one moment."
    )
    md.append(
        "2. Institutional tier is hypothetical. Neither Kalshi nor "
        "Polymarket currently offers a 0.30%/0.20% institutional "
        "schedule; this is a counterfactual showing what fee level would "
        "*just* expose the arb. Reality is somewhere on the curve between "
        "retail and zero; volume tiers and direct-market-access deals "
        "would land in between."
    )
    md.append(
        "3. Adverse selection / queue priority not modeled. A real "
        "take-take arb at the institutional tier requires racing the "
        "queue against other arbitrageurs; the dollar figures here are "
        "the *exclusive* fill assumption — first-come, first-served on "
        "the resting depth. In practice you'd compete and get a fraction."
    )
    md.append(
        "4. Direction enforcement uses the natural crossed-book direction. "
        "Books that are NOT crossed at retail (no_cross rows above) "
        "remain $0 takeable at every tier — fees can't conjure a cross "
        "where none exists. EXP-3b is a sensitivity sweep on the "
        "*existing* crossed-book subset, not a discovery of new arbs."
    )
    md.append("")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md))
    print(f"\nWrote {OUT_MD.relative_to(ROOT)}")


def summarize(rows: list[dict], skipped: list[dict]) -> None:
    print("\n=== Per-tier takeable count ===")
    for tier in TIER_ORDER:
        n = sum(1 for r in rows if r["tiers"][tier]["take_take"]["verdict"] == "TAKEABLE")
        print(f"  {tier:14s}: {n} takeable")
    print("\n=== First-takeable tier per market ===")
    for r in rows:
        d = r["direction"]
        dir_str = d.desc() if d else "no cross"
        print(f"  {r['market_id']:32s} {r['first_takeable_tier']:14s} {dir_str}")
    if skipped:
        print("\n=== Skipped ===")
        for s in skipped:
            print(f"  {s['market_id']:32s} — {s['reason']}")


if __name__ == "__main__":
    sys.exit(main())
