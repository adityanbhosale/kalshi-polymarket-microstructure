"""Fee models for the batch-auction counterfactual study (Phase 1).

The per-venue fee FORMULAS are ported VERBATIM from `src/pm_micro/fees.py`
(the EXP-3a-corrected models used throughout the existing analysis):

  * Kalshi  — per-contract PARABOLIC: ``ceil(7 * multiplier * C * (1-C))`` cents.
  * Polymarket — proportional in notional: ``rate * price * size``; maker mode
    is zero unless a rebate applies, in which case it is NEGATIVE.

On top of those verbatim primitives this module adds the four study fee TIERS
behind one shared signature (`leg_fee`), so an arm can price any leg under any
tier without knowing the venue-specific formula:

  * ``Tier.RETAIL``            — Kalshi parabolic taker + Polymarket category taker.
  * ``Tier.RETAIL_PM_REBATE``  — Kalshi parabolic taker + Polymarket MAKER rebate
                                 (PM leg earns the rebate; negative fee).
  * ``Tier.INSTITUTIONAL``     — counterfactual flat 0.30% taker / 0.20% maker of
                                 notional, applied identically to BOTH venues.
                                 (Not offered by either venue — see fig_fee_cliff.)
  * ``Tier.ZERO``              — fee-free (the pre-fee / "free money" view).

All functions are pure and return fees in DOLLARS per the given size. A negative
return value is a rebate (a credit, not a cost). The sign of buy-vs-sell is NOT
applied here — callers add a buy fee to cost and subtract a sell fee from
proceeds (see `book.py`).
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

Side = Literal["buy", "sell"]
ExecutionMode = Literal["taker", "maker"]
Role = Literal["taker", "maker"]

# =========================================================================
# VERBATIM PORT from src/pm_micro/fees.py  (do not edit the formulas)
# =========================================================================

KALSHI_MULTIPLIER_BASE = 7.0
KALSHI_FEE_MULTIPLIER_DEFAULT = 1.0
KALSHI_MAKER_FRACTION = 0.25          # for fee_type="quadratic_with_maker_fees"

# Polymarket category taker rates (decimal fractions of notional). Source: venue
# fee schedule, May 2026; verified against per-market `feeSchedule.rate` on the
# Gamma API. Maker fees are zero; rebates default to a fraction of the taker fee.
CATEGORY_RATES: dict[str, float] = {
    "crypto":       0.072,
    "economics":    0.05,
    "culture":      0.05,
    "weather":      0.05,
    "finance":      0.04,
    "politics":     0.04,
    "tech":         0.04,
    "sports":       0.03,
    "geopolitics":  0.00,        # FEE-FREE umbrella
    "world_events": 0.00,        # alias
}

POLYMARKET_REBATE_FRACTION_DEFAULT = 0.22


def kalshi_fee(
    price: float,
    size: float = 1.0,
    side: Side = "buy",
    multiplier: float = KALSHI_FEE_MULTIPLIER_DEFAULT,
    execution_mode: ExecutionMode = "taker",
    maker_fraction: float = KALSHI_MAKER_FRACTION,
) -> float:
    """All-in Kalshi fee in dollars for `size` contracts at price `price`.

    Fee in cents is ``ceil(7 * multiplier * C * (1-C))``; maker mode ceils
    ``maker_fraction`` of the raw parabolic (pass `maker_fraction=0` for
    fee_type="quadratic" taker-only markets). Ported verbatim from
    `src/pm_micro/fees.py`.
    """
    if not 0.0 <= price <= 1.0:
        raise ValueError(f"Kalshi price must be in [0,1], got {price}")
    if size < 0:
        raise ValueError(f"size must be non-negative, got {size}")
    raw_cents = KALSHI_MULTIPLIER_BASE * multiplier * price * (1.0 - price)
    if execution_mode == "taker":
        fee_cents = math.ceil(raw_cents)
    elif execution_mode == "maker":
        if maker_fraction <= 0:
            return 0.0
        fee_cents = math.ceil(maker_fraction * raw_cents)
    else:
        raise ValueError(f"unknown execution_mode: {execution_mode}")
    return (fee_cents / 100.0) * size


def polymarket_rate_for_category(category: str | None) -> tuple[float, str]:
    """Resolve a category string to a (rate, resolved_key) pair.

    Ported verbatim from `src/pm_micro/fees.py`. None -> legacy 2% default;
    unmapped non-None -> most-conservative max rate flagged "_unmapped".
    """
    if category is None:
        return 0.02, "_legacy_default"
    norm = category.strip().lower()
    if norm in CATEGORY_RATES:
        return CATEGORY_RATES[norm], norm
    base = norm
    for suffix in ("_fees_v2", "_fees_v1", "_fees"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if base in CATEGORY_RATES:
        return CATEGORY_RATES[base], base
    synonyms: dict[str, str] = {
        "sport": "sports", "election": "politics", "elections": "politics",
        "us_politics": "politics", "political": "politics", "world": "geopolitics",
        "world-events": "geopolitics", "world_events": "geopolitics",
        "international": "geopolitics", "intl": "geopolitics",
        "entertainment": "culture", "pop_culture": "culture", "cultural": "culture",
        "ma": "culture", "m&a": "culture", "mergers": "culture", "ai": "tech",
        "technology": "tech", "macro": "economics", "macroeconomics": "economics",
        "btc": "crypto", "eth": "crypto", "cryptocurrency": "crypto",
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
    """All-in Polymarket fee in dollars. Ported verbatim from `src/pm_micro/fees.py`.

    Taker = ``rate * price * size``. Maker = 0 unless `use_rebate`, then the
    return is NEGATIVE (a rebate of `rebate_fraction` of the taker fee).
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


