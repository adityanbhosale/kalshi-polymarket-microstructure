"""Unit tests for src/pm_micro/fills.py (EXP-12a fill-realism primitives)."""

import math

import numpy as np
import pytest

from pm_micro.fills import (
    LogisticModel,
    book_imbalance,
    fill_label,
    fit_logistic,
    markout_cents,
    posting_distance_cents,
    rolling_volatility_cents,
)


# ---------------------------------------------------------------------------
# posting_distance_cents
# ---------------------------------------------------------------------------

def test_posting_distance_bid_passive_positive():
    # bid posted below mid is passive -> positive distance
    assert posting_distance_cents(0.50, 0.48, "buy") == pytest.approx(2.0)


def test_posting_distance_ask_passive_positive():
    # ask posted above mid is passive -> positive distance
    assert posting_distance_cents(0.50, 0.52, "sell") == pytest.approx(2.0)


def test_posting_distance_through_mid_negative():
    # bid posted above mid (aggressive / crossing) -> negative distance
    assert posting_distance_cents(0.50, 0.53, "buy") == pytest.approx(-3.0)


def test_posting_distance_bad_side():
    with pytest.raises(ValueError):
        posting_distance_cents(0.5, 0.5, "hold")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# book_imbalance
# ---------------------------------------------------------------------------

def test_book_imbalance_symmetric():
    assert book_imbalance(100, 100) == pytest.approx(0.0)


def test_book_imbalance_bid_heavy():
    assert book_imbalance(300, 100) == pytest.approx(0.5)


def test_book_imbalance_ask_heavy():
    assert book_imbalance(0, 100) == pytest.approx(-1.0)


def test_book_imbalance_empty():
    assert book_imbalance(0, 0) == 0.0


# ---------------------------------------------------------------------------
# rolling_volatility_cents
# ---------------------------------------------------------------------------

def test_rolling_vol_flat_is_zero():
    assert rolling_volatility_cents([0.5, 0.5, 0.5]) == pytest.approx(0.0)


def test_rolling_vol_positive():
    v = rolling_volatility_cents([0.50, 0.52, 0.48, 0.50])
    assert v > 0.0
    # population stddev of [50,52,48,50] cents = sqrt(2.0) ~ 1.414
    assert v == pytest.approx(np.std([50.0, 52.0, 48.0, 50.0]), rel=1e-6)


def test_rolling_vol_short_window():
    assert rolling_volatility_cents([0.5]) == 0.0
    assert rolling_volatility_cents([]) == 0.0


def test_rolling_vol_ignores_nan():
    v = rolling_volatility_cents([0.5, float("nan"), 0.5])
    assert v == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# fill_label (price-through proxy)
# ---------------------------------------------------------------------------

def test_fill_label_bid_fills_when_price_drops_to_level():
    # resting bid at 0.40; best bid later reaches 0.39 (<= 0.40) -> fill
    assert fill_label([0.45, 0.42, 0.39], 0.40, "buy") is True


def test_fill_label_bid_no_fill_when_price_stays_above():
    assert fill_label([0.45, 0.44, 0.43], 0.40, "buy") is False


def test_fill_label_ask_fills_when_price_rises_to_level():
    assert fill_label([0.55, 0.58, 0.61], 0.60, "sell") is True


def test_fill_label_ask_no_fill_when_price_stays_below():
    assert fill_label([0.55, 0.56, 0.57], 0.60, "sell") is False


def test_fill_label_empty_and_nan_window():
    assert fill_label([], 0.40, "buy") is False
    assert fill_label([float("nan"), float("nan")], 0.40, "buy") is False


def test_fill_label_at_touch_boundary():
    # exact equality counts as a fill (tolerance)
    assert fill_label([0.40], 0.40, "buy") is True
    assert fill_label([0.60], 0.60, "sell") is True


# ---------------------------------------------------------------------------
# markout_cents (sign convention)
# ---------------------------------------------------------------------------

def test_markout_buy_favorable_when_mid_rises():
    # bought at fill mid 0.40, mid rises to 0.43 -> +3c favorable
    assert markout_cents(0.40, 0.43, "buy") == pytest.approx(3.0)


def test_markout_buy_adverse_when_mid_falls():
    # bought, mid falls -> negative (adverse selection)
    assert markout_cents(0.40, 0.37, "buy") == pytest.approx(-3.0)


def test_markout_sell_favorable_when_mid_falls():
    assert markout_cents(0.60, 0.57, "sell") == pytest.approx(3.0)


def test_markout_sell_adverse_when_mid_rises():
    assert markout_cents(0.60, 0.63, "sell") == pytest.approx(-3.0)


def test_markout_nan_inputs():
    assert math.isnan(markout_cents(float("nan"), 0.5, "buy"))
    assert math.isnan(markout_cents(0.5, float("nan"), "sell"))


# ---------------------------------------------------------------------------
# fit_logistic
# ---------------------------------------------------------------------------

def test_logistic_recovers_separating_direction():
    # 1-D: larger x -> more likely fill. Fit should give positive coef and
    # predictions monotone in x.
    rng = np.random.default_rng(0)
    x = np.linspace(-3, 3, 400)
    p = 1.0 / (1.0 + np.exp(-2.0 * x))
    y = (rng.random(400) < p).astype(float)
    model = fit_logistic(x.reshape(-1, 1), y, ["x"], n_iter=3000)
    assert model.coef[0] > 0.0
    lo = model.predict_proba(np.array([[-3.0]]))[0]
    hi = model.predict_proba(np.array([[3.0]]))[0]
    assert hi > lo
    assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0


def test_logistic_predicts_base_rate_with_uninformative_feature():
    # Feature carries no signal; intercept should encode the ~30% base rate.
    rng = np.random.default_rng(1)
    n = 600
    x = rng.normal(size=n)
    y = (rng.random(n) < 0.30).astype(float)
    model = fit_logistic(x.reshape(-1, 1), y, ["noise"], n_iter=3000)
    mean_pred = float(model.predict_proba(x.reshape(-1, 1)).mean())
    assert mean_pred == pytest.approx(0.30, abs=0.06)
    assert abs(model.coef[0]) < 0.5  # weak/no dependence on noise


def test_logistic_zero_variance_column_is_safe():
    # A constant column must not blow up (std floored to 1).
    n = 200
    x_const = np.ones(n)
    x_sig = np.linspace(-2, 2, n)
    y = (x_sig > 0).astype(float)
    X = np.column_stack([x_const, x_sig])
    model = fit_logistic(X, y, ["const", "sig"], n_iter=2000)
    assert np.isfinite(model.coef).all()
    assert np.isfinite(model.predict_proba(X)).all()


def test_logistic_proba_in_unit_interval():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(300, 3))
    y = (X[:, 0] + rng.normal(scale=0.5, size=300) > 0).astype(float)
    model = fit_logistic(X, y, ["a", "b", "c"], n_iter=1500)
    p = model.predict_proba(X)
    assert p.min() >= 0.0 and p.max() <= 1.0
    assert isinstance(model, LogisticModel)


def test_logistic_input_validation():
    with pytest.raises(ValueError):
        fit_logistic(np.zeros((5, 2)), np.zeros(4), ["a", "b"])
    with pytest.raises(ValueError):
        fit_logistic(np.zeros((5, 2)), np.zeros(5), ["only_one"])
