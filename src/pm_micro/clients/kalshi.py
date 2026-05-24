"""Kalshi public market data endpoints. No authentication required.

Note: Kalshi orderbook returns bid-only data — asks on YES are reconstructable as
(1 - bid on NO).
"""

from __future__ import annotations

import httpx

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

_client = httpx.Client(base_url=BASE_URL, timeout=10.0)


def get_orderbook(ticker: str) -> dict:
    """GET /markets/{ticker}/orderbook — returns the raw JSON response.

    The dict has an "orderbook" key with "yes" and "no" bid arrays.
    """
    resp = _client.get(f"/markets/{ticker}/orderbook")
    resp.raise_for_status()
    return resp.json()


def get_market(ticker: str) -> dict:
    """GET /markets/{ticker} — returns the raw JSON response."""
    resp = _client.get(f"/markets/{ticker}")
    resp.raise_for_status()
    return resp.json()