# =========================================================================
# STUDY FEE TIERS  (one shared signature on top of the verbatim primitives)
# =========================================================================

class Tier(Enum):
    """The four fee tiers from the EXP-3 fee-frontier / fig_fee_cliff analysis."""
    RETAIL = "retail"
    RETAIL_PM_REBATE = "retail_pm_rebate"
    INSTITUTIONAL = "institutional"   # counterfactual 0.30% taker / 0.20% maker
    ZERO = "zero"


# Counterfactual institutional tier — flat proportional, both venues identical.
# Not offered by either venue; used as the "unlock that doesn't exist" reference.
INSTITUTIONAL_TAKER_RATE = 0.0030   # 0.30%
INSTITUTIONAL_MAKER_RATE = 0.0020   # 0.20%


def leg_fee(
    venue: str,
    price: float,
    size: float = 1.0,
    *,
    tier: Tier,
    role: Role = "taker",
    category: str | None = None,
    pm_rate: float | None = None,
    kalshi_multiplier: float = KALSHI_FEE_MULTIPLIER_DEFAULT,
) -> float:
    """All-in fee in DOLLARS for ONE leg under a fee `tier` (negative = rebate).

    One shared signature for both venues / all tiers. `role` selects taker vs
    maker where the tier offers a choice (INSTITUTIONAL). The RETAIL_PM_REBATE
    tier forces the Polymarket leg to maker+rebate regardless of `role`, modeling
    the counterfactual where the PM leg is posted (earns the rebate) while the
    Kalshi leg is taken. `category`/`pm_rate` resolve the Polymarket category
    rate (prefer the per-market API `pm_rate` when available).
    """
    venue = venue.lower()
    if venue not in ("kalshi", "polymarket"):
        raise ValueError(f"unknown venue: {venue}")
    if role not in ("taker", "maker"):
        raise ValueError(f"unknown role: {role}")

    if tier is Tier.ZERO:
        return 0.0

    if tier is Tier.INSTITUTIONAL:
        rate = INSTITUTIONAL_TAKER_RATE if role == "taker" else INSTITUTIONAL_MAKER_RATE
        return rate * price * size

    if tier is Tier.RETAIL:
        if venue == "kalshi":
            return kalshi_fee(price, size, multiplier=kalshi_multiplier,
                              execution_mode=role)
        return polymarket_fee(price, size, category=category, rate=pm_rate,
                              execution_mode=role)

    if tier is Tier.RETAIL_PM_REBATE:
        if venue == "kalshi":
            # Retail Kalshi is unchanged (taker parabolic by default).
            return kalshi_fee(price, size, multiplier=kalshi_multiplier,
                              execution_mode=role)
        # PM leg is the maker that earns the rebate (negative fee).
        return polymarket_fee(price, size, category=category, rate=pm_rate,
                              execution_mode="maker", use_rebate=True)

    raise ValueError(f"unknown tier: {tier}")
