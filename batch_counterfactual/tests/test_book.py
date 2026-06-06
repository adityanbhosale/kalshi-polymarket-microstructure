"""Unit tests for the book reconstruction layer."""

from decimal import Decimal

import pandas as pd
import pytest

import book
from book import (
    BookState,
    Panel,
    prob_to_ticks,
    ticks_to_prob,
    to_cents,
    to_prob,
)
from fees import Tier

HEADER = "utc_ts,market_id,venue,best_bid,best_ask,error\n"


def _write(path, rows: list[str]) -> str:
    path.write_text(HEADER + "".join(r if r.endswith("\n") else r + "\n" for r in rows))
    return str(path)


def _mkstate(venue, bid, ask, *, market="m", ts="2026-05-28T04:01:00Z") -> BookState:
    return BookState(
        venue=venue, market_id=market, ts=pd.Timestamp(ts),
        best_bid=to_prob(bid, venue), best_ask=to_prob(ask, venue),
        bid_sz=None, ask_sz=None, raw_best_bid=bid, raw_best_ask=ask,
        tick_size=book.venue_tick(venue),
    )


# --- normalization round-trip ---------------------------------------------

def test_cents_decimal_round_trip():
    assert to_prob(0.56, "kalshi") == Decimal("0.56")
    assert to_prob(0.285, "polymarket") == Decimal("0.285")
    # Kalshi on 1c grid -> 56 ticks; PM on 0.1c grid -> 285 ticks.
    assert prob_to_ticks(Decimal("0.56"), "kalshi") == 56
    assert prob_to_ticks(Decimal("0.285"), "polymarket") == 285
    assert to_cents(Decimal("0.56")) == Decimal("56.00")
    assert to_cents(Decimal("0.285")) == Decimal("28.500")
    for v, vals in (("kalshi", ["0.01", "0.30", "0.56", "0.99"]),
                    ("polymarket", ["0.001", "0.285", "0.567", "0.999"])):
        for s in vals:
            p = Decimal(s)
            assert ticks_to_prob(prob_to_ticks(p, v), v) == p


def test_no_views_are_derived_not_stored():
    s = _mkstate("kalshi", 0.30, 0.31)
    assert s.no_bid == Decimal("0.69")   # 1 - YES ask
    assert s.no_ask == Decimal("0.70")   # 1 - YES bid
    assert s.yes_mid == Decimal("0.305")


# --- at-or-before semantics + gap tolerance --------------------------------

def test_at_or_before_and_gap_tolerance(tmp_path):
    rows = []
    for t in ("04:01:00", "04:01:30"):          # two adjacent cycles
        rows.append(f"2026-05-28T{t}+00:00,m,kalshi_yes,0.30,0.31,")
        rows.append(f"2026-05-28T{t}+00:00,m,polymarket_yes,0.27,0.285,")
    for t in ("04:06:00",):                       # then a ~4.5 min hole
        rows.append(f"2026-05-28T{t}+00:00,m,kalshi_yes,0.40,0.41,")
        rows.append(f"2026-05-28T{t}+00:00,m,polymarket_yes,0.38,0.39,")
    p = Panel(_write(tmp_path / "f.csv", rows), outages=[])

    # query between the two adjacent cycles -> at-or-before returns the earlier
    s = p.book_state("kalshi", "m", "2026-05-28T04:01:45Z")
    assert s is not None and s.ts == pd.Timestamp("2026-05-28T04:01:30Z")
    assert s.age_s == pytest.approx(15.0)

    # query deep in the hole -> last snapshot (04:01:30) is >90s stale -> None
    assert p.book_state("kalshi", "m", "2026-05-28T04:04:00Z") is None
    # query exactly at the post-hole cycle -> resolves it
    s2 = p.book_state("kalshi", "m", "2026-05-28T04:06:00Z")
    assert s2 is not None and s2.ts == pd.Timestamp("2026-05-28T04:06:00Z")
    # query before any data -> None
    assert p.book_state("kalshi", "m", "2026-05-28T03:00:00Z") is None


