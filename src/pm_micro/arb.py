"""Cross-venue discrepancy and executable arbitrage computation.

Fee assumptions live in `pm_micro.fees` after the EXP-3a correction
(2026-05-28). This module's `apply_fee` is now a thin wrapper that
delegates per-venue and per-execution-mode pricing to the parabolic
Kalshi / category-dependent Polymarket models in `fees.py`. Callers
that don't pass `pm_category` / `kalshi_multiplier` / `execution_mode`
fall back to the pre-EXP-3a constants (Kalshi $0.02 flat at midprice,
Polymarket 2% flat), preserving backward compatibility with the
existing test suite and `scripts/compute_arb.py`.
"""

from dataclasses import dataclass

from .fees import kalshi_fee, polymarket_fee
from .normalize import NormalizedBook, PriceLevel

# Pre-EXP-3a constants. Retained for tests/baselines that explicitly
# need the stale values (see scripts/exp3a_fee_correction.py scenario A).
# DO NOT USE in new code — pass category/multiplier through `apply_fee`
# instead.
POLYMARKET_TAKER_FEE_RATE = 0.02    # legacy 2% flat — superseded by fees.py
POLYMARKET_MAKER_FEE_RATE = 0.0
KALSHI_PER_CONTRACT_FEE = 0.02      # legacy $0.02 flat — superseded by fees.py


def apply_fee(
    venue: str,
    side: str,
    price: float,
    size: float = 1.0,
    *,
    pm_category: str | None = None,
    pm_rate: float | None = None,
    kalshi_multiplier: float = 1.0,
    kalshi_maker_fraction: float = 0.25,
    execution_mode: str = "taker",
    use_rebate: bool = False,
    rebate_fraction: float | None = None,
) -> float:
    """Return effective per-contract price after fees.

    Sign convention preserved from pre-EXP-3a: buys receive an upward
    fee adjustment (cost > nominal), sells receive a downward adjustment
    (proceeds < nominal). Magnitude now flows through `pm_micro.fees`:

      * Kalshi: parabolic ``ceil(7 * kalshi_multiplier * C * (1-C))``
        in cents, with maker mode at ``kalshi_maker_fraction`` of the
        raw (pass 0 for ``fee_type='quadratic'`` markets).
      * Polymarket: category-dependent ``rate * price`` notional;
        maker mode is zero unless ``use_rebate=True``.

    Defaults (all keyword args omitted) reproduce the historical
    behavior at the midprice: Kalshi 2¢/contract at C=0.5,
    Polymarket 2% of notional (because `pm_category=None` resolves to
    the legacy 2% default — see `polymarket_rate_for_category`).
    """
    if venue == "polymarket":
        rebate_kwargs = {}
        if rebate_fraction is not None:
            rebate_kwargs["rebate_fraction"] = rebate_fraction
        fee_dollars = polymarket_fee(
            price=price, size=1.0, side=side, category=pm_category,
            rate=pm_rate, execution_mode=execution_mode,
            use_rebate=use_rebate, **rebate_kwargs,
        )
        return price + fee_dollars if side == "buy" else price - fee_dollars
    if venue == "kalshi":
        fee_dollars = kalshi_fee(
            price=price, size=1.0, side=side, multiplier=kalshi_multiplier,
            execution_mode=execution_mode, maker_fraction=kalshi_maker_fraction,
        )
        return price + fee_dollars if side == "buy" else price - fee_dollars
    raise ValueError(f"Unknown venue: {venue}")


@dataclass(frozen=True)
class FeeContext:
    """Per-market fee parameters threaded into the executable arb walkers.

    Defaults reproduce the pre-EXP-3a behavior at midprice (Kalshi $0.02
    at C=0.5 via the parabolic, Polymarket 2% via the legacy fallback in
    `polymarket_rate_for_category(None)`). Pass explicit category /
    multiplier / execution_mode to engage the corrected EXP-3a model.

    For the "mixed" scenario (Kalshi taker / PM maker), set
    `kalshi_execution_mode='taker'` and `pm_execution_mode='maker'`
    independently. `pm_use_rebate=True` makes maker mode produce a
    negative fee (rebate).
    """
    kalshi_multiplier: float = 1.0
    kalshi_maker_fraction: float = 0.25
    kalshi_execution_mode: str = "taker"
    pm_category: str | None = None
    pm_rate: float | None = None
    pm_execution_mode: str = "taker"
    pm_use_rebate: bool = False
    pm_rebate_fraction: float | None = None

    def apply(self, venue: str, side: str, price: float, size: float = 1.0) -> float:
        """Call apply_fee with venue-appropriate kwargs."""
        if venue == "kalshi":
            return apply_fee(
                venue, side, price, size,
                kalshi_multiplier=self.kalshi_multiplier,
                kalshi_maker_fraction=self.kalshi_maker_fraction,
                execution_mode=self.kalshi_execution_mode,
            )
        if venue == "polymarket":
            kw = dict(
                pm_category=self.pm_category, pm_rate=self.pm_rate,
                execution_mode=self.pm_execution_mode,
                use_rebate=self.pm_use_rebate,
            )
            if self.pm_rebate_fraction is not None:
                kw["rebate_fraction"] = self.pm_rebate_fraction
            return apply_fee(venue, side, price, size, **kw)
        raise ValueError(f"unknown venue: {venue}")


