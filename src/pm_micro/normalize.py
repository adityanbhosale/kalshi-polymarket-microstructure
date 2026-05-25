"""Normalize raw venue orderbooks into a common schema."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PriceLevel:
    price: float       # in dollars, 0.0 to 1.0
    size: float        # number of contracts


@dataclass(frozen=True)
class NormalizedBook:
    venue: Literal["kalshi", "polymarket"]
    market_id: str             # the markets.yaml id (e.g. "nba_finals_okc")
    side: Literal["yes", "no"] # which outcome token this book represents
    bids: list[PriceLevel]     # sorted descending by price (best bid first)
    asks: list[PriceLevel]     # sorted ascending by price (best ask first)
    fetched_at: str            # ISO 8601 UTC timestamp
    raw_source: dict | None = None  # optional, for debugging


def normalize_kalshi_orderbook(
    raw: dict,
    market_id: str,
    fetched_at: str,
) -> tuple[NormalizedBook, NormalizedBook]:
    """
    Normalize a Kalshi orderbook response into separate YES and NO books.

    Kalshi returns:
      {"orderbook_fp": {"yes_dollars": [[price_str, size_str], ...],
                        "no_dollars":  [[price_str, size_str], ...]}}

    Both arrays are bids. Asks are reconstructed:
      - Ask on YES at price p ≡ Bid on NO at (1 - p), size unchanged
      - Ask on NO at price p ≡ Bid on YES at (1 - p), size unchanged

    Returns: (yes_book, no_book)
    """
    ob = raw.get("orderbook_fp", {}) or raw.get("orderbook", {})
    yes_bids_raw = ob.get("yes_dollars", []) or []
    no_bids_raw = ob.get("no_dollars", []) or []

    yes_bids = sorted(
        [PriceLevel(float(p), float(s)) for p, s in yes_bids_raw],
        key=lambda x: -x.price,
    )
    no_bids = sorted(
        [PriceLevel(float(p), float(s)) for p, s in no_bids_raw],
        key=lambda x: -x.price,
    )

    yes_asks = sorted(
        [PriceLevel(round(1.0 - b.price, 4), b.size) for b in no_bids],
        key=lambda x: x.price,
    )
    no_asks = sorted(
        [PriceLevel(round(1.0 - b.price, 4), b.size) for b in yes_bids],
        key=lambda x: x.price,
    )

    yes_book = NormalizedBook(
        venue="kalshi", market_id=market_id, side="yes",
        bids=yes_bids, asks=yes_asks, fetched_at=fetched_at, raw_source=raw,
    )
    no_book = NormalizedBook(
        venue="kalshi", market_id=market_id, side="no",
        bids=no_bids, asks=no_asks, fetched_at=fetched_at, raw_source=raw,
    )
    return yes_book, no_book


def normalize_polymarket_orderbook(
    book,
    market_id: str,
    side: Literal["yes", "no"],
    fetched_at: str,
) -> NormalizedBook:
    """
    Normalize a Polymarket OrderBookSummary into a NormalizedBook.

    Polymarket returns bids and asks directly as lists of OrderSummary objects
    with .price and .size as string-encoded floats.
    """
    bids = sorted(
        [PriceLevel(float(b.price), float(b.size)) for b in (book.bids or [])],
        key=lambda x: -x.price,
    )
    asks = sorted(
        [PriceLevel(float(a.price), float(a.size)) for a in (book.asks or [])],
        key=lambda x: x.price,
    )
    return NormalizedBook(
        venue="polymarket", market_id=market_id, side=side,
        bids=bids, asks=asks, fetched_at=fetched_at,
    )
