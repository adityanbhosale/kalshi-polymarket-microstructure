"""Book reconstruction layer for the batch-auction counterfactual study (Phase 1).

Turns the FROZEN 30s REST panel (`data/processed/timeofday_poll.csv`, pinned at
`FROZEN_MANIFEST.json`'s cutoff) into normalized, gap-aware cross-venue book
states. No auction logic, no gz ladder extraction — top-of-book from the panel
only. See `batch_counterfactual/DATA_AUDIT.md` for the conventions this honors:

  * Units (Q8): both venues stored as dollars in [0,1]; Kalshi tick $0.01,
    Polymarket tick $0.001. We normalize prices to `Decimal` probability in
    [0,1], preserving the raw stored value and the venue tick as attributes.
  * YES-side convention throughout; NO views are DERIVED (1 - YES), never stored.
  * R9 logical-row parsing: the panel has rows whose error field carries embedded
    newlines, so one logical row spans several physical lines — we parse with
    pandas' CSV reader (R9-safe), never line counting.
  * Gaps (Q2): 209 holes > 5 min incl. a 10.1h outage (2026-06-02). `book_state`
    returns None (never a stale fabrication) when the latest snapshot at-or-before
    `t` is older than `gap_tolerance_s`, or when `t` falls inside a known outage.

Sizes (`bid_sz`/`ask_sz`) are part of the BookState schema but are NOT populated
from the 30s panel (which stores top-of-book PRICES + two depth scalars only,
per audit Q5); they remain None until per-episode gz ladder extraction (later
phase). All price-based helpers work without them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL_CSV = ROOT / "data" / "processed" / "timeofday_poll.csv"

# Frozen replay horizon (FROZEN_MANIFEST.json): only rows strictly before this.
FROZEN_CUTOFF = pd.Timestamp("2026-06-06T04:00:00Z")

# Default staleness tolerance: a snapshot older than this (relative to the query
# time) is treated as a gap -> None. 90s = 3x the nominal 30s cadence.
DEFAULT_GAP_TOLERANCE_S = 90.0

# Known outage windows from the audit's gap inventory (DATA_AUDIT.md Q2). A query
# time strictly inside one returns None regardless of tolerance. The 10.1h outage
# is the decision-#4 blackout excluded from all time-in-state denominators; the
# other large holes (77-82 min) are caught by the staleness check generically.
OUTAGE_10H = (
    pd.Timestamp("2026-06-02T03:53:31.857383Z"),
    pd.Timestamp("2026-06-02T14:01:37.635796Z"),
)
DEFAULT_OUTAGES: list[tuple[pd.Timestamp, pd.Timestamp]] = [OUTAGE_10H]

KALSHI_TICK = Decimal("0.01")
POLYMARKET_TICK = Decimal("0.001")
ONE = Decimal("1")
HUNDRED = Decimal("100")


# =========================================================================
# Normalization helpers (cents/decimal probability round-trip)
# =========================================================================

def venue_tick(venue: str) -> Decimal:
    v = venue.lower()
    if v == "kalshi":
        return KALSHI_TICK
    if v == "polymarket":
        return POLYMARKET_TICK
    raise ValueError(f"unknown venue: {venue}")


def to_prob(value, venue: str) -> Decimal:
    """Stored dollar value in [0,1] -> Decimal probability quantized to venue tick."""
    d = Decimal(str(value)).quantize(venue_tick(venue), rounding=ROUND_HALF_UP)
    if not (Decimal(0) <= d <= ONE):
        raise ValueError(f"price out of [0,1]: {value} ({venue})")
    return d


def prob_to_ticks(prob: Decimal, venue: str) -> int:
    """Probability -> integer number of venue ticks (Kalshi cents, PM milli-dollars)."""
    return int((Decimal(prob) / venue_tick(venue)).to_integral_value(ROUND_HALF_UP))


def ticks_to_prob(ticks: int, venue: str) -> Decimal:
    """Integer venue ticks -> Decimal probability (inverse of `prob_to_ticks`)."""
    tick = venue_tick(venue)
    return (Decimal(int(ticks)) * tick).quantize(tick)


def to_cents(prob: Decimal | None) -> Decimal | None:
    """Repo convention: express prices/edges in cents = probability * 100."""
    return None if prob is None else (Decimal(prob) * HUNDRED)


# =========================================================================
# BookState
# =========================================================================

@dataclass(frozen=True)
class BookState:
    """Normalized YES-side top-of-book for one venue at one instant.

    Prices are Decimal probability in [0,1]. NO views are derived, never stored.
    `bid_sz`/`ask_sz` are None when sourced from the 30s panel (gz-only).
    """
    venue: str                      # "kalshi" | "polymarket"
    market_id: str
    ts: pd.Timestamp                # the snapshot's own utc_ts (tz-aware UTC)
    best_bid: Decimal | None        # YES bid, probability [0,1]
    best_ask: Decimal | None        # YES ask, probability [0,1]
    bid_sz: Decimal | None          # top-of-book bid size (None from 30s panel)
    ask_sz: Decimal | None          # top-of-book ask size (None from 30s panel)
    raw_best_bid: float | None      # value as stored in the panel (dollars)
    raw_best_ask: float | None
    tick_size: Decimal              # venue tick ($0.01 Kalshi / $0.001 PM)
    query_ts: pd.Timestamp | None = None   # the requested t (for staleness/debug)
    age_s: float | None = None      # seconds between query_ts and ts
    source: str = "panel_top_of_book"

    # --- derived NO views (complementarity NO = 1 - YES) ---
    @property
    def no_bid(self) -> Decimal | None:
        return None if self.best_ask is None else (ONE - self.best_ask)

    @property
    def no_ask(self) -> Decimal | None:
        return None if self.best_bid is None else (ONE - self.best_bid)

    @property
    def yes_mid(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    @property
    def bid_cents(self) -> Decimal | None:
        return to_cents(self.best_bid)

    @property
    def ask_cents(self) -> Decimal | None:
        return to_cents(self.best_ask)

    @property
    def is_two_sided(self) -> bool:
        return self.best_bid is not None and self.best_ask is not None


# =========================================================================
# Panel — frozen-set loader + gap-aware at-or-before lookup
# =========================================================================

class Panel:
    """Frozen 30s REST panel reader with gap-aware book reconstruction.

    The default instance reads the committed `timeofday_poll.csv` clipped to the
    frozen cutoff; tests inject a small fixture CSV via `csv_path`.
    """

    def __init__(
        self,
        csv_path: str | Path = PANEL_CSV,
        *,
        cutoff: pd.Timestamp | None = FROZEN_CUTOFF,
        gap_tolerance_s: float = DEFAULT_GAP_TOLERANCE_S,
        outages: list[tuple[pd.Timestamp, pd.Timestamp]] | None = None,
    ):
        self.csv_path = Path(csv_path)
        self.cutoff = cutoff
        self.gap_tolerance_s = float(gap_tolerance_s)
        self.outages = DEFAULT_OUTAGES if outages is None else list(outages)
        self._df: pd.DataFrame | None = None
        self._idx: dict[tuple[str, str], pd.DataFrame] = {}

    def _load(self) -> pd.DataFrame:
        if self._df is None:
            # pandas CSV reader rejoins quoted multi-line fields -> R9-safe.
            df = pd.read_csv(self.csv_path)
            df["ts"] = pd.to_datetime(df["utc_ts"], utc=True, errors="coerce")
            df = df[df["ts"].notna()]
            if self.cutoff is not None:
                df = df[df["ts"] < self.cutoff]
            self._df = df.reset_index(drop=True)
        return self._df

    def _leg(self, venue: str, market: str) -> pd.DataFrame:
        """Sorted, two-sided-only rows for one (venue, market) leg."""
        key = (venue.lower(), market)
        if key not in self._idx:
            df = self._load()
            row_venue = f"{venue.lower()}_yes"   # YES-side convention
            sub = df[(df["market_id"] == market) & (df["venue"] == row_venue)]
            # A valid book state requires BOTH sides present (audit "two-sided");
            # error/one-sided rows are skipped so they read as gaps, not books.
            sub = sub[sub["best_bid"].notna() & sub["best_ask"].notna()]
            self._idx[key] = (sub.sort_values("ts").reset_index(drop=True)
                              [["ts", "best_bid", "best_ask"]])
        return self._idx[key]

    def _in_outage(self, t: pd.Timestamp) -> bool:
        return any(lo < t < hi for lo, hi in self.outages)

    def book_state(self, venue: str, market: str, t) -> BookState | None:
        """Last two-sided snapshot at-or-before `t` for (venue, market).

        Returns None — never a stale fabrication — when `t` is inside a known
        outage, before any data, or when the latest snapshot is older than
        `gap_tolerance_s`.
        """
        t = pd.Timestamp(t)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        if self._in_outage(t):
            return None
        leg = self._leg(venue, market)
        if leg.empty:
            return None
        pos = int(leg["ts"].searchsorted(t, side="right")) - 1
        if pos < 0:
            return None
        row = leg.iloc[pos]
        age = (t - row["ts"]).total_seconds()
        if age > self.gap_tolerance_s:
            return None
        v = venue.lower()
        return BookState(
            venue=v, market_id=market, ts=row["ts"],
            best_bid=to_prob(row["best_bid"], v),
            best_ask=to_prob(row["best_ask"], v),
            bid_sz=None, ask_sz=None,
            raw_best_bid=float(row["best_bid"]),
            raw_best_ask=float(row["best_ask"]),
            tick_size=venue_tick(v),
            query_ts=t, age_s=age,
        )

    def paired_state(self, pair_id: str, t) -> tuple[BookState, BookState] | None:
        """(Kalshi, Polymarket) YES book states for `pair_id` at `t`, or None if
        EITHER leg is unavailable. `pair_id` is the markets.yaml id (join key)."""
        k = self.book_state("kalshi", pair_id, t)
        if k is None:
            return None
        p = self.book_state("polymarket", pair_id, t)
        if p is None:
            return None
        return (k, p)


# =========================================================================
# Module-level convenience (default frozen panel)
# =========================================================================

_DEFAULT_PANEL: Panel | None = None


def default_panel() -> Panel:
    global _DEFAULT_PANEL
    if _DEFAULT_PANEL is None:
        _DEFAULT_PANEL = Panel()
    return _DEFAULT_PANEL


def book_state(venue: str, market: str, t) -> BookState | None:
    return default_panel().book_state(venue, market, t)


def paired_state(pair_id: str, t) -> tuple[BookState, BookState] | None:
    return default_panel().paired_state(pair_id, t)


# =========================================================================
# Cross helpers (gross + fee-adjusted)
# =========================================================================

def _best_cross_cents(
    pair: tuple[BookState, BookState],
    tier,
    *,
    kalshi_category: str | None = None,
    pm_category: str | None = None,
    pm_rate: float | None = None,
) -> Decimal | None:
    """Signed best-direction cross in CENTS under `tier` (Tier.ZERO = gross).

    Two directions (YES leg, taking liquidity on both venues):
      A: buy Polymarket ask, sell Kalshi bid  ->  k_bid - p_ask
      B: buy Kalshi ask,      sell Polymarket bid -> p_bid - k_ask
    Fees: buy legs add their fee to cost, sell legs subtract from proceeds.
    Returns the larger of the two net edges; None if neither is computable.
    """
    from fees import Tier, leg_fee  # local import to avoid hard import cycle

    k, p = pair

    def kf(price: Decimal, role: str) -> Decimal:
        return Decimal(str(leg_fee("kalshi", float(price), tier=tier, role=role,
                                   category=kalshi_category)))

    def pf(price: Decimal, role: str) -> Decimal:
        return Decimal(str(leg_fee("polymarket", float(price), tier=tier, role=role,
                                   category=pm_category, pm_rate=pm_rate)))

    cands: list[Decimal] = []
    # Direction A: sell Kalshi @ bid, buy Polymarket @ ask
    if k.best_bid is not None and p.best_ask is not None:
        proceeds = k.best_bid - kf(k.best_bid, "taker")
        cost = p.best_ask + pf(p.best_ask, "taker")
        cands.append(proceeds - cost)
    # Direction B: buy Kalshi @ ask, sell Polymarket @ bid
    if k.best_ask is not None and p.best_bid is not None:
        proceeds = p.best_bid - pf(p.best_bid, "taker")
        cost = k.best_ask + kf(k.best_ask, "taker")
        cands.append(proceeds - cost)

    if not cands:
        return None
    if tier is Tier.ZERO:  # exact pre-fee cross (no float fee noise)
        return max(cands) * HUNDRED
    return max(cands) * HUNDRED


def cross_size(pair: tuple[BookState, BookState], fee_tier=None, **kwargs) -> Decimal | None:
    """Signed best-direction cross in cents. `fee_tier` omitted/None or Tier.ZERO
    gives the GROSS (pre-fee) cross; pass a real tier for the fee-adjusted cross.
    Positive => the books cross in that tier's favor."""
    from fees import Tier
    tier = Tier.ZERO if fee_tier is None else fee_tier
    return _best_cross_cents(pair, tier, **kwargs)


def is_crossed(pair: tuple[BookState, BookState], fee_tier=None, **kwargs) -> bool:
    """True iff the cross is strictly positive under `fee_tier` (None/ZERO = gross)."""
    c = cross_size(pair, fee_tier, **kwargs)
    return c is not None and c > 0