# =========================================================================
# ARB COMPUTATION — three layers, two structures
# =========================================================================

@dataclass(frozen=True)
class MidDiscrepancy:
    """Layer 1: paper mid-price discrepancy (no fees, no size)."""
    market_id: str
    kalshi_mid: float | None
    polymarket_yes_mid: float | None
    polymarket_no_mid: float | None
    discrepancy_direct_cents: float | None       # 100 * (poly_yes_mid - kalshi_mid)
    discrepancy_synthetic_cents: float | None    # 100 * (1 - kalshi_mid - poly_no_mid)


@dataclass(frozen=True)
class CrossedBookArb:
    """Layer 2: is the book crossed across venues at top-of-book?"""
    market_id: str
    structure: str  # "direct" or "synthetic"
    crossed: bool
    lockable_spread_cents: float | None    # before fees
    max_size_at_top: float | None          # min(size on each leg)
    legs: dict | None                      # {"buy_leg": ..., "sell_leg": ...}


@dataclass(frozen=True)
class ExecutableArb:
    """Layer 3: walk the books, apply fees, compute realizable profit."""
    market_id: str
    structure: str  # "direct" or "synthetic"
    fillable_size: float
    gross_profit_dollars: float
    net_profit_dollars: float           # after fees
    net_profit_per_contract: float
    fees_paid_dollars: float
    legs: list[dict]                    # list of fill levels with sizes and prices


def _yes_mid(book: NormalizedBook) -> float | None:
    if not book.bids or not book.asks:
        return None
    return (book.bids[0].price + book.asks[0].price) / 2


def compute_mid_discrepancy(
    kalshi_yes_book: NormalizedBook,
    polymarket_yes_book: NormalizedBook,
    polymarket_no_book: NormalizedBook | None,
    market_id: str,
) -> MidDiscrepancy:
    """
    Layer 1: paper mid-price discrepancy.

    direct: poly_yes_mid - kalshi_yes_mid  (positive = YES cheaper on Kalshi)
    synthetic: 1 - kalshi_yes_mid - poly_no_mid  (positive = synthetic short cheaper)
    """
    kalshi_mid = _yes_mid(kalshi_yes_book)
    poly_yes_mid = _yes_mid(polymarket_yes_book)
    poly_no_mid = _yes_mid(polymarket_no_book) if polymarket_no_book else None

    direct_cents = None
    if kalshi_mid is not None and poly_yes_mid is not None:
        direct_cents = 100 * (poly_yes_mid - kalshi_mid)

    synthetic_cents = None
    if kalshi_mid is not None and poly_no_mid is not None:
        synthetic_cents = 100 * (1 - kalshi_mid - poly_no_mid)

    return MidDiscrepancy(
        market_id=market_id,
        kalshi_mid=kalshi_mid,
        polymarket_yes_mid=poly_yes_mid,
        polymarket_no_mid=poly_no_mid,
        discrepancy_direct_cents=direct_cents,
        discrepancy_synthetic_cents=synthetic_cents,
    )


