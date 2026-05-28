"""Unit tests for src/pm_micro/fees.py (EXP-3a corrected fee models)."""

import math

import pytest

from pm_micro.fees import (
    CATEGORY_RATES,
    KALSHI_FEE_MULTIPLIER_DEFAULT,
    KALSHI_MAKER_FRACTION,
    KALSHI_MULTIPLIER_BASE,
    POLYMARKET_REBATE_FRACTION_DEFAULT,
    kalshi_fee,
    polymarket_fee,
    polymarket_rate_for_category,
)


# =========================================================================
# Kalshi parabolic (price-dependent) fee
# =========================================================================

@pytest.mark.parametrize(
    "price,expected_cents",
    [
        (0.50, 2),   # ceil(7 * 0.5 * 0.5) = ceil(1.75) = 2¢
        (0.20, 2),   # ceil(7 * 0.2 * 0.8) = ceil(1.12) = 2¢
        (0.10, 1),   # ceil(7 * 0.1 * 0.9) = ceil(0.63) = 1¢
        (0.05, 1),   # ceil(7 * 0.05 * 0.95) = ceil(0.3325) = 1¢
        (0.01, 1),   # ceil(7 * 0.01 * 0.99) = ceil(0.0693) = 1¢
        (0.95, 1),   # symmetric: ceil(7 * 0.95 * 0.05) = 1¢
        (0.99, 1),   # symmetric: ceil(7 * 0.99 * 0.01) = 1¢
    ],
)
def test_kalshi_taker_parabola_at_pricepoints(price, expected_cents):
    """Spec: ceil(7 * C * (1-C)) cents at multiplier=1, taker mode."""
    fee = kalshi_fee(price, size=1, execution_mode="taker")
    assert fee == pytest.approx(expected_cents / 100.0)


def test_kalshi_taker_at_boundaries():
    """C=0 and C=1 → parabola is zero, ceil(0)=0¢."""
    assert kalshi_fee(0.0, execution_mode="taker") == pytest.approx(0.0)
    assert kalshi_fee(1.0, execution_mode="taker") == pytest.approx(0.0)


def test_kalshi_taker_scales_linearly_with_size():
    """Per-contract fee × N contracts."""
    per_contract = kalshi_fee(0.50, size=1, execution_mode="taker")
    assert kalshi_fee(0.50, size=100, execution_mode="taker") == pytest.approx(100 * per_contract)


def test_kalshi_maker_at_50c_quadratic_with_maker_fees():
    """At 50¢, multiplier=1: raw=1.75¢, maker = ceil(0.25 * 1.75) = ceil(0.4375) = 1¢."""
    fee = kalshi_fee(0.50, execution_mode="maker", maker_fraction=KALSHI_MAKER_FRACTION)
    assert fee == pytest.approx(0.01)


def test_kalshi_maker_at_tail_drops_to_zero():
    """At 5¢: raw = 0.3325¢, 0.25*0.3325 = 0.0831¢, ceil = 1¢. Floor stays at 1¢."""
    fee = kalshi_fee(0.05, execution_mode="maker", maker_fraction=KALSHI_MAKER_FRACTION)
    assert fee == pytest.approx(0.01)


def test_kalshi_maker_with_zero_fraction_is_taker_only():
    """fee_type='quadratic' (no maker fees) → maker fee should be exactly $0."""
    fee = kalshi_fee(0.50, execution_mode="maker", maker_fraction=0.0)
    assert fee == 0.0


def test_kalshi_financial_multiplier_halves_body_fee():
    """multiplier=0.5 (financial indices): raw=0.875¢, ceil=1¢."""
    fee = kalshi_fee(0.50, multiplier=0.5)
    assert fee == pytest.approx(0.01)


def test_kalshi_rejects_out_of_range_price():
    with pytest.raises(ValueError):
        kalshi_fee(-0.1)
    with pytest.raises(ValueError):
        kalshi_fee(1.1)


# =========================================================================
# Polymarket category lookup
# =========================================================================

