from pm_micro.normalize import (
    normalize_kalshi_orderbook,
)


def test_kalshi_ask_reconstruction():
    """Kalshi asks must be reconstructed from the opposite side's bids via 1-p."""
    raw = {
        "orderbook_fp": {
            "yes_dollars": [["0.40", "100"], ["0.39", "200"]],
            "no_dollars":  [["0.59", "150"], ["0.58", "250"]],
        }
    }
    yes_book, no_book = normalize_kalshi_orderbook(raw, "test_market", "2026-05-25T00:00:00Z")

    # YES bids come straight from yes_dollars, sorted descending
    assert yes_book.bids[0].price == 0.40
    assert yes_book.bids[0].size == 100.0
    assert yes_book.bids[1].price == 0.39

    # YES asks reconstructed from NO bids: ask = 1 - no_bid
    # NO bids: 0.59, 0.58 → YES asks: 0.41, 0.42 (sorted ascending)
    assert yes_book.asks[0].price == 0.41
    assert yes_book.asks[0].size == 150.0  # size preserved from no_bid
    assert yes_book.asks[1].price == 0.42

    # Symmetric for NO book
    assert no_book.bids[0].price == 0.59
    assert no_book.asks[0].price == round(1 - 0.40, 4)  # 0.60


def test_kalshi_empty_book():
    """Empty orderbook should normalize to empty bids/asks, not crash."""
    raw = {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
    yes_book, no_book = normalize_kalshi_orderbook(raw, "empty", "2026-05-25T00:00:00Z")
    assert yes_book.bids == []
    assert yes_book.asks == []


from pm_micro.arb import (
    apply_fee, compute_mid_discrepancy,
    compute_crossed_book_arb_direct, compute_executable_arb_direct,
)
from pm_micro.normalize import NormalizedBook, PriceLevel


def _make_book(venue, market_id, side, bids, asks):
    return NormalizedBook(
        venue=venue, market_id=market_id, side=side,
        bids=[PriceLevel(p, s) for p, s in bids],
        asks=[PriceLevel(p, s) for p, s in asks],
        fetched_at="2026-05-25T00:00:00Z",
    )


def test_fees_directional():
    # Kalshi buy at 0.50 → costs 0.52
    assert apply_fee("kalshi", "buy", 0.50, 1) == 0.52
    # Polymarket buy at 0.50 → costs 0.51
    assert apply_fee("polymarket", "buy", 0.50, 1) == 0.51
    # Polymarket sell at 0.50 → proceeds 0.49
    assert apply_fee("polymarket", "sell", 0.50, 1) == 0.49


def test_mid_discrepancy_clean_pair():
    # OKC-like: Kalshi at 0.475 mid, Polymarket YES at 0.485 mid, NO at 0.515 mid
    k = _make_book("kalshi", "test", "yes", [(0.47, 100)], [(0.48, 100)])
    p_yes = _make_book("polymarket", "test", "yes", [(0.48, 100)], [(0.49, 100)])
    p_no = _make_book("polymarket", "test", "no", [(0.51, 100)], [(0.52, 100)])
    md = compute_mid_discrepancy(k, p_yes, p_no, "test")
    assert md.kalshi_mid == 0.475
    assert md.polymarket_yes_mid == 0.485
    assert abs(md.discrepancy_direct_cents - 1.0) < 0.001  # 1¢ direct discrepancy
    # synthetic: 1 - 0.475 - 0.515 = 0.01 → 1.0 cents
    assert abs(md.discrepancy_synthetic_cents - 1.0) < 0.001


def test_no_crossed_book():
    # Kalshi ask 0.48 > Polymarket bid 0.48 (equal, not crossed)
    k = _make_book("kalshi", "test", "yes", [(0.47, 100)], [(0.48, 100)])
    p = _make_book("polymarket", "test", "yes", [(0.48, 100)], [(0.49, 100)])
    arb = compute_crossed_book_arb_direct(k, p, "test")
    assert arb.crossed == False


def test_yes_crossed_book():
    # Kalshi ask 0.45 < Polymarket bid 0.50 → can buy K, sell P
    k = _make_book("kalshi", "test", "yes", [(0.44, 100)], [(0.45, 200)])
    p = _make_book("polymarket", "test", "yes", [(0.50, 150)], [(0.51, 150)])
    arb = compute_crossed_book_arb_direct(k, p, "test")
    assert arb.crossed == True
    assert abs(arb.lockable_spread_cents - 5.0) < 0.001  # 5¢ before fees
    assert arb.max_size_at_top == 150  # min(200, 150)