def compute_crossed_book_arb_direct(
    kalshi_yes_book: NormalizedBook,
    polymarket_yes_book: NormalizedBook,
    market_id: str,
) -> CrossedBookArb:
    """
    Direct structure: buy YES on cheaper venue, sell YES on richer venue.
    Crossed iff cheaper_ask < richer_bid.
    """
    if not kalshi_yes_book.asks or not polymarket_yes_book.bids:
        return CrossedBookArb(market_id, "direct", False, None, None, None)
    if not kalshi_yes_book.bids or not polymarket_yes_book.asks:
        return CrossedBookArb(market_id, "direct", False, None, None, None)

    # Buy Kalshi (at ask), Sell Polymarket (at bid)
    kalshi_ask, kalshi_ask_size = kalshi_yes_book.asks[0].price, kalshi_yes_book.asks[0].size
    poly_bid, poly_bid_size = polymarket_yes_book.bids[0].price, polymarket_yes_book.bids[0].size

    # Buy Polymarket (at ask), Sell Kalshi (at bid)
    poly_ask, poly_ask_size = polymarket_yes_book.asks[0].price, polymarket_yes_book.asks[0].size
    kalshi_bid, kalshi_bid_size = kalshi_yes_book.bids[0].price, kalshi_yes_book.bids[0].size

    if poly_bid > kalshi_ask:
        return CrossedBookArb(
            market_id, "direct", True,
            lockable_spread_cents=100 * (poly_bid - kalshi_ask),
            max_size_at_top=min(kalshi_ask_size, poly_bid_size),
            legs={"buy": {"venue": "kalshi", "price": kalshi_ask, "size": kalshi_ask_size},
                  "sell": {"venue": "polymarket", "price": poly_bid, "size": poly_bid_size}},
        )
    if kalshi_bid > poly_ask:
        return CrossedBookArb(
            market_id, "direct", True,
            lockable_spread_cents=100 * (kalshi_bid - poly_ask),
            max_size_at_top=min(poly_ask_size, kalshi_bid_size),
            legs={"buy": {"venue": "polymarket", "price": poly_ask, "size": poly_ask_size},
                  "sell": {"venue": "kalshi", "price": kalshi_bid, "size": kalshi_bid_size}},
        )
    return CrossedBookArb(market_id, "direct", False, None, None, None)


def compute_crossed_book_arb_synthetic(
    kalshi_yes_book: NormalizedBook,
    polymarket_no_book: NormalizedBook | None,
    market_id: str,
) -> CrossedBookArb:
    """
    Synthetic structure: buy YES_Kalshi + buy NO_Polymarket. If combined ask
    sums to < $1.00, you've locked in risk-free profit equal to (1.00 - sum).
    """
    if polymarket_no_book is None:
        return CrossedBookArb(market_id, "synthetic", False, None, None, None)
    if not kalshi_yes_book.asks or not polymarket_no_book.asks:
        return CrossedBookArb(market_id, "synthetic", False, None, None, None)

    k_ask, k_size = kalshi_yes_book.asks[0].price, kalshi_yes_book.asks[0].size
    p_ask, p_size = polymarket_no_book.asks[0].price, polymarket_no_book.asks[0].size
    combined = k_ask + p_ask

    if combined < 1.0:
        return CrossedBookArb(
            market_id, "synthetic", True,
            lockable_spread_cents=100 * (1.0 - combined),
            max_size_at_top=min(k_size, p_size),
            legs={"yes_leg": {"venue": "kalshi", "price": k_ask, "size": k_size},
                  "no_leg": {"venue": "polymarket", "price": p_ask, "size": p_size}},
        )
    return CrossedBookArb(market_id, "synthetic", False, None, None, None)


def _walk_book_for_fillable(
    buy_book_asks: list[PriceLevel],
    sell_book_bids: list[PriceLevel],
    buy_venue: str,
    sell_venue: str,
    max_levels: int = 50,
    fee_ctx: FeeContext | None = None,
) -> tuple[float, float, float, list[dict]]:
    """
    Walk both books level-by-level. At each step, fill the smaller side.
    Stop when the prices cross back (buy_price >= sell_price after fees).
    Returns: (fillable_size, gross_pnl, fees_paid, legs_detail)
    """
    ctx = fee_ctx or FeeContext()
    fillable = 0.0
    gross_pnl = 0.0
    fees_paid = 0.0
    legs: list[dict] = []

    buy_idx, sell_idx = 0, 0
    buy_remaining = buy_book_asks[0].size if buy_book_asks else 0
    sell_remaining = sell_book_bids[0].size if sell_book_bids else 0

    iterations = 0
    while (buy_idx < len(buy_book_asks) and sell_idx < len(sell_book_bids)
           and iterations < max_levels):
        iterations += 1
        buy_price = buy_book_asks[buy_idx].price
        sell_price = sell_book_bids[sell_idx].price

        buy_cost = ctx.apply(buy_venue, "buy", buy_price, 1)
        sell_proceeds = ctx.apply(sell_venue, "sell", sell_price, 1)

        per_contract = sell_proceeds - buy_cost
        if per_contract <= 0:
            break

        fill_size = min(buy_remaining, sell_remaining)
        fillable += fill_size
        gross_pnl += fill_size * (sell_price - buy_price)
        fee_cost = fill_size * (buy_cost - buy_price) + fill_size * (sell_price - sell_proceeds)
        fees_paid += fee_cost
        legs.append({
            "level": iterations,
            "buy_venue": buy_venue, "buy_price": buy_price,
            "sell_venue": sell_venue, "sell_price": sell_price,
            "fill_size": fill_size,
            "per_contract_net": per_contract,
        })

        buy_remaining -= fill_size
        sell_remaining -= fill_size
        if buy_remaining == 0:
            buy_idx += 1
            buy_remaining = buy_book_asks[buy_idx].size if buy_idx < len(buy_book_asks) else 0
        if sell_remaining == 0:
            sell_idx += 1
            sell_remaining = sell_book_bids[sell_idx].size if sell_idx < len(sell_book_bids) else 0

    return fillable, gross_pnl, fees_paid, legs