def test_none_inside_outage(tmp_path):
    # A fresh snapshot exists at 09:30 (age 60s at query) but it's inside the
    # outage window -> must return None regardless of staleness tolerance.
    rows = [
        "2026-06-02T09:30:00+00:00,m,kalshi_yes,0.30,0.31,",
        "2026-06-02T15:00:00+00:00,m,kalshi_yes,0.40,0.41,",
    ]
    outage = (pd.Timestamp("2026-06-02T09:00:00Z"), pd.Timestamp("2026-06-02T10:00:00Z"))
    p = Panel(_write(tmp_path / "f.csv", rows), outages=[outage])
    assert p.book_state("kalshi", "m", "2026-06-02T09:31:00Z") is None
    # outside the outage, a fresh snapshot resolves normally
    s = p.book_state("kalshi", "m", "2026-06-02T15:00:30Z")
    assert s is not None and s.ts == pd.Timestamp("2026-06-02T15:00:00Z")


# --- R9: multi-line quoted error fields ------------------------------------

def test_r9_multiline_row(tmp_path):
    # The polymarket row's error field carries an embedded newline (quoted), so
    # one logical row spans two physical lines. A real CSV reader must keep it as
    # ONE row; book_state must not be fooled and must return None for that null
    # book while the valid Kalshi row resolves.
    raw = (
        HEADER
        + "2026-05-28T04:01:00+00:00,m,kalshi_yes,0.30,0.31,\n"
        + '2026-05-28T04:01:00+00:00,m,polymarket_yes,,,"503 Service Unavailable\n'
        + 'For more information check: https://example.com/err"\n'
    )
    fp = tmp_path / "r9.csv"
    fp.write_text(raw)
    p = Panel(str(fp), outages=[])

    assert len(p._load()) == 2          # two LOGICAL rows, not three physical lines
    k = p.book_state("kalshi", "m", "2026-05-28T04:01:00Z")
    assert k is not None and k.best_bid == Decimal("0.30")
    # null/one-sided PM book is not a fabricated state
    assert p.book_state("polymarket", "m", "2026-05-28T04:01:00Z") is None
    assert p.paired_state("m", "2026-05-28T04:01:00Z") is None


# --- paired lookup with a missing leg --------------------------------------

def test_paired_missing_leg(tmp_path):
    rows = [
        "2026-05-28T04:01:00+00:00,m,kalshi_yes,0.30,0.31,",
        # no polymarket_yes row for m
        "2026-05-28T04:01:00+00:00,other,polymarket_yes,0.27,0.285,",
    ]
    p = Panel(_write(tmp_path / "f.csv", rows), outages=[])
    assert p.book_state("kalshi", "m", "2026-05-28T04:01:00Z") is not None
    assert p.paired_state("m", "2026-05-28T04:01:00Z") is None


# --- cross helpers (gross + fee-adjusted) ----------------------------------

def test_is_crossed_gross_and_fee_adjusted():
    # k_bid 0.30 / ask 0.31 ; p_bid 0.27 / ask 0.285
    # gross dir A: k_bid - p_ask = 0.015 -> +1.5c crossed
    pair = (_mkstate("kalshi", 0.30, 0.31), _mkstate("polymarket", 0.27, 0.285))
    assert book.is_crossed(pair) is True                       # gross
    assert book.cross_size(pair) == Decimal("1.500")
    assert book.is_crossed(pair, Tier.ZERO) is True

    # retail fees (Kalshi 2c sell + PM 0.04 taker) flip it negative
    assert book.is_crossed(pair, Tier.RETAIL, pm_category="politics") is False
    assert book.cross_size(pair, Tier.RETAIL, pm_category="politics") < 0

    # an uncrossed book is False gross
    flat = (_mkstate("kalshi", 0.30, 0.32), _mkstate("polymarket", 0.30, 0.32))
    assert book.is_crossed(flat) is False
