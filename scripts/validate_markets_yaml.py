"""Sanity-check every entry in ``markets.yaml``.

Per-pair checks (collected, not short-circuited):
 * Kalshi market + orderbook fetch must succeed (no 404).
 * Polymarket ``condition_id`` is 66 chars and starts with ``0x``.
 * Polymarket ``yes_token_id`` and ``no_token_id`` are each 77 chars
   (``len(token_id) == 77`` — the same assertion that would have caught the
   Phase 2 NYK truncation regression).
 * Polymarket orderbook fetch for each token. A 404 is tolerated **only** when
   the entry explicitly opts in via ``polymarket.<side>_token_orderbook_status``
   set to a value beginning with ``"404"`` (e.g. ``"404_unlisted"``,
   ``"404_observed_..."``). Otherwise it's an error.

Errors from all pairs are collected and printed together; the script exits 1
when there is at least one. Used as the regression gate after every
``markets.yaml`` change and as a CI-style precheck before D.2 expansions.

Usage: ``uv run python scripts/validate_markets_yaml.py``
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import yaml

from pm_micro.clients import kalshi, polymarket
from pm_micro.discovery import (
    POLYMARKET_CONDITION_ID_LEN,
    POLYMARKET_TOKEN_ID_MAX_LEN,
    POLYMARKET_TOKEN_ID_MIN_LEN,
    validate_polymarket_ids,
)

REPO_ROOT = Path(__file__).parent.parent
MARKETS_PATH = REPO_ROOT / "markets.yaml"

# Map yaml-side labels -> the corresponding token-id field.
TOKEN_SIDES: tuple[tuple[str, str, str], ...] = (
    ("yes", "yes_token_id", "yes_token_orderbook_status"),
    ("no", "no_token_id", "no_token_orderbook_status"),
)


def _is_explicitly_delisted(status_value: object) -> bool:
    """A status string starting with ``404`` opts a token out of strict checks."""
    if not isinstance(status_value, str):
        return False
    return status_value.strip().lower().startswith("404")


def _check_kalshi(entry: dict, errors: list[str]) -> None:
    mid = entry.get("id", "<unknown>")
    kalshi_block = entry.get("kalshi") or {}
    ticker = kalshi_block.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        errors.append(f"[{mid}] kalshi.ticker missing or non-string")
        return

    try:
        kalshi.get_market(ticker)
    except Exception as e:
        errors.append(f"[{mid}] kalshi.get_market({ticker!r}) failed: {e}")
        return

    try:
        kalshi.get_orderbook(ticker)
    except Exception as e:
        errors.append(f"[{mid}] kalshi.get_orderbook({ticker!r}) failed: {e}")


def _check_polymarket_ids(entry: dict, errors: list[str]) -> None:
    mid = entry.get("id", "<unknown>")
    poly = entry.get("polymarket") or {}
    result = validate_polymarket_ids(
        poly.get("condition_id"),
        poly.get("yes_token_id"),
        poly.get("no_token_id"),
    )
    for err in result.errors:
        errors.append(f"[{mid}] polymarket id: {err}")


def _check_polymarket_orderbooks(entry: dict, errors: list[str]) -> None:
    mid = entry.get("id", "<unknown>")
    poly = entry.get("polymarket") or {}

    for side_label, tid_field, status_field in TOKEN_SIDES:
        tid = poly.get(tid_field)
        if not isinstance(tid, str) or not (
            POLYMARKET_TOKEN_ID_MIN_LEN <= len(tid) <= POLYMARKET_TOKEN_ID_MAX_LEN
            and tid.isdigit()
        ):
            # Shape error already reported by _check_polymarket_ids; don't pile on.
            continue
        delisted_ok = _is_explicitly_delisted(poly.get(status_field))
        try:
            polymarket.get_orderbook(tid)
        except Exception as e:
            if delisted_ok:
                print(
                    f"  [{mid}] polymarket {side_label}: 404/error tolerated "
                    f"(marked delisted via {status_field}={poly.get(status_field)!r}): {e}"
                )
            else:
                errors.append(
                    f"[{mid}] polymarket {side_label} orderbook fetch failed "
                    f"({tid_field}): {e}"
                )
        # Be courteous to the public CLOB regardless of outcome.
        time.sleep(0.5)


def main() -> int:
    if not MARKETS_PATH.exists():
        print(f"❌ {MARKETS_PATH} not found", file=sys.stderr)
        return 1

    with open(MARKETS_PATH) as f:
        entries = yaml.safe_load(f) or []

    if not isinstance(entries, list):
        print(f"❌ {MARKETS_PATH} must be a YAML list at top level", file=sys.stderr)
        return 1

    errors: list[str] = []
    print(f"Validating {len(entries)} entries from {MARKETS_PATH}")
    print(
        f"  condition_id len = {POLYMARKET_CONDITION_ID_LEN}, "
        f"token_id len ∈ [{POLYMARKET_TOKEN_ID_MIN_LEN}, "
        f"{POLYMARKET_TOKEN_ID_MAX_LEN}] and all-digits"
    )

    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"Non-dict entry: {entry!r}")
            continue
        mid = entry.get("id", "<unknown>")
        print(f"\n--- {mid} ---")
        _check_kalshi(entry, errors)
        _check_polymarket_ids(entry, errors)
        _check_polymarket_orderbooks(entry, errors)

    print()
    if errors:
        print(f"❌ {len(errors)} validation error(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"OK: {len(entries)} pairs validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
