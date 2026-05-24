"""Polymarket public market data via py-clob-client (read-only) and Gamma API."""

from __future__ import annotations

import httpx
from py_clob_client.client import ClobClient

HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"

_client = ClobClient(HOST)


def get_orderbook(token_id: str):
    """Return the OrderBookSummary for a CLOB token id."""
    return _client.get_order_book(token_id)


def get_midpoint(token_id: str) -> float:
    """Return the midpoint price for a CLOB token id."""
    resp = _client.get_midpoint(token_id)
    if isinstance(resp, dict):
        return float(resp.get("mid", resp.get("midpoint")))
    return float(resp)


def search_markets(query: str, limit: int = 10) -> list[dict]:
    """Search active Polymarket markets via the Gamma API.

    Returns a list of dicts with: question, condition_id, clobTokenIds (list of 2 token IDs),
    volume.
    """
    params = {"active": "true", "closed": "false", "limit": limit}
    with httpx.Client(timeout=10.0) as http:
        resp = http.get(f"{GAMMA_HOST}/markets", params=params)
        resp.raise_for_status()
        markets = resp.json()

    needle = query.lower()
    out: list[dict] = []
    for m in markets:
        question = m.get("question", "")
        if needle not in question.lower():
            continue
        out.append(
            {
                "question": question,
                "condition_id": m.get("conditionId") or m.get("condition_id"),
                "clobTokenIds": m.get("clobTokenIds"),
                "volume": m.get("volume"),
            }
        )
    return out
