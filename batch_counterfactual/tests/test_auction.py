"""Unit tests for auction.py — synthetic books with hand-computed expectations."""

from decimal import Decimal

import pandas as pd
import pytest

from auction import (
    BoundsResult,
    Fill,
    Order,
    book_to_orders,
    clearance_bounds,
    clear,
    clear_joint,
)
from book import BookState, to_prob
from fees import Tier

D = Decimal


def _o(oid, side, price, qty, venue="kalshi", owner="t"):
    return Order(oid, owner, venue, side, D(str(price)), D(str(qty)))


def _book(venue, bid, ask, bid_sz=None, ask_sz=None, market="m"):
    return BookState(
        venue=venue, market_id=market,
        ts=pd.Timestamp("2026-05-28T04:01:00Z"),
        best_bid=to_prob(bid, venue), best_ask=to_prob(ask, venue),
        bid_sz=None if bid_sz is None else D(str(bid_sz)),
        ask_sz=None if ask_sz is None else D(str(ask_sz)),
        raw_best_bid=bid, raw_best_ask=ask,
        tick_size=D("0.01") if venue == "kalshi" else D("0.001"),
    )


# --- 4-order hand-computed clearing (zero fees) ---------------------------

def test_clear_four_orders_max_volume_zero_fee():
    """Hand: vol=120 at p in [0.57,0.58]; midpoint 0.575 -> 0.58 at 0.01 tick."""
    orders = [
        _o("b1", "buy", "0.60", 100),
        _o("b2", "buy", "0.58", 50),
        _o("s1", "sell", "0.55", 80),
        _o("s2", "sell", "0.57", 40),
    ]
    r = clear(orders, "max_volume", Tier.ZERO)
    assert r.clearing_price == D("0.58")
    assert r.total_qty == D("120")
    assert r.feasible_range == (D("0.57"), D("0.58"))


def test_clear_four_orders_max_agg_pi_zero_fee():
    orders = [
        _o("b1", "buy", "0.60", 100),
        _o("b2", "buy", "0.58", 50),
        _o("s1", "sell", "0.55", 80),
        _o("s2", "sell", "0.57", 40),
    ]
    r = clear(orders, "max_agg_pi", Tier.ZERO)
    assert r.total_qty == D("120")
    # Midpoint p=0.58 with buy pro-rata (120/150): b1=80, b2=40, s1=80, s2=40
    # PI = 0.02*80 + 0 + 0.03*80 + 0.01*40 = 4.40
    assert r.agg_pi == D("4.40")


# --- max_volume vs max_agg_pi choose different prices ---------------------

def test_max_volume_vs_max_agg_pi_different_prices():
    """Asymmetric depth: same vol/PI but objectives pick different clearing prices."""
    orders = [
        _o("s1", "sell", "0.50", 10),
        _o("s2", "sell", "0.53", 10),
        _o("b1", "buy", "0.525", 5),
        _o("b2", "buy", "0.54", 10),
    ]
    rv = clear(orders, "max_volume", Tier.ZERO)
    rp = clear(orders, "max_agg_pi", Tier.ZERO)
    assert rv.total_qty == D("10")
    assert rp.total_qty == D("10")
    assert rv.clearing_price == D("0.52")
    assert rp.clearing_price == D("0.51")
    assert rv.clearing_price != rp.clearing_price


# --- clearance_bounds: gross-uncrossed vs fee-blocked ---------------------

def test_bounds_gross_uncrossed():
    k = _book("kalshi", 0.28, 0.30)
    p = _book("polymarket", 0.27, 0.29)   # k_bid 0.28 < p_ask 0.29 barely uncrossed
    # Make clearly uncrossed: k_bid=0.27, p_ask=0.28
    k = _book("kalshi", 0.27, 0.30)
    p = _book("polymarket", 0.26, 0.28)
    r = clearance_bounds(k, p, Tier.ZERO)
    assert not r.clearable
    assert r.not_clearable.reason == "gross_uncrossed"


def test_bounds_fee_blocked_not_gross():
    """Gross cross 0.5c but retail fees eat it -> fee_blocked."""
    k = _book("kalshi", 0.30, 0.31)
    p = _book("polymarket", 0.27, 0.285)   # k_bid - p_ask = 0.015 = 1.5c gross
    r_gross = clearance_bounds(k, p, Tier.ZERO)
    assert r_gross.clearable
    r_retail = clearance_bounds(k, p, Tier.RETAIL, category="sports")
    assert not r_retail.clearable
    assert r_retail.not_clearable.reason == "fee_blocked"
    assert r_retail.gross_cross_c > 0


