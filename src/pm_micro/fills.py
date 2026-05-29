"""Fill-realism primitives: probabilistic fill modeling + post-fill markout.

EXP-12a (2026-05-28). The EXP-3a/3b/3c LP-edge dollar figures rest on a
load-bearing "exclusive-fill at displayed depth" assumption: that a
posted passive order fills in full, instantly, with no adverse price
movement afterward. This module replaces that with honest, observable
primitives calibrated on the E.1 daemon's 30s-cadence snapshot history.

Two things are modeled:

1. FILL PROBABILITY. For a hypothetical resting order at price ``P`` on a
   given side, posted at snapshot ``t``, did the market trade through
   ``P`` within a horizon of ``H`` snapshots? We cannot observe trades
   directly at 30s cadence, so we use a price-through proxy (see
   ``fill_label``) and fit a logistic model on engineered features
   (distance from mid, queue depth ahead, book imbalance, recent
   volatility, time-to-catalyst).

   MODEL ASSUMPTION (documented, not hidden): the price-through proxy
   says a resting BID at ``P`` "would have filled" if the best bid
   reaches ``<= P`` at some later snapshot in the horizon. Intra-snapshot
   queue depletion is unobservable; we assume the queue ahead clears
   proportionally to the level being touched. This OVER-counts fills for
   orders posted exactly at the touch (you'd be behind the queue) and is
   most reliable for orders posted at a strictly passive distance below
   (bid) / above (ask) the touch. We therefore fit over a distance grid
   and report fill probability *as a function of posting distance*, which
   is the honest object.

2. MARKOUT (adverse selection). Given a hypothetical fill at snapshot
   ``t``, where did the venue mid go at ``t+H``? Signed so POSITIVE =
   favorable to the resting trader (price moved in their favor after the
   fill) and NEGATIVE = adverse (informed flow lifted them). A
   systematically negative markout means the "edge" is really
   adverse-selection-paid spread, not edge.

All public functions are pure and unit-tested in ``tests/test_fills.py``.
No timezone handling here (callers pass numeric arrays); the calling
script keeps everything tz-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np

Side = Literal["buy", "sell"]


# =========================================================================
# Feature primitives
# =========================================================================

def posting_distance_cents(mid: float, posted_price: float, side: Side) -> float:
    """Signed posting distance in cents; POSITIVE = passive (away from mid).

    A resting BID (``side="buy"``) posted below the mid is passive:
    distance = (mid - posted_price) * 100. A resting ASK (``side="sell"``)
    posted above the mid is passive: distance = (posted_price - mid) * 100.
    Negative distance means the order is posted through the mid (aggressive
    / would cross), which on a crossed book is exactly the LP's situation.
    """
    if side == "buy":
        return (mid - posted_price) * 100.0
    if side == "sell":
        return (posted_price - mid) * 100.0
    raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")


def book_imbalance(bid_size: float, ask_size: float) -> float:
    """Order-book imbalance in [-1, 1]: (bid - ask) / (bid + ask).

    Positive = more size resting on the bid (buy pressure). Returns 0.0
    when both sides are empty.
    """
    total = bid_size + ask_size
    if total <= 0:
        return 0.0
    return (bid_size - ask_size) / total


def rolling_volatility_cents(mids: Sequence[float]) -> float:
    """Population stddev of a mid window, in cents. NaNs ignored.

    Returns 0.0 for a window of length < 2 or all-NaN.
    """
    arr = np.asarray([m for m in mids if m == m], dtype=float)  # drop NaN
    if arr.size < 2:
        return 0.0
    return float(np.std(arr) * 100.0)


# =========================================================================
# Fill-event reconstruction (price-through proxy)
# =========================================================================

def fill_label(
    future_best_prices: Sequence[float],
    posted_price: float,
    side: Side,
) -> bool:
    """Did a resting order at ``posted_price`` fill within the horizon?

    Price-through proxy (see module docstring). ``future_best_prices`` is
    the sequence of best-bid (for a resting BID) or best-ask (for a
    resting ASK) over the horizon snapshots strictly after posting.

      * resting BID at P fills if any future best_bid <= P
        (the market traded down to our level).
      * resting ASK at P fills if any future best_ask >= P
        (the market traded up to our level).

    NaNs in the future window are skipped. Empty / all-NaN window -> False.
    """
    vals = [p for p in future_best_prices if p == p]
    if not vals:
        return False
    if side == "buy":
        return any(p <= posted_price + 1e-9 for p in vals)
    if side == "sell":
        return any(p >= posted_price - 1e-9 for p in vals)
    raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")


def markout_cents(
    mid_at_fill: float,
    mid_future: float,
    side: Side,
) -> float:
    """Signed post-fill markout in cents; POSITIVE = favorable to rester.

    A resting BID that fills means we BOUGHT at the posted price; it is
    favorable if the mid subsequently rises:
        markout = (mid_future - mid_at_fill) * 100.
    A resting ASK that fills means we SOLD; favorable if the mid falls:
        markout = (mid_at_fill - mid_future) * 100.
    NaN inputs -> NaN.
    """
    if mid_at_fill != mid_at_fill or mid_future != mid_future:
        return float("nan")
    if side == "buy":
        return (mid_future - mid_at_fill) * 100.0
    if side == "sell":
        return (mid_at_fill - mid_future) * 100.0
    raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")


# =========================================================================
# Minimal logistic regression (numpy, deterministic, no sklearn dep)
# =========================================================================

@dataclass
class LogisticModel:
    """A fitted standardized logistic regression.

    ``predict_proba`` accepts raw (un-standardized) feature rows and
    applies the stored standardization internally. Coefficients are stored
    in standardized space; ``raw_importance`` exposes |coef| for ranking.
    """

    feature_names: list[str]
    mean: np.ndarray
    std: np.ndarray
    coef: np.ndarray          # standardized-space weights (len = n_features)
    intercept: float
    n_train: int
    n_pos: int

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        Xs = (X - self.mean) / self.std
        z = Xs @ self.coef + self.intercept
        return _sigmoid(z)

    def importance(self) -> dict[str, float]:
        return {n: float(abs(c)) for n, c in zip(self.feature_names, self.coef)}


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35.0, 35.0)))


def fit_logistic(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    *,
    l2: float = 1.0,
    lr: float = 0.5,
    n_iter: int = 4000,
    seed: int = 0,
) -> LogisticModel:
    """Fit logistic regression by deterministic full-batch gradient descent.

    Features are standardized (zero mean, unit std) before fitting; columns
    with zero variance are given std=1 so they contribute only via the
    intercept. L2 penalizes the standardized weights (not the intercept).
    Deterministic given inputs (no stochasticity; ``seed`` reserved).
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if X.ndim != 2:
        raise ValueError("X must be 2-D")
    if X.shape[0] != y.shape[0]:
        raise ValueError("X and y row count mismatch")
    if X.shape[1] != len(feature_names):
        raise ValueError("feature_names length mismatch")

    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std = np.where(std < 1e-12, 1.0, std)
    Xs = (X - mean) / std

    n, d = Xs.shape
    w = np.zeros(d)
    b = 0.0
    # Initialize intercept to the base rate's logit for faster convergence.
    p_base = float(np.clip(y.mean(), 1e-6, 1 - 1e-6))
    b = float(np.log(p_base / (1 - p_base)))

    for _ in range(n_iter):
        z = Xs @ w + b
        p = _sigmoid(z)
        err = p - y
        grad_w = (Xs.T @ err) / n + (l2 / n) * w
        grad_b = float(err.mean())
        w -= lr * grad_w
        b -= lr * grad_b

    return LogisticModel(
        feature_names=list(feature_names),
        mean=mean, std=std, coef=w, intercept=b,
        n_train=int(n), n_pos=int(y.sum()),
    )