@pytest.mark.parametrize(
    "category,expected_rate",
    [
        ("crypto",       0.072),
        ("economics",    0.05),
        ("culture",      0.05),
        ("weather",      0.05),
        ("finance",      0.04),
        ("politics",     0.04),
        ("tech",         0.04),
        ("sports",       0.03),
        ("geopolitics",  0.00),
        ("world_events", 0.00),
    ],
)
def test_polymarket_category_rates_table(category, expected_rate):
    rate, key = polymarket_rate_for_category(category)
    assert rate == pytest.approx(expected_rate)


@pytest.mark.parametrize(
    "raw,expected_key",
    [
        ("Sports",            "sports"),
        ("sports_fees_v2",    "sports"),
        ("politics_fees",     "politics"),
        ("tech_fees",         "tech"),
        ("crypto_fees_v1",    "crypto"),
        ("WORLD-EVENTS",      "geopolitics"),
        ("elections",         "politics"),
        ("M&A",               "culture"),
        ("AI",                "tech"),
    ],
)
def test_polymarket_category_synonyms_resolve(raw, expected_key):
    _, key = polymarket_rate_for_category(raw)
    assert key == expected_key


def test_polymarket_unmapped_category_falls_back_to_max():
    rate, key = polymarket_rate_for_category("zzz_nonexistent_category")
    assert key == "_unmapped"
    assert rate == max(CATEGORY_RATES.values())


def test_polymarket_none_category_is_legacy_default():
    """Backward compat: callers with no category info get the OLD 2% flat."""
    rate, key = polymarket_rate_for_category(None)
    assert key == "_legacy_default"
    assert rate == pytest.approx(0.02)


# =========================================================================
# Polymarket fee application
# =========================================================================

def test_polymarket_taker_sports_at_50c():
    """0.03 × 0.50 × 1 = $0.015."""
    fee = polymarket_fee(0.50, category="sports", execution_mode="taker")
    assert fee == pytest.approx(0.015)


def test_polymarket_taker_politics_at_50c():
    """0.04 × 0.50 × 1 = $0.020."""
    fee = polymarket_fee(0.50, category="politics", execution_mode="taker")
    assert fee == pytest.approx(0.020)


def test_polymarket_taker_geopolitics_is_zero():
    """Fee-free umbrella: matches user spec for world-events markets."""
    assert polymarket_fee(0.50, category="geopolitics", execution_mode="taker") == 0.0
    assert polymarket_fee(0.50, category="world events", execution_mode="taker") == 0.0


def test_polymarket_taker_scales_with_notional():
    f1 = polymarket_fee(0.20, size=10, category="politics", execution_mode="taker")
    f2 = polymarket_fee(0.40, size=10, category="politics", execution_mode="taker")
    assert f1 == pytest.approx(0.04 * 0.20 * 10)
    assert f2 == pytest.approx(2 * f1)


def test_polymarket_taker_explicit_rate_overrides_category():
    """Pass `rate=` directly to bypass the lookup."""
    fee = polymarket_fee(0.50, rate=0.10, category="sports", execution_mode="taker")
    assert fee == pytest.approx(0.05)  # 0.10 × 0.50


def test_polymarket_maker_is_zero_by_default():
    """`takerOnly: True` model — makers pay nothing."""
    assert polymarket_fee(0.50, category="sports", execution_mode="maker") == 0.0


def test_polymarket_maker_with_rebate_is_negative():
    """Optional upside: makers receive rebate as a NEGATIVE fee."""
    fee = polymarket_fee(
        0.50, category="sports", execution_mode="maker",
        use_rebate=True, rebate_fraction=0.25,
    )
    expected = -0.25 * 0.03 * 0.50
    assert fee == pytest.approx(expected)
    assert fee < 0


def test_polymarket_rejects_out_of_range_price():
    with pytest.raises(ValueError):
        polymarket_fee(-0.1)
    with pytest.raises(ValueError):
        polymarket_fee(1.5)


# =========================================================================
# Sanity: the legacy 2% / $0.02 numerics still match at C=0.50
# =========================================================================

def test_kalshi_at_50c_matches_old_2c_constant():
    """The parabolic model at midprice converges to the historical flat 2¢."""
    assert kalshi_fee(0.50, multiplier=1.0) == pytest.approx(0.02)


def test_polymarket_default_no_category_matches_old_2pct():
    """Backward compat default: PM fee with no category = 2% × notional."""
    assert polymarket_fee(0.50, execution_mode="taker") == pytest.approx(0.01)  # 2% * 0.50
