"""Auction cutoff generators for the batch-auction counterfactual (Phase 2).

Produces deterministic, logged cutoff schedules for counterfactual auction runs.
Each candidate timestamp is validated against ``book.Panel`` gap/outage semantics:
when ``paired_state`` (or ``book_state``) returns None the generator emits a
``SkippedAuction`` record — never a silent skip.

Grid intervals ``T`` are parameterized (seconds); common panel values are
30s / 60s / 5min / 15min / 60min. Sub-second grids are reserved for the
Polymarket-only WS case study — pass ``T`` explicitly, do not hardcode.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterator, Literal

import pandas as pd

from book import Panel

SkipReason = Literal["outage", "stale_gap", "no_data"]


@dataclass(frozen=True)
class SkippedAuction:
    """A cutoff where book reconstruction failed — logged, not silently dropped."""
    ts: pd.Timestamp
    reason: SkipReason
    detail: str


@dataclass(frozen=True)
class ValidCutoff:
    ts: pd.Timestamp


CutoffEvent = ValidCutoff | SkippedAuction


def _to_ts(t) -> pd.Timestamp:
    ts = pd.Timestamp(t)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts


def _classify_skip(panel: Panel, pair_id: str, t: pd.Timestamp) -> SkippedAuction | None:
    """Return a SkippedAuction if ``pair_id`` is unavailable at ``t``, else None."""
    if panel._in_outage(t):
        return SkippedAuction(t, "outage", "timestamp inside known outage window")
    k = panel.book_state("kalshi", pair_id, t)
    if k is None:
        # Distinguish stale gap vs no data.
        leg = panel._leg("kalshi", pair_id)
        if leg.empty:
            return SkippedAuction(t, "no_data", "no kalshi rows for market")
        pos = int(leg["ts"].searchsorted(t, side="right")) - 1
        if pos < 0:
            return SkippedAuction(t, "no_data", "before first snapshot")
        age = (t - leg.iloc[pos]["ts"]).total_seconds()
        if age > panel.gap_tolerance_s:
            return SkippedAuction(t, "stale_gap", f"last snapshot {age:.0f}s stale")
        return SkippedAuction(t, "no_data", "kalshi leg unavailable")
    p = panel.book_state("polymarket", pair_id, t)
    if p is None:
        return SkippedAuction(t, "stale_gap", "polymarket leg unavailable or stale")
    return None


def _validate(
    panel: Panel | None,
    pair_id: str | None,
    t: pd.Timestamp,
) -> CutoffEvent:
    if panel is None or pair_id is None:
        return ValidCutoff(t)
    skip = _classify_skip(panel, pair_id, t)
    return skip if skip is not None else ValidCutoff(t)


def fixed_grid(
    start,
    end,
    T: float,
    *,
    pair_id: str | None = None,
    panel: Panel | None = None,
) -> list[CutoffEvent]:
    """Evenly spaced cutoffs every ``T`` seconds from ``start`` to ``end``."""
    lo = _to_ts(start)
    hi = _to_ts(end)
    step = timedelta(seconds=float(T))
    out: list[CutoffEvent] = []
    t = lo
    while t <= hi:
        out.append(_validate(panel, pair_id, t))
        t += step
    return out


def randomized(
    start,
    end,
    T: float,
    seed: int,
    *,
    pair_id: str | None = None,
    panel: Panel | None = None,
) -> list[CutoffEvent]:
    """Cutoffs with inter-arrival gaps ~ Uniform(0.5*T, 1.5*T); seeded, reproducible."""
    lo = _to_ts(start)
    hi = _to_ts(end)
    rng = random.Random(seed)
    out: list[CutoffEvent] = []
    t = lo
    while t <= hi:
        out.append(_validate(panel, pair_id, t))
        gap_s = rng.uniform(0.5 * T, 1.5 * T)
        t += timedelta(seconds=gap_s)
    return out


def iter_valid(events: list[CutoffEvent]) -> Iterator[pd.Timestamp]:
    """Yield only non-skipped cutoff timestamps."""
    for ev in events:
        if isinstance(ev, ValidCutoff):
            yield ev.ts


def skipped_summary(events: list[CutoffEvent]) -> dict[str, int]:
    """Count skips by reason (for logging)."""
    counts: dict[str, int] = {}
    for ev in events:
        if isinstance(ev, SkippedAuction):
            counts[ev.reason] = counts.get(ev.reason, 0) + 1
    return counts
