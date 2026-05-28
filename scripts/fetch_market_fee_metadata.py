"""EXP-3a: fetch per-market fee metadata from Kalshi /series and Polymarket Gamma.

For each market in markets.yaml, pulls:
  Kalshi side:    /series/{prefix} → fee_multiplier, fee_type, category
  Polymarket side: /markets?condition_ids=... → feeSchedule.rate, feeType,
                   feeSchedule.takerOnly, feeSchedule.rebateRate, makerBaseFee,
                   takerBaseFee, feesEnabled, events[0].title

Writes data/processed/market_fee_metadata.yaml with the resolved
taker_rate / maker_fraction / rebate_fraction per venue per market.
Flags any ambiguous or unmapped category for human review.

Usage:
    uv run python scripts/fetch_market_fee_metadata.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pm_micro.fees import polymarket_rate_for_category  # noqa: E402

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
POLY_GAMMA = "https://gamma-api.polymarket.com"
MARKETS_YAML = ROOT / "markets.yaml"
OUT_YAML = ROOT / "data" / "processed" / "market_fee_metadata.yaml"


def _kalshi_series_prefix(ticker: str) -> str:
    """Return the series prefix from a market ticker.

    KXNBA-26-OKC → KXNBA
    KXCOLOMBIAPRES-26-AESP → KXCOLOMBIAPRES
    KXCOLOMBIAPRESR1-26MAY31-ICAS → KXCOLOMBIAPRESR1
    """
    return ticker.split("-")[0]


def _fetch_kalshi_series(prefix: str) -> dict[str, Any]:
    with httpx.Client(timeout=10.0) as http:
        r = http.get(f"{KALSHI_BASE}/series/{prefix}")
        r.raise_for_status()
        data = r.json()
    return data.get("series", data) if isinstance(data, dict) else {}


def _fetch_polymarket_market(condition_id: str) -> dict[str, Any]:
    with httpx.Client(timeout=10.0) as http:
        r = http.get(f"{POLY_GAMMA}/markets", params={"condition_ids": condition_id})
        r.raise_for_status()
        data = r.json()
    if isinstance(data, list) and data:
        return data[0]
    return {}


def resolve_kalshi_fee_params(prefix: str, series_cache: dict) -> dict[str, Any]:
    """Look up cached /series data; map fee_multiplier + fee_type → params.

    fee_type:
      "quadratic"                     → maker_fraction = 0 (taker only)
      "quadratic_with_maker_fees"     → maker_fraction = 0.25
    fee_multiplier:
      raw API field, default 1.0 for general categories.
    """
    series = series_cache.get(prefix)
    if not series:
        return {
            "category_raw": None,
            "fee_multiplier": 1.0,
            "fee_type": None,
            "taker_multiplier_base": 7.0,
            "maker_fraction": 0.25,
            "source": "fallback_default",
        }
    fee_type = series.get("fee_type")
    return {
        "category_raw": series.get("category"),
        "fee_multiplier": float(series.get("fee_multiplier") or 1.0),
        "fee_type": fee_type,
        "taker_multiplier_base": 7.0,
        "maker_fraction": 0.0 if fee_type == "quadratic" else 0.25,
        "source": "kalshi_series_api",
    }


def resolve_polymarket_fee_params(market: dict) -> dict[str, Any]:
    """Map Polymarket Gamma fields → resolved fee parameters.

    Prefers the per-market `feeSchedule.rate` field over the category
    lookup. Reports both for transparency. Tags ambiguity if the API
    category is null AND no feeSchedule is present.
    """
    if not market:
        return {
            "fee_type": None,
            "event_category": None,
            "event_title": None,
            "api_rate": None,
            "api_taker_only": None,
            "api_rebate_rate": None,
            "resolved_rate": polymarket_rate_for_category(None)[0],
            "resolved_category_key": "_no_market",
            "rate_source": "fallback_no_market",
            "ambiguous": True,
            "ambiguity_notes": "market not found on Gamma",
        }
    fee_type = market.get("feeType")
    fee_schedule = market.get("feeSchedule") or {}
    api_rate = fee_schedule.get("rate")
    taker_only = fee_schedule.get("takerOnly")
    rebate_rate = fee_schedule.get("rebateRate")
    fees_enabled = market.get("feesEnabled")
    events = market.get("events") or []
    event_category = events[0].get("category") if events else None
    event_title = events[0].get("title") if events else None
    rate_table_lookup, key = polymarket_rate_for_category(fee_type or event_category)
    resolved_rate = float(api_rate) if api_rate is not None else rate_table_lookup
    if fees_enabled is False:
        resolved_rate = 0.0
    ambiguous = False
    notes: list[str] = []
    if api_rate is None:
        notes.append("no feeSchedule.rate on market")
        ambiguous = True
    if fee_type is None and event_category is None:
        notes.append("both feeType and event.category are null")
        ambiguous = True
    if key == "_unmapped":
        notes.append(f"feeType '{fee_type}' unmapped; using max rate")
        ambiguous = True
    rate_source = (
        "polymarket_gamma_feeSchedule" if api_rate is not None
        else f"category_table[{key}]"
    )
    return {
        "fee_type": fee_type,
        "event_category": event_category,
        "event_title": event_title,
        "api_rate": api_rate,
        "api_taker_only": taker_only,
        "api_rebate_rate": rebate_rate,
        "api_fees_enabled": fees_enabled,
        "resolved_rate": resolved_rate,
        "resolved_category_key": key,
        "rate_source": rate_source,
        "ambiguous": ambiguous,
        "ambiguity_notes": "; ".join(notes) if notes else None,
    }


def main() -> int:
    with open(MARKETS_YAML) as f:
        markets = yaml.safe_load(f)
    series_prefixes = sorted({_kalshi_series_prefix(m["kalshi"]["ticker"]) for m in markets})
    print(f"Fetching {len(series_prefixes)} unique Kalshi series...")
    series_cache: dict[str, dict] = {}
    for prefix in series_prefixes:
        try:
            series_cache[prefix] = _fetch_kalshi_series(prefix)
            time.sleep(0.1)
            print(f"  ✓ {prefix:24s} category={series_cache[prefix].get('category')!r:14s} fee_mult={series_cache[prefix].get('fee_multiplier')} fee_type={series_cache[prefix].get('fee_type')!r}")
        except Exception as e:
            print(f"  ✗ {prefix}: {e}", file=sys.stderr)

    print(f"\nFetching {len(markets)} Polymarket markets from Gamma...")
    out: list[dict] = []
    for m in markets:
        market_id = m["id"]
        ticker = m["kalshi"]["ticker"]
        prefix = _kalshi_series_prefix(ticker)
        condition_id = m["polymarket"]["condition_id"]
        try:
            pm_market = _fetch_polymarket_market(condition_id)
        except Exception as e:
            print(f"  ✗ {market_id}: gamma fetch failed: {e}", file=sys.stderr)
            pm_market = {}
        kalshi_fee_params = resolve_kalshi_fee_params(prefix, series_cache)
        pm_fee_params = resolve_polymarket_fee_params(pm_market)
        ambiguous_marker = " [!] " if pm_fee_params.get("ambiguous") else "     "
        print(f"  {ambiguous_marker}{market_id:32s} k_cat={kalshi_fee_params.get('category_raw')!r:12s} pm_type={pm_fee_params.get('fee_type')!r:24s} pm_rate={pm_fee_params.get('resolved_rate')}")
        out.append({
            "market_id": market_id,
            "internal_category": m.get("category"),
            "kalshi": {
                "series_prefix": prefix,
                "ticker": ticker,
                **kalshi_fee_params,
            },
            "polymarket": {
                "condition_id": condition_id,
                **pm_fee_params,
            },
        })
        time.sleep(0.1)

    OUT_YAML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_YAML, "w") as f:
        yaml.safe_dump(out, f, sort_keys=False, default_flow_style=False)
    print(f"\nWrote {OUT_YAML.relative_to(ROOT)} with {len(out)} entries.")

    n_ambiguous = sum(1 for e in out if e["polymarket"].get("ambiguous"))
    print(f"Ambiguous/unmapped Polymarket categories: {n_ambiguous} of {len(out)}")
    if n_ambiguous:
        print("STOP candidates (per EXP-3a guardrail). Review before running exp3a_fee_correction.py:")
        for e in out:
            if e["polymarket"].get("ambiguous"):
                print(f"  - {e['market_id']}: {e['polymarket'].get('ambiguity_notes')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
