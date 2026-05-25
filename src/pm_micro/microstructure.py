"""Per-venue microstructure metrics: spread, depth, mid."""

from dataclasses import asdict, dataclass

from .normalize import NormalizedBook


@dataclass(frozen=True)
class Microstructure:
    venue: str
    market_id: str
    side: str
    fetched_at: str

    best_bid: float | None
    best_ask: float | None
    best_bid_size: float | None
    best_ask_size: float | None

    mid_simple: float | None              # (best_bid + best_ask) / 2
    mid_size_weighted: float | None       # weighted by best_bid_size, best_ask_size

    spread_abs: float | None              # best_ask - best_bid (in dollars)
    spread_bps: float | None              # 10_000 * spread_abs / mid_simple

    depth_top_of_book: float              # best_bid_size + best_ask_size
    depth_within_1c: float                # total size on both sides within $0.01 of mid_simple
    depth_within_5c: float                # total size on both sides within $0.05 of mid_simple

    n_bid_levels: int
    n_ask_levels: int

    def to_dict(self) -> dict:
        return asdict(self)


def compute_microstructure(book: NormalizedBook) -> Microstructure:
    """Compute microstructure metrics for a single normalized orderbook."""
    best_bid = book.bids[0].price if book.bids else None
    best_ask = book.asks[0].price if book.asks else None
    best_bid_size = book.bids[0].size if book.bids else None
    best_ask_size = book.asks[0].size if book.asks else None

    mid_simple = None
    if best_bid is not None and best_ask is not None:
        mid_simple = (best_bid + best_ask) / 2

    mid_size_weighted = None
    if (
        best_bid is not None and best_ask is not None
        and best_bid_size and best_ask_size
        and (best_bid_size + best_ask_size) > 0
    ):
        # The side with more size pulls the mid toward the other side's price.
        total = best_bid_size + best_ask_size
        mid_size_weighted = (best_bid * best_ask_size + best_ask * best_bid_size) / total

    spread_abs = None
    spread_bps = None
    if best_bid is not None and best_ask is not None:
        spread_abs = best_ask - best_bid
        if mid_simple and mid_simple > 0:
            spread_bps = 10_000 * spread_abs / mid_simple

    depth_top = (best_bid_size or 0) + (best_ask_size or 0)

    def _depth_within(threshold: float) -> float:
        if mid_simple is None:
            return 0.0
        lo, hi = mid_simple - threshold, mid_simple + threshold
        bid_size = sum(b.size for b in book.bids if b.price >= lo)
        ask_size = sum(a.size for a in book.asks if a.price <= hi)
        return bid_size + ask_size

    return Microstructure(
        venue=book.venue,
        market_id=book.market_id,
        side=book.side,
        fetched_at=book.fetched_at,
        best_bid=best_bid,
        best_ask=best_ask,
        best_bid_size=best_bid_size,
        best_ask_size=best_ask_size,
        mid_simple=mid_simple,
        mid_size_weighted=mid_size_weighted,
        spread_abs=spread_abs,
        spread_bps=spread_bps,
        depth_top_of_book=depth_top,
        depth_within_1c=_depth_within(0.01),
        depth_within_5c=_depth_within(0.05),
        n_bid_levels=len(book.bids),
        n_ask_levels=len(book.asks),
    )
