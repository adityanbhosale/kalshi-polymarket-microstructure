"""Uniform-price call auction engine for the batch-auction counterfactual (Phase 2).

Consumes `book.BookState` and `fees.leg_fee` — does not duplicate their logic.
Two clearance paths:

  (a-d) ``clear`` / ``clear_joint`` — full order-book auction on synthetic or
        extracted orders with real quantities. Requires ``Order.qty``; the
        ``BookOrders`` adapter raises if ``BookState.bid_sz``/``ask_sz`` are
        None (30s panel must never use this path).

  (e)   ``clearance_bounds`` — price-only first-clearance primitive for the
        30s panel (top-of-book prices, per-contract metrics only). This is the
        Arm-A / Arm-D entry point until per-episode gz ladder extraction lands.

ASSUMPTION-1 (tie-break): when a contiguous interval of clearing prices achieves
the same optimal objective, clear at the interval midpoint rounded to the finer
of the participating venues' ticks (Polymarket 0.001 when both venues present).

ASSUMPTION-2 (rationing): pro-rata by order qty at the margin; no time priority.
Rounding residue assigned by largest-remainder rule (deterministic, no RNG).

Settlement-rail impossibility (Kalshi USD vs PM USDC) is a writeup caveat, not
enforced in code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal

from book import BookState, HUNDRED, KALSHI_TICK, POLYMARKET_TICK, venue_tick
from fees import Tier, leg_fee

Side = Literal["buy", "sell"]
Objective = Literal["max_volume", "max_agg_pi"]
NotClearableReason = Literal["gross_uncrossed", "fee_blocked"]

ZERO = Decimal(0)
ONE = Decimal(1)
TWO = Decimal(2)


# =========================================================================
# Order model + BookOrders adapter (synthetic / extracted books only)
# =========================================================================

@dataclass(frozen=True)
class Order:
    order_id: str
    owner_id: str
    venue: str
    side: Side
    price: Decimal          # limit price, YES probability in [0, 1]
    qty: Decimal


def book_to_orders(book: BookState, *, owner_prefix: str = "resting") -> list[Order]:
    """Convert a two-sided ``BookState`` into resting limit orders.

    Raises if ``bid_sz`` or ``ask_sz`` is None — the 30s panel must use
    ``clearance_bounds``, never this adapter.
    """
    if book.bid_sz is None or book.ask_sz is None:
        raise ValueError(
            "BookState has no sizes; panel data must use clearance_bounds(), "
            "not book_to_orders()"
        )
    if book.best_bid is None or book.best_ask is None:
        raise ValueError("BookState is not two-sided")
    v = book.venue.lower()
    return [
        Order(f"{owner_prefix}-bid", owner_prefix, v, "buy", book.best_bid, book.bid_sz),
        Order(f"{owner_prefix}-ask", owner_prefix, v, "sell", book.best_ask, book.ask_sz),
    ]


# =========================================================================
# Fee helpers (Decimal wrappers around fees.leg_fee)
# =========================================================================

def _d_fee(
    venue: str,
    price: Decimal,
    tier: Tier,
    *,
    role: str = "taker",
    category: str | None = None,
    pm_rate: float | None = None,
) -> Decimal:
    return Decimal(str(leg_fee(
        venue, float(price), tier=tier, role=role,
        category=category, pm_rate=pm_rate,
    )))


def buy_cost(p: Decimal, venue: str, tier: Tier, **kw) -> Decimal:
    """Effective per-contract buy cost at clearing price ``p``."""
    return p + _d_fee(venue, p, tier, role="taker", **kw)


def sell_proceeds(p: Decimal, venue: str, tier: Tier, **kw) -> Decimal:
    """Effective per-contract sell proceeds at clearing price ``p``."""
    return p - _d_fee(venue, p, tier, role="taker", **kw)


def _finer_tick(venues: set[str]) -> Decimal:
    ticks = {venue_tick(v) for v in venues}
    return min(ticks) if ticks else POLYMARKET_TICK


def _quantize(p: Decimal, tick: Decimal) -> Decimal:
    return p.quantize(tick, rounding=ROUND_HALF_UP)


# =========================================================================
# Clearing result types
# =========================================================================

@dataclass(frozen=True)
class Fill:
    order_id: str
    qty: Decimal
    p_eff: Decimal          # effective price after leg fee


@dataclass(frozen=True)
class ClearingResult:
    clearing_price: Decimal | None
    fills: list[Fill]
    total_qty: Decimal
    agg_pi: Decimal
    objective_used: Objective
    feasible_range: tuple[Decimal, Decimal] | None
    unfilled: dict[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class NotClearable:
    reason: NotClearableReason


@dataclass(frozen=True)
class BoundsResult:
    """Price-only clearance outcome for two top-of-book ``BookState``s."""
    clearable: bool
    clearing_price: Decimal | None
    feasible_range: tuple[Decimal, Decimal] | None
    pi_kalshi_c: Decimal | None       # per-contract PI, cents, participating side
    pi_polymarket_c: Decimal | None
    gross_cross_c: Decimal | None
    direction: str | None             # "sell_k_buy_p" | "buy_k_sell_p"
    not_clearable: NotClearable | None = None


# =========================================================================
# Full auction: uniform-price call with fee-adjusted limits
# =========================================================================

def _order_participates(o: Order, p: Decimal, tier: Tier, **kw) -> bool:
    if o.side == "buy":
        return buy_cost(p, o.venue, tier, **kw) <= o.price
    return sell_proceeds(p, o.venue, tier, **kw) >= o.price


def _volume_at(orders: list[Order], p: Decimal, tier: Tier, **kw) -> Decimal:
    dem = sum((o.qty for o in orders if o.side == "buy" and _order_participates(o, p, tier, **kw)),
              ZERO)
    sup = sum((o.qty for o in orders if o.side == "sell" and _order_participates(o, p, tier, **kw)),
              ZERO)
    return min(dem, sup)


def _agg_pi_at(orders: list[Order], p: Decimal, tier: Tier, trade_qty: Decimal, **kw) -> Decimal:
    """Aggregate PI at price ``p`` for the traded ``trade_qty`` (pro-rata preview)."""
    if trade_qty <= ZERO:
        return ZERO
    buys = [o for o in orders if o.side == "buy" and _order_participates(o, p, tier, **kw)]
    sells = [o for o in orders if o.side == "sell" and _order_participates(o, p, tier, **kw)]
    dem = sum((o.qty for o in buys), ZERO)
    sup = sum((o.qty for o in sells), ZERO)
    if dem == ZERO or sup == ZERO:
        return ZERO
    # Pro-rata fill fractions for PI estimate at this price.
    buy_frac = trade_qty / dem if dem > sup else ONE
    sell_frac = trade_qty / sup if sup > dem else ONE
    pi = ZERO
    for o in buys:
        fill = o.qty * buy_frac
        pe = buy_cost(p, o.venue, tier, **kw)
        pi += (o.price - pe) * fill
    for o in sells:
        fill = o.qty * sell_frac
        pe = sell_proceeds(p, o.venue, tier, **kw)
        pi += (pe - o.price) * fill
    return pi


def _candidate_prices(orders: list[Order], tick: Decimal) -> list[Decimal]:
    if not orders:
        return []
    lo = _quantize(min(o.price for o in orders), tick)
    hi = _quantize(max(o.price for o in orders), tick)
    prices: list[Decimal] = []
    p = lo
    while p <= hi:
        prices.append(p)
        p += tick
    return prices


def _optimal_prices(
    orders: list[Order],
    objective: Objective,
    tier: Tier,
    tick: Decimal,
    **kw,
) -> tuple[Decimal, tuple[Decimal, Decimal] | None]:
    """Return (best_value, feasible_price_interval) for the objective."""
    cands = _candidate_prices(orders, tick)
    if not cands:
        return ZERO, None

    best_val = None
    best_prices: list[Decimal] = []

    for p in cands:
        vol = _volume_at(orders, p, tier, **kw)
        val = vol if objective == "max_volume" else _agg_pi_at(orders, p, tier, vol, **kw)
        if best_val is None or val > best_val:
            best_val = val
            best_prices = [p]
        elif val == best_val:
            best_prices.append(p)

    if best_val is None or best_val <= ZERO:
        return ZERO, None

    lo, hi = min(best_prices), max(best_prices)
    return best_val, (lo, hi)


def _midpoint_price(interval: tuple[Decimal, Decimal], tick: Decimal) -> Decimal:
    lo, hi = interval
    mid = (lo + hi) / TWO
    return _quantize(mid, tick)


def _largest_remainder(weights: list[Decimal], total: Decimal) -> list[Decimal]:
    """Deterministic pro-rata: assign ``total`` across ``weights`` (ASSUMPTION-2)."""
    if total <= ZERO or not weights:
        return [ZERO] * len(weights)
    wsum = sum(weights, ZERO)
    if wsum <= ZERO:
        return [ZERO] * len(weights)
    raw = [total * w / wsum for w in weights]
    floors = [r.to_integral_value(rounding=ROUND_FLOOR) for r in raw]
    assigned = sum(floors, ZERO)
    residue = int((total - assigned).to_integral_value(rounding=ROUND_HALF_UP))
    fracs = sorted(
        [(raw[i] - floors[i], i) for i in range(len(weights))],
        key=lambda x: (-x[0], x[1]),
    )
    out = list(floors)
    for k in range(residue):
        out[fracs[k][1]] += ONE
    return out


def _allocate(
    orders: list[Order],
    p: Decimal,
    tier: Tier,
    **kw,
) -> tuple[list[Fill], Decimal, Decimal, dict[str, Decimal]]:
    """Pro-rata allocation at clearing price ``p`` (ASSUMPTION-2)."""
    buys = [o for o in orders if o.side == "buy" and _order_participates(o, p, tier, **kw)]
    sells = [o for o in orders if o.side == "sell" and _order_participates(o, p, tier, **kw)]
    dem = sum((o.qty for o in buys), ZERO)
    sup = sum((o.qty for o in sells), ZERO)
    trade = min(dem, sup)
    fills: list[Fill] = []
    unfilled: dict[str, Decimal] = {}

    if trade <= ZERO:
        for o in orders:
            unfilled[o.order_id] = o.qty
        return fills, ZERO, ZERO, unfilled

    if dem <= sup:
        # All buys fill; ration sells.
        buy_allocs = [o.qty for o in buys]
        sell_allocs = _largest_remainder([o.qty for o in sells], trade)
        for o, q in zip(buys, buy_allocs):
            fills.append(Fill(o.order_id, q, buy_cost(p, o.venue, tier, **kw)))
        for o, q in zip(sells, sell_allocs):
            if q > ZERO:
                fills.append(Fill(o.order_id, q, sell_proceeds(p, o.venue, tier, **kw)))
            if q < o.qty:
                unfilled[o.order_id] = o.qty - q
    else:
        # All sells fill; ration buys.
        sell_allocs = [o.qty for o in sells]
        buy_allocs = _largest_remainder([o.qty for o in buys], trade)
        for o, q in zip(sells, sell_allocs):
            fills.append(Fill(o.order_id, q, sell_proceeds(p, o.venue, tier, **kw)))
        for o, q in zip(buys, buy_allocs):
            if q > ZERO:
                fills.append(Fill(o.order_id, q, buy_cost(p, o.venue, tier, **kw)))
            if q < o.qty:
                unfilled[o.order_id] = o.qty - q

    for o in orders:
        if o.order_id not in {f.order_id for f in fills} and o.order_id not in unfilled:
            unfilled[o.order_id] = o.qty

    agg_pi = ZERO
    for f in fills:
        o = next(x for x in orders if x.order_id == f.order_id)
        if o.side == "buy":
            agg_pi += (o.price - f.p_eff) * f.qty
        else:
            agg_pi += (f.p_eff - o.price) * f.qty

    return fills, trade, agg_pi, unfilled


def clear(
    orders: list[Order],
    objective: Objective,
    fee_tier: Tier,
    *,
    category: str | None = None,
    pm_rate: float | None = None,
) -> ClearingResult:
    """Uniform-price call auction for ONE market (single or joint order set)."""
    kw = dict(category=category, pm_rate=pm_rate)
    venues = {o.venue.lower() for o in orders}
    tick = _finer_tick(venues)

    best_val, interval = _optimal_prices(orders, objective, fee_tier, tick, **kw)
    if interval is None or best_val <= ZERO:
        return ClearingResult(None, [], ZERO, ZERO, objective, None, {})

    p_clear = _midpoint_price(interval, tick)
    fills, total, agg_pi, unfilled = _allocate(orders, p_clear, fee_tier, **kw)
    return ClearingResult(p_clear, fills, total, agg_pi, objective, interval, unfilled)


def clear_joint(
    orders_a: list[Order],
    orders_b: list[Order],
    objective: Objective,
    fee_tier: Tier,
    **kw,
) -> ClearingResult:
    """Joint cross-venue auction: both venues' orders in one clearing (Arm D core)."""
    return clear(orders_a + orders_b, objective, fee_tier, **kw)