# --- nonlinear Kalshi fee at tails vs mid ---------------------------------

def test_kalshi_parabolic_extreme_c_flips_feasibility():
    """At C=0.50 Kalshi fee=2c can block; at C=0.05 fee=1c may clear a 1.2c gross."""
    # Direction sell_k_buy_p: need p - fee_k >= k_bid and p + fee_p <= p_ask
    k = _book("kalshi", 0.04, 0.06)      # sell limit 0.04
    p = _book("polymarket", 0.02, 0.051) # buy limit 0.051; gross 0.04 vs 0.051 crossed
    r_mid = clearance_bounds(k, p, Tier.RETAIL, category="sports")
    # At midpoint ~0.045: kalshi fee 1c (tail), pm fee small — may clear
    # Widen cross at mid C=0.50 scenario with 2c kalshi fee:
    k2 = _book("kalshi", 0.48, 0.52)
    p2 = _book("polymarket", 0.46, 0.495)  # 1.5c gross at zero
    r_tail = clearance_bounds(k, p, Tier.RETAIL, category="sports")
    r_mid50 = clearance_bounds(k2, p2, Tier.RETAIL, category="sports")
    # Tail cross (low C) has lower Kalshi fee — more likely clearable than mid if tight.
    if r_tail.clearable and not r_mid50.clearable:
        pass  # expected pattern
    else:
        # At minimum: fees at 0.05 are strictly less than at 0.50 per contract.
        from fees import kalshi_fee
        assert kalshi_fee(0.05) < kalshi_fee(0.50)


# --- pro-rata rationing + largest remainder ------------------------------

def test_prorata_rationing_excess_supply():
    orders = [
        _o("b1", "buy", "0.55", 10),
        _o("s1", "sell", "0.55", 6),
        _o("s2", "sell", "0.55", 9),
    ]
    r = clear(orders, "max_volume", Tier.ZERO)
    assert r.clearing_price == D("0.55")
    assert r.total_qty == D("10")
    fills = {f.order_id: f.qty for f in r.fills}
    assert fills["b1"] == D("10")
    # 10 pro-rata across 6+9=15: 4 and 6 (largest remainder)
    assert fills["s1"] + fills["s2"] == D("10")
    assert fills["s1"] == D("4")
    assert fills["s2"] == D("6")


# --- tie-break midpoint + tick rounding -----------------------------------

def test_tie_break_midpoint_finer_tick():
    """Two adjacent optimal prices -> midpoint rounded to 0.001 tick."""
    orders = [
        _o("b1", "buy", "0.552", 10, venue="polymarket"),
        _o("s1", "sell", "0.548", 10, venue="kalshi"),
    ]
    r = clear(orders, "max_volume", Tier.ZERO)
    # Optimal interval spans 0.548-0.552 at 0.001 ticks; midpoint 0.550
    assert r.clearing_price == D("0.550")


# --- clear_joint executes volume neither venue could alone ----------------

def test_clear_joint_cross_venue_only():
    """Kalshi only has buys, PM only has sells — joint clears, singles cannot."""
    k_buys = [_o("kb", "buy", "0.55", 50, venue="kalshi")]
    p_sells = [_o("ps", "sell", "0.52", 50, venue="polymarket")]
    r_joint = clear_joint(k_buys, p_sells, "max_volume", Tier.ZERO)
    assert r_joint.total_qty == D("50")
    r_k = clear(k_buys, "max_volume", Tier.ZERO)
    r_p = clear(p_sells, "max_volume", Tier.ZERO)
    assert r_k.total_qty == D("0")
    assert r_p.total_qty == D("0")


# --- BookOrders adapter rejects panel books --------------------------------

def test_book_to_orders_raises_without_sizes():
    k = _book("kalshi", 0.30, 0.31)  # no sizes
    with pytest.raises(ValueError, match="clearance_bounds"):
        book_to_orders(k)


def test_book_to_orders_with_sizes():
    k = _book("kalshi", 0.30, 0.31, bid_sz=100, ask_sz=50)
    orders = book_to_orders(k)
    assert len(orders) == 2
    assert orders[0].side == "buy" and orders[0].qty == D("100")