def compute_executable_arb_direct(
    kalshi_yes_book: NormalizedBook,
    polymarket_yes_book: NormalizedBook,
    market_id: str,
    fee_ctx: FeeContext | None = None,
) -> ExecutableArb:
    """Layer 3 direct: walk books across venues, apply fees, return realizable profit."""
    # Direction 1: buy Kalshi, sell Polymarket
    size1, gross1, fees1, legs1 = _walk_book_for_fillable(
        kalshi_yes_book.asks, polymarket_yes_book.bids, "kalshi", "polymarket",
        fee_ctx=fee_ctx,
    )
    # Direction 2: buy Polymarket, sell Kalshi
    size2, gross2, fees2, legs2 = _walk_book_for_fillable(
        polymarket_yes_book.asks, kalshi_yes_book.bids, "polymarket", "kalshi",
        fee_ctx=fee_ctx,
    )

    net1 = gross1 - fees1
    net2 = gross2 - fees2

    if net1 >= net2:
        size, gross, fees, legs = size1, gross1, fees1, legs1
    else:
        size, gross, fees, legs = size2, gross2, fees2, legs2

    per_contract = (gross - fees) / size if size > 0 else 0.0

    return ExecutableArb(
        market_id=market_id, structure="direct",
        fillable_size=size, gross_profit_dollars=gross,
        net_profit_dollars=gross - fees, net_profit_per_contract=per_contract,
        fees_paid_dollars=fees, legs=legs,
    )


def compute_executable_arb_synthetic(
    kalshi_yes_book: NormalizedBook,
    polymarket_no_book: NormalizedBook | None,
    market_id: str,
    fee_ctx: FeeContext | None = None,
) -> ExecutableArb:
    """
    Layer 3 synthetic: buy YES_Kalshi + buy NO_Polymarket, walk both ask books
    until combined cost reaches $1.00 + fees.
    """
    if polymarket_no_book is None:
        return ExecutableArb(market_id, "synthetic", 0.0, 0.0, 0.0, 0.0, 0.0, [])

    ctx = fee_ctx or FeeContext()
    fillable = 0.0
    gross_pnl = 0.0
    fees_paid = 0.0
    legs: list[dict] = []

    k_idx, p_idx = 0, 0
    k_remaining = kalshi_yes_book.asks[0].size if kalshi_yes_book.asks else 0
    p_remaining = polymarket_no_book.asks[0].size if polymarket_no_book.asks else 0

    iterations = 0
    while (k_idx < len(kalshi_yes_book.asks) and p_idx < len(polymarket_no_book.asks)
           and iterations < 50):
        iterations += 1
        k_price = kalshi_yes_book.asks[k_idx].price
        p_price = polymarket_no_book.asks[p_idx].price

        k_cost = ctx.apply("kalshi", "buy", k_price, 1)
        p_cost = ctx.apply("polymarket", "buy", p_price, 1)
        combined_cost = k_cost + p_cost
        per_contract = 1.0 - combined_cost  # synthetic pays $1.00 at resolution

        if per_contract <= 0:
            break

        fill_size = min(k_remaining, p_remaining)
        fillable += fill_size
        gross_pnl += fill_size * (1.0 - k_price - p_price)
        fee_cost = fill_size * (k_cost - k_price) + fill_size * (p_cost - p_price)
        fees_paid += fee_cost
        legs.append({
            "level": iterations,
            "k_price": k_price, "p_price": p_price,
            "combined_with_fees": combined_cost,
            "fill_size": fill_size,
            "per_contract_net": per_contract,
        })

        k_remaining -= fill_size
        p_remaining -= fill_size
        if k_remaining == 0:
            k_idx += 1
            k_remaining = kalshi_yes_book.asks[k_idx].size if k_idx < len(kalshi_yes_book.asks) else 0
        if p_remaining == 0:
            p_idx += 1
            p_remaining = polymarket_no_book.asks[p_idx].size if p_idx < len(polymarket_no_book.asks) else 0

    per_contract_avg = (gross_pnl - fees_paid) / fillable if fillable > 0 else 0.0
    return ExecutableArb(
        market_id=market_id, structure="synthetic",
        fillable_size=fillable, gross_profit_dollars=gross_pnl,
        net_profit_dollars=gross_pnl - fees_paid, net_profit_per_contract=per_contract_avg,
        fees_paid_dollars=fees_paid, legs=legs,
    )
