"""Fee models for Kalshi (parabolic) and Polymarket (category-dependent).

EXP-3a correction (2026-05-28). Replaces the stale flat-rate constants
previously hardcoded in `src/pm_micro/arb.py`:

    POLYMARKET_TAKER_FEE_RATE = 0.02   # flat 2% of notional
    KALSHI_PER_CONTRACT_FEE   = 0.02   # flat $0.02 / contract

Both models verified against live venue metadata (2026):

Kalshi (per-contract, parabolic in price):
    raw_cents   = multiplier_base * fee_multiplier * C * (1 - C)
    taker_cents = ceil(raw_cents)
    maker_cents = ceil(maker_fraction * raw_cents)        # zero when fee_type
                                                          # is "quadratic"
    fee_dollars = (taker_or_maker_cents / 100) * size

    `multiplier_base` is the standard 7 (cents). `fee_multiplier` is the
    per-series API field (1 for general markets, ~0.5 for some financial
    indices). At C=0.5 with the defaults this gives the historical 2¢.
    At the tails (C<0.10 or C>0.90) it collapses to 1¢ minimum.

Polymarket (proportional in notional, category-dependent):
    taker_dollars = rate * price * size
    maker_dollars = 0                             # by default
    maker_dollars = -rebate_fraction * rate * price * size  # if use_rebate=True

    `rate` is exposed directly per market as `feeSchedule.rate` on the
    Polymarket Gamma API. The CATEGORY_RATES table below is the documented
    fallback (used only when the per-market API field is unavailable).

The sign convention applied by `arb.apply_fee` is unchanged:
    buy:  returned effective price > nominal (added cost)
    sell: returned effective price < nominal (deducted proceeds)
"""

from __future__ import annotations

import math
from typing import Literal

Side = Literal["buy", "sell"]
ExecutionMode = Literal["taker", "maker"]

# Kalshi parabolic constants. The formula uses fee in CENTS, so
# `KALSHI_MULTIPLIER_BASE` is in cents-per-contract at the peak of the
# parabola (C*(1-C) max = 0.25). 7c * 0.25 = 1.75c → ceil → 2c at C=0.5,
# matching Kalshi's published schedule. `KALSHI_FEE_MULTIPLIER_DEFAULT`
# is the per-series scaling field (1 for general, ~0.5 for financial
# indices); pull the live value from the /series endpoint when
# available.
KALSHI_MULTIPLIER_BASE = 7.0
KALSHI_FEE_MULTIPLIER_DEFAULT = 1.0
KALSHI_MAKER_FRACTION = 0.25          # for fee_type="quadratic_with_maker_fees"

# Polymarket category taker rates (decimal fractions of notional).
# Source: venue fee schedule, May 2026. Verified against the per-market
# `feeSchedule.rate` field on the Gamma API. Maker fees are zero;
# rebates default to 25% of taker fee for the counterparty's leg.
#
# CAVEAT (EXP-3a, 2026-05-28): the synonym `m&a -> culture` is not
# semantically verified against Polymarket's taxonomy. Our one M&A
# market (Paramount/Warner Bros, KXTAKEOVERACQWB-27JUN30-PSKY) returns
# `feeType="tech_fees"` from Gamma, NOT culture or finance. The rate
# happens to coincide between tech (0.04) and culture (0.05) only at
# the politics tier — i.e. the verdict is unaffected by the mapping
# choice for this snapshot, but the `m&a -> culture` synonym should be
# re-examined when a fresh M&A market enters the panel. Always prefer
# the per-market `feeSchedule.rate` API field over CATEGORY_RATES
# lookup whenever both are available.
CATEGORY_RATES: dict[str, float] = {
    "crypto":      0.072,
    "economics":   0.05,
    "culture":     0.05,
    "weather":     0.05,
    "finance":     0.04,
    "politics":    0.04,
    "tech":        0.04,
    "sports":      0.03,
    "geopolitics": 0.00,        # FEE-FREE umbrella
    "world_events": 0.00,       # alias
}

# Default maker rebate as a fraction of counterparty taker rate. The
# Polymarket Gamma `feeSchedule.rebateRate` field reports 0.25 on every
# market in our 16-market panel; we default to 0.22 (midpoint of the
# 20-25% range cited in the schedule) for safety. Pass a per-market
# override (or 0.25) via `rebate_fraction=` to use the API value.
POLYMARKET_REBATE_FRACTION_DEFAULT = 0.22


# =========================================================================
# Kalshi parabolic fee
# =========================================================================

