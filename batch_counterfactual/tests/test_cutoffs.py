"""Unit tests for cutoffs.py — determinism, outage skips."""

import pandas as pd

from book import OUTAGE_10H, Panel
from cutoffs import SkippedAuction, ValidCutoff, fixed_grid, randomized, skipped_summary


def _mini_panel(tmp_path) -> Panel:
    rows = [
        "utc_ts,market_id,venue,best_bid,best_ask,error\n",
        "2026-06-01T10:00:00+00:00,m,kalshi_yes,0.30,0.31,\n",
        "2026-06-01T10:00:00+00:00,m,polymarket_yes,0.29,0.30,\n",
        "2026-06-02T15:00:00+00:00,m,kalshi_yes,0.40,0.41,\n",
        "2026-06-02T15:00:00+00:00,m,polymarket_yes,0.39,0.40,\n",
    ]
    fp = tmp_path / "panel.csv"
    fp.write_text("".join(rows))
    return Panel(fp, outages=[OUTAGE_10H])


def test_randomized_deterministic_under_seed(tmp_path):
    p = _mini_panel(tmp_path)
    a = randomized("2026-06-01T10:00:00Z", "2026-06-02T16:00:00Z", 3600, seed=42,
                   pair_id="m", panel=p)
    b = randomized("2026-06-01T10:00:00Z", "2026-06-02T16:00:00Z", 3600, seed=42,
                   pair_id="m", panel=p)
    assert [type(e).__name__ + str(getattr(e, "ts", "")) for e in a] == \
           [type(e).__name__ + str(getattr(e, "ts", "")) for e in b]


def test_skipped_auction_in_outage(tmp_path):
    p = _mini_panel(tmp_path)
    # Midpoint of the 10.1h outage
    t_out = pd.Timestamp("2026-06-02T09:00:00Z")
    events = fixed_grid(t_out, t_out, 30, pair_id="m", panel=p)
    assert len(events) == 1
    assert isinstance(events[0], SkippedAuction)
    assert events[0].reason == "outage"


def test_valid_cutoff_outside_outage(tmp_path):
    p = _mini_panel(tmp_path)
    events = fixed_grid("2026-06-01T10:00:00Z", "2026-06-01T10:00:00Z", 30,
                        pair_id="m", panel=p)
    assert len(events) == 1
    assert isinstance(events[0], ValidCutoff)


def test_skipped_summary_counts(tmp_path):
    p = _mini_panel(tmp_path)
    events = fixed_grid("2026-06-02T08:00:00Z", "2026-06-02T10:00:00Z", 1800,
                        pair_id="m", panel=p)
    counts = skipped_summary(events)
    assert counts.get("outage", 0) >= 1
