"""Table-driven fee tests with hand-computed expected values at C=0.05/0.50/0.95.

Hand computation (size=1, multiplier=1, PM category=politics rate=0.04,
PM rebate_fraction=0.22, institutional 0.30% taker / 0.20% maker):

  Kalshi parabolic taker = ceil(7*C*(1-C)) cents / 100:
    C=0.05 -> ceil(0.3325)=1c -> 0.01;  C=0.50 -> ceil(1.75)=2c -> 0.02;
    C=0.95 -> ceil(0.3325)=1c -> 0.01.
  PM retail taker = 0.04*C:               0.05->0.002, 0.50->0.02, 0.95->0.038
  PM rebate (maker) = -0.22*0.04*C:       0.05->-0.00044, 0.50->-0.0044, 0.95->-0.00836
  Institutional taker = 0.003*C:          0.05->0.00015, 0.50->0.0015, 0.95->0.00285
  Institutional maker = 0.002*C:          0.05->0.0001, 0.50->0.001, 0.95->0.0019
  Zero = 0 everywhere.
"""

import math

import pytest

from fees import Tier, leg_fee

CASES = [
    # (venue, tier, role, C, expected_dollars)
    ("kalshi", Tier.RETAIL, "taker", 0.05, 0.01),
    ("kalshi", Tier.RETAIL, "taker", 0.50, 0.02),
    ("kalshi", Tier.RETAIL, "taker", 0.95, 0.01),
    ("polymarket", Tier.RETAIL, "taker", 0.05, 0.002),
    ("polymarket", Tier.RETAIL, "taker", 0.50, 0.02),
    ("polymarket", Tier.RETAIL, "taker", 0.95, 0.038),
    # RETAIL_PM_REBATE: Kalshi unchanged (taker parabolic); PM earns rebate (neg).
    ("kalshi", Tier.RETAIL_PM_REBATE, "taker", 0.50, 0.02),
    ("polymarket", Tier.RETAIL_PM_REBATE, "maker", 0.05, -0.00044),
    ("polymarket", Tier.RETAIL_PM_REBATE, "maker", 0.50, -0.0044),
    ("polymarket", Tier.RETAIL_PM_REBATE, "maker", 0.95, -0.00836),
    # INSTITUTIONAL counterfactual, identical on both venues.
    ("kalshi", Tier.INSTITUTIONAL, "taker", 0.05, 0.00015),
    ("kalshi", Tier.INSTITUTIONAL, "taker", 0.50, 0.0015),
    ("kalshi", Tier.INSTITUTIONAL, "taker", 0.95, 0.00285),
    ("polymarket", Tier.INSTITUTIONAL, "taker", 0.50, 0.0015),
    ("kalshi", Tier.INSTITUTIONAL, "maker", 0.05, 0.0001),
    ("polymarket", Tier.INSTITUTIONAL, "maker", 0.50, 0.001),
    ("polymarket", Tier.INSTITUTIONAL, "maker", 0.95, 0.0019),
    # ZERO everywhere.
    ("kalshi", Tier.ZERO, "taker", 0.05, 0.0),
    ("polymarket", Tier.ZERO, "taker", 0.50, 0.0),
    ("kalshi", Tier.ZERO, "maker", 0.95, 0.0),
]


@pytest.mark.parametrize("venue,tier,role,price,expected", CASES)
def test_leg_fee_table(venue, tier, role, price, expected):
    got = leg_fee(venue, price, 1.0, tier=tier, role=role, category="politics")
    assert math.isclose(got, expected, rel_tol=0, abs_tol=1e-9), (
        f"{venue}/{tier}/{role}@C={price}: got {got}, expected {expected}")


def test_size_scales_linearly():
    one = leg_fee("polymarket", 0.50, 1.0, tier=Tier.RETAIL, category="politics")
    ten = leg_fee("polymarket", 0.50, 10.0, tier=Tier.RETAIL, category="politics")
    assert math.isclose(ten, 10 * one, abs_tol=1e-12)


def test_rebate_is_negative_and_zero_is_zero():
    assert leg_fee("polymarket", 0.5, tier=Tier.RETAIL_PM_REBATE, role="maker",
                   category="politics") < 0
    assert leg_fee("kalshi", 0.5, tier=Tier.ZERO) == 0.0
    assert leg_fee("polymarket", 0.5, tier=Tier.ZERO) == 0.0


def test_pm_rate_overrides_category():
    # explicit rate beats category lookup
    got = leg_fee("polymarket", 0.5, tier=Tier.RETAIL, pm_rate=0.03)
    assert math.isclose(got, 0.03 * 0.5, abs_tol=1e-12)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        leg_fee("bogus", 0.5, tier=Tier.RETAIL)
    with pytest.raises(ValueError):
        leg_fee("kalshi", 1.5, tier=Tier.RETAIL)
