"""Kalshi public market data endpoints. No authentication required.

Orderbook response shape: the JSON returned by /markets/{ticker}/orderbook contains
an ``orderbook_fp`` key with both ``yes_dollars`` and ``no_dollars`` arrays — i.e.
both sides of the book are returned directly, in dollar-denominated price levels.
There is no need to reconstruct asks from NO bids.
"""

from __future__ import annotations

import httpx

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

_client = httpx.Client(base_url=BASE_URL, timeout=10.0)


def get_orderbook(ticker: str) -> dict:
    """GET /markets/{ticker}/orderbook — returns the raw JSON response.

    The dict has an ``orderbook_fp`` key with ``yes_dollars`` and ``no_dollars``
    arrays of [price, size] levels (both sides of the book).
    """
    resp = _client.get(f"/markets/{ticker}/orderbook")
    resp.raise_for_status()
    return resp.json()


def get_market(ticker: str) -> dict:
    """GET /markets/{ticker} — returns the raw JSON response."""
    resp = _client.get(f"/markets/{ticker}")
    resp.raise_for_status()
    return resp.json()


def search_markets(
    series_ticker: str | None = None,
    status: str = "open",
    limit: int = 200,
    min_volume: float | None = None,
) -> list[dict]:
    """
    Search Kalshi markets via the public /markets endpoint.

    Args:
        series_ticker: Filter to a specific series (e.g. "KXFEDHIKE", "KXBTC").
                       If None, returns markets across all series.
        status: "open", "closed", or "settled". Default "open".
        limit: Max results to return (Kalshi paginates; this fetches one page).
        min_volume: If set, filters results to markets with volume >= this value.

    Returns:
        List of market dicts with keys: ticker, title, yes_sub_title, status,
        volume, open_interest, close_time, expected_expiration_time, etc.
    """
    params: dict[str, str | int] = {"status": status, "limit": limit}
    if series_ticker is not None:
        params["series_ticker"] = series_ticker.upper()

    resp = _client.get("/markets", params=params)
    resp.raise_for_status()
    markets = resp.json().get("markets", [])

    if min_volume is not None:
        markets = [m for m in markets if (m.get("volume") or 0) >= min_volume]

    return markets