# =========================================================================
# Price-only clearance_bounds (30s panel — per-contract metrics only)
# =========================================================================

def _scan_feasible(
    lo: Decimal,
    hi: Decimal,
    tick: Decimal,
    pred,
) -> list[Decimal]:
    """Return tick prices in [lo, hi] where ``pred(p)`` is True."""
    out: list[Decimal] = []
    p = _quantize(lo, tick)
    hi_q = _quantize(hi, tick)
    while p <= hi_q + tick / 1000:
        if pred(p):
            out.append(p)
        p += tick
    return out


def _bounds_direction(
    k: BookState,
    p: BookState,
    tier: Tier,
    direction: str,
    **kw,
) -> tuple[Decimal | None, tuple[Decimal, Decimal] | None, Decimal | None, Decimal | None]:
    """Return (gross_cross_c, feasible_range, pi_k_c, pi_p_c) for one direction.

    Uniform-price semantics (YES probability ``p`` on both venues):
      * ``sell_k_buy_p`` (crossA = k_bid - p_ask): PM **sells** (ask limit),
        Kalshi **buys** (bid limit). Feasible ``p_ask <= p <= k_bid``.
      * ``buy_k_sell_p`` (crossB = p_bid - k_ask): Kalshi **sells** (ask limit),
        PM **buys** (bid limit). Feasible ``k_ask <= p <= p_bid``.
    """
    tick = _finer_tick({k.venue, p.venue})

    if direction == "sell_k_buy_p":
        if k.best_bid is None or p.best_ask is None:
            return None, None, None, None
        gross = (k.best_bid - p.best_ask) * HUNDRED
        lo, hi = p.best_ask, k.best_bid
        if lo > hi:
            return gross, None, None, None

        def ok(price: Decimal) -> bool:
            return (sell_proceeds(price, "polymarket", tier, **kw) >= p.best_ask
                    and buy_cost(price, "kalshi", tier, **kw) <= k.best_bid)

        feas = _scan_feasible(lo, hi, tick, ok)
        if not feas:
            return gross, None, None, None
        fr = (feas[0], feas[-1])
        mid = _midpoint_price(fr, tick)
        pi_p = (sell_proceeds(mid, "polymarket", tier, **kw) - p.best_ask) * HUNDRED
        pi_k = (k.best_bid - buy_cost(mid, "kalshi", tier, **kw)) * HUNDRED
        return gross, fr, pi_k, pi_p

    # buy_k_sell_p
    if k.best_ask is None or p.best_bid is None:
        return None, None, None, None
    gross = (p.best_bid - k.best_ask) * HUNDRED
    lo, hi = k.best_ask, p.best_bid
    if lo > hi:
        return gross, None, None, None

    def ok(price: Decimal) -> bool:
        return (sell_proceeds(price, "kalshi", tier, **kw) >= k.best_ask
                and buy_cost(price, "polymarket", tier, **kw) <= p.best_bid)

    feas = _scan_feasible(lo, hi, tick, ok)
    if not feas:
        return gross, None, None, None
    fr = (feas[0], feas[-1])
    mid = _midpoint_price(fr, tick)
    pi_k = (sell_proceeds(mid, "kalshi", tier, **kw) - k.best_ask) * HUNDRED
    pi_p = (p.best_bid - buy_cost(mid, "polymarket", tier, **kw)) * HUNDRED
    return gross, fr, pi_k, pi_p


