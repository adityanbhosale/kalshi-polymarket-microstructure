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