def kalshi_fee(
    price: float,
    size: float = 1.0,
    side: Side = "buy",
    multiplier: float = KALSHI_FEE_MULTIPLIER_DEFAULT,
    execution_mode: ExecutionMode = "taker",
    maker_fraction: float = KALSHI_MAKER_FRACTION,
) -> float:
    """Return all-in Kalshi fee in dollars for `size` contracts at price `price`.

    `multiplier` is the venue's `fee_multiplier` field (1 for general
    markets; ~0.5 for some financial indices). The fee in cents is
    ``ceil(7 * multiplier * C * (1-C))``. Maker mode multiplies the raw
    cents by `maker_fraction` (default 0.25) before ceiling — pass
    `maker_fraction=0` to model Kalshi's "quadratic" fee_type (taker-only).
    `side` is not used here; the +/- sign is applied by `arb.apply_fee`.
    """
    if not 0.0 <= price <= 1.0:
        raise ValueError(f"Kalshi price must be in [0,1], got {price}")
    if size < 0:
        raise ValueError(f"size must be non-negative, got {size}")
    raw_cents = KALSHI_MULTIPLIER_BASE * multiplier * price * (1.0 - price)
    if execution_mode == "taker":
        fee_cents = math.ceil(raw_cents)
    elif execution_mode == "maker":
        # Maker = `maker_fraction` of the raw (pre-ceil) parabolic, then
        # ceiled. With the default 0.25 this gives a 1¢ floor in the
        # body and zero at the very edges. For Kalshi markets whose
        # `fee_type` is "quadratic" (taker-only), pass maker_fraction=0.
        if maker_fraction <= 0:
            return 0.0
        fee_cents = math.ceil(maker_fraction * raw_cents)
    else:
        raise ValueError(f"unknown execution_mode: {execution_mode}")
    return (fee_cents / 100.0) * size


# =========================================================================
# Polymarket category fee
# =========================================================================

def polymarket_rate_for_category(category: str | None) -> tuple[float, str]:
    """Resolve a category string to a (rate, resolved_key) pair.

    Tries exact lowercase match against CATEGORY_RATES first, then a small
    synonym map for common venue strings ('sports_fees_v2', 'politics_fees',
    'tech_fees', 'crypto_fees', 'world-events'). If still unmapped and the
    input is non-None, returns (max(CATEGORY_RATES), "_unmapped") so the
    caller can flag the assumption (most conservative rate). If the input
    is None (no category info at all), returns (0.02, "_legacy_default")
    to preserve backward compatibility with pre-EXP-3a callers that don't
    know about categories.
    """
    if category is None:
        return 0.02, "_legacy_default"
    norm = category.strip().lower()
    if norm in CATEGORY_RATES:
        return CATEGORY_RATES[norm], norm
    # strip venue-internal '_fees', '_fees_v2' suffixes
    base = norm
    for suffix in ("_fees_v2", "_fees_v1", "_fees"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if base in CATEGORY_RATES:
        return CATEGORY_RATES[base], base
    # synonyms
    synonyms: dict[str, str] = {
        "sport":         "sports",
        "election":      "politics",
        "elections":     "politics",
        "us_politics":   "politics",
        "political":     "politics",
        "world":         "geopolitics",
        "world-events":  "geopolitics",
        "world_events":  "geopolitics",
        "international": "geopolitics",
        "intl":          "geopolitics",
        "entertainment": "culture",
        "pop_culture":   "culture",
        "cultural":      "culture",
        "ma":            "culture",
        "m&a":           "culture",
        "mergers":       "culture",
        "ai":            "tech",
        "technology":    "tech",
        "macro":         "economics",
        "macroeconomics": "economics",
        "btc":           "crypto",
        "eth":           "crypto",
        "cryptocurrency": "crypto",
    }
    base2 = base.replace(" ", "_").replace("-", "_")
    if base2 in synonyms:
        return CATEGORY_RATES[synonyms[base2]], synonyms[base2]
    return max(CATEGORY_RATES.values()), "_unmapped"


def polymarket_fee(
    price: float,
    size: float = 1.0,
    side: Side = "buy",
    category: str | None = None,
    rate: float | None = None,
    execution_mode: ExecutionMode = "taker",
    use_rebate: bool = False,
    rebate_fraction: float = POLYMARKET_REBATE_FRACTION_DEFAULT,
) -> float:
    """Return all-in Polymarket fee in dollars for `size` contracts.

    Pass either `category` (looked up via `polymarket_rate_for_category`)
    or `rate` directly (overrides category). With no category and no rate,
    falls back to the legacy 2% flat assumption — see the docstring on
    `polymarket_rate_for_category` for the rationale. Maker fees are
    zero unless `use_rebate=True`, in which case the return value is
    NEGATIVE (a rebate from the counterparty's taker fee).
    """
    if not 0.0 <= price <= 1.0:
        raise ValueError(f"Polymarket price must be in [0,1], got {price}")
    if size < 0:
        raise ValueError(f"size must be non-negative, got {size}")
    if rate is None:
        rate, _ = polymarket_rate_for_category(category)
    if execution_mode == "taker":
        return rate * price * size
    if execution_mode != "maker":
        raise ValueError(f"unknown execution_mode: {execution_mode}")
    if not use_rebate:
        return 0.0
    return -rebate_fraction * rate * price * size