def clearance_bounds(
    book_a: BookState,
    book_b: BookState,
    fee_tier: Tier,
    *,
    category: str | None = None,
    pm_rate: float | None = None,
) -> BoundsResult:
    """Price-only first-clearance primitive for top-of-book panel data.

    ``book_a`` = Kalshi, ``book_b`` = Polymarket. Returns per-contract PI in
    cents for each participating side at the midpoint clearing price.
    """
    kw = dict(category=category, pm_rate=pm_rate)
    k, p = book_a, book_b

    dirs: list[tuple[str, Decimal | None, tuple | None, Decimal | None, Decimal | None]] = []
    for d in ("sell_k_buy_p", "buy_k_sell_p"):
        g, fr, pi_k, pi_p = _bounds_direction(k, p, fee_tier, d, **kw)
        if g is not None:
            dirs.append((d, g, fr, pi_k, pi_p))

    if not dirs:
        return BoundsResult(False, None, None, None, None, None, None,
                            NotClearable("gross_uncrossed"))

    # Pick direction with largest gross cross (pre-fee).
    best = max(dirs, key=lambda x: x[1] if x[1] is not None else Decimal("-999"))
    direction, gross, fr, pi_k, pi_p = best

    if gross is None or gross <= ZERO:
        return BoundsResult(False, None, None, None, None, gross, direction,
                            NotClearable("gross_uncrossed"))

    if fr is None:
        return BoundsResult(False, None, None, None, None, gross, direction,
                            NotClearable("fee_blocked"))

    mid = _midpoint_price(fr, _finer_tick({k.venue, p.venue}))
    return BoundsResult(True, mid, fr, pi_k, pi_p, gross, direction, None)
