"""Shared helpers for cross-venue market discovery (D.1).

Hosts:
 * Locked configuration constants (volume floors, probability buckets,
   resolution-window cutoff). These mirror the values in the D.1 spec and are
   imported by both ``scripts/discover_markets.py`` and
   ``scripts/validate_markets_yaml.py`` so that any future revision happens in
   one place.
 * Pure helpers for:
    - Probability-bucket assignment.
    - Parlay-series detection (heuristic: ticker length + title keywords).
    - ISO datetime parsing and time-to-resolution arithmetic.
    - Composite match scoring (rapidfuzz token-set + date proximity).
    - Polymarket condition-id / token-id length validation. The 14-char
      truncation bug from Phase 2 (commit ``e8ff31c``) is the proximate
      reason this validator exists; the token-length checks here are the
      single source of truth used by both D.1 scripts.
 * Thin discovery-time API helpers that the existing ``pm_micro.clients``
   modules don't expose:
    - ``list_kalshi_series`` (no helper today; ``/series`` is unwrapped).
    - ``fetch_polymarket_active_markets`` (Gamma ``/markets`` paginated, with
      the full record retained — the existing ``polymarket.search_markets``
      drops ``endDate``, which we need for the date-proximity score).

The clients in ``pm_micro.clients`` remain untouched per D.1 guardrails.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import httpx
from rapidfuzz import fuzz

# === Locked constants (D.1 spec) =====================================
MIN_KALSHI_VOLUME_USD: float = 25_000.0
MIN_POLYMARKET_VOLUME_USD: float = 25_000.0
MIN_COMBINED_OI_USD: float = 50_000.0
MIN_DAYS_TO_RESOLUTION: float = 2.0

PROB_BUCKETS: dict[str, tuple[float, float]] = {
    "tail_low":  (0.00, 0.10),
    "mid_low":   (0.10, 0.30),
    "central":   (0.30, 0.70),
    "mid_high":  (0.70, 0.90),
    "tail_high": (0.90, 1.00),
}

# === Validation constants ============================================
POLYMARKET_CONDITION_ID_LEN: int = 66   # "0x" + 64 hex chars

# Polymarket token IDs are uint256 values rendered as decimal strings.
# Empirically the active universe contains 76-, 77-, and 78-char IDs (the
# value's magnitude determines the digit count); requiring exactly 77 was an
# overcorrection from the Phase 2 NYK truncation bug that flagged
# legitimately-shaped IDs as malformed. We now accept 76-78 chars and
# additionally require every character to be a base-10 digit, which still
# catches the original 14-char truncation pattern and other obvious garbage.
POLYMARKET_TOKEN_ID_MIN_LEN: int = 76
POLYMARKET_TOKEN_ID_MAX_LEN: int = 78
# Retained for backwards compatibility with prior call sites; new code should
# prefer the min/max bounds above.
POLYMARKET_TOKEN_ID_LEN: int = 77

DATE_PROXIMITY_WINDOW_DAYS: float = 14.0

# === Parlay-filter heuristic =========================================
KALSHI_PARLAY_TICKER_MAX_LEN: int = 25
PARLAY_KEYWORDS: tuple[str, ...] = ("parlay", "multi-game", "extended", "multigame")

# === Match-score weighting ===========================================
NAME_WEIGHT: float = 0.7
DATE_WEIGHT: float = 0.3
NEUTRAL_DATE_SCORE: float = 0.5

# === Endpoints (read-only) ===========================================
KALSHI_BASE_URL: str = "https://api.elections.kalshi.com/trade-api/v2"
POLYMARKET_GAMMA_URL: str = "https://gamma-api.polymarket.com"


# ---------------------------------------------------------------------
# Bucket / parlay / time helpers
# ---------------------------------------------------------------------
def assign_prob_bucket(probability: float | None) -> str | None:
    """Map a probability in [0, 1] to one of the five named buckets.

    Returns ``None`` when the probability is missing. The endpoint p == 1.0
    is rolled into ``tail_high`` for completeness (the half-open interval
    ``[0.90, 1.00)`` would otherwise drop it).
    """
    if probability is None:
        return None
    if probability < 0 or probability > 1:
        return None
    if probability == 1.0:
        return "tail_high"
    for name, (lo, hi) in PROB_BUCKETS.items():
        if lo <= probability < hi:
            return name
    return None


def is_parlay_series(ticker: str | None, title: str | None = None) -> bool:
    """Heuristically flag auto-generated parlay/multi-game series."""
    if not ticker:
        return True
    if len(ticker) > KALSHI_PARLAY_TICKER_MAX_LEN:
        return True
    haystack = f"{ticker} {title or ''}".lower()
    return any(kw in haystack for kw in PARLAY_KEYWORDS)


def parse_iso_dt(s: str | None) -> datetime | None:
    """Parse an ISO-8601 string to an aware UTC datetime (None on failure)."""
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def days_until(dt: datetime | None, now: datetime | None = None) -> float | None:
    """Days from ``now`` (default: utcnow) to ``dt``. Negative if past."""
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - now).total_seconds() / 86_400.0


# ---------------------------------------------------------------------
# Match scoring
# ---------------------------------------------------------------------
def _date_proximity_score(
    a: datetime | None,
    b: datetime | None,
    window_days: float = DATE_PROXIMITY_WINDOW_DAYS,
) -> float:
    """Date-proximity component in [0, 1].

    Returns ``NEUTRAL_DATE_SCORE`` when either date is missing (no information,
    so we don't bias the match either direction). When both dates are present,
    decays linearly from 1.0 (same day) to 0.5 (``window_days`` apart) and
    falls to 0.0 beyond the window.
    """
    if a is None or b is None:
        return NEUTRAL_DATE_SCORE
    delta = abs((a - b).total_seconds()) / 86_400.0
    if delta > window_days:
        return 0.0
    return 1.0 - 0.5 * (delta / window_days)


def score_match(
    kalshi_event: str,
    polymarket_question: str,
    kalshi_close_dt: datetime | None,
    polymarket_end_dt: datetime | None,
) -> float:
    """Composite match score in [0, 1].

    Combines a string-similarity component (rapidfuzz ``token_set_ratio``,
    which is forgiving of word-order and stopword differences) with a
    date-proximity component. Weights are ``NAME_WEIGHT`` / ``DATE_WEIGHT``.

    Conservative bias: callers should treat scores below 0.5 as uncertain.
    Empty inputs produce a 0.0 score.
    """
    if not kalshi_event or not polymarket_question:
        return 0.0
    name_score = fuzz.token_set_ratio(kalshi_event, polymarket_question) / 100.0
    date_score = _date_proximity_score(kalshi_close_dt, polymarket_end_dt)
    return round(NAME_WEIGHT * name_score + DATE_WEIGHT * date_score, 3)


# ---------------------------------------------------------------------
# Polymarket id validation
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class IdValidationResult:
    ok: bool
    errors: tuple[str, ...]


def validate_polymarket_ids(
    condition_id: str | None,
    yes_token_id: str | None,
    no_token_id: str | None,
) -> IdValidationResult:
    """Length-and-prefix validate the trio of Polymarket identifiers.

    Catches the 14-char truncation pattern that produced the Phase 2/5b
    NYK regression: the spec's literal assertions are encoded here so both
    discovery and yaml validation agree on what "well-formed" means.
    """
    errors: list[str] = []

    if not isinstance(condition_id, str):
        errors.append("condition_id missing or not a string")
    elif len(condition_id) != POLYMARKET_CONDITION_ID_LEN:
        errors.append(
            f"condition_id length {len(condition_id)} != {POLYMARKET_CONDITION_ID_LEN}"
        )
    elif not condition_id.startswith("0x"):
        errors.append("condition_id missing 0x prefix")

    for label, tid in (("yes_token_id", yes_token_id), ("no_token_id", no_token_id)):
        if not isinstance(tid, str):
            errors.append(f"{label} missing or not a string")
            continue
        if not (POLYMARKET_TOKEN_ID_MIN_LEN <= len(tid) <= POLYMARKET_TOKEN_ID_MAX_LEN
                and tid.isdigit()):
            preview = tid[:20]
            errors.append(
                f"{label} malformed: len={len(tid)}, value={preview}..."
            )

    return IdValidationResult(ok=not errors, errors=tuple(errors))


# ---------------------------------------------------------------------
# Discovery-time API helpers (kept here, not in clients/, per guardrails)
# ---------------------------------------------------------------------
def list_kalshi_series(limit: int = 1000) -> list[dict]:
    """GET /series?limit=N. Returns the raw ``series`` list from the response.

    The existing ``pm_micro.clients.kalshi`` doesn't wrap ``/series``; rather
    than modify that module (D.1 guardrail) the call lives here.
    """
    with httpx.Client(timeout=15.0, base_url=KALSHI_BASE_URL) as client:
        resp = client.get("/series", params={"limit": limit})
        resp.raise_for_status()
        payload = resp.json()
    if isinstance(payload, list):
        return payload
    return payload.get("series", []) or []


def filter_recent_eligible_series(
    series: list[dict],
    *,
    recency_days: float = 7.0,
    max_series: int | None = 500,
    anchor_tickers: Iterable[str] = (),
    now: datetime | None = None,
) -> list[dict]:
    """Reduce a raw ``/series`` list to per-series-enumeration targets.

    Pipeline:
      * drop parlay-style (:func:`is_parlay_series`),
      * keep series whose ``last_updated_ts`` is within ``recency_days``,
      * sort by ``last_updated_ts`` descending,
      * cap at ``max_series`` (None = no cap),
      * union with the records for any ``anchor_tickers`` regardless of age
        (these always get enumerated; useful for keeping known-anchor series
        like ``KXNBA`` in the run even when their last_updated_ts has aged
        past the recency window).

    Returns a fresh list with anchors first. ``last_updated_ts`` is parsed
    permissively (epoch seconds *or* ISO string).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now.timestamp() - recency_days * 86_400.0
    anchors = {a.upper() for a in anchor_tickers if isinstance(a, str)}

    def _ts(value) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return parse_iso_dt(value).timestamp()  # type: ignore[union-attr]
        except (AttributeError, ValueError, TypeError):
            return 0.0

    by_ticker = {
        (s.get("ticker") or "").upper(): s
        for s in series
        if not is_parlay_series(s.get("ticker"), s.get("title"))
    }
    anchor_records = [by_ticker[a] for a in anchors if a in by_ticker]

    recent = [
        s for s in by_ticker.values()
        if _ts(s.get("last_updated_ts")) >= cutoff
        and (s.get("ticker") or "").upper() not in anchors
    ]
    recent.sort(key=lambda s: _ts(s.get("last_updated_ts")), reverse=True)
    if max_series is not None:
        recent = recent[:max_series]
    return anchor_records + recent


def fetch_kalshi_markets_for_series(
    series_ticker: str,
    *,
    min_volume_usd: float = MIN_KALSHI_VOLUME_USD,
    status: str = "open",
    limit: int = 200,
) -> list[dict]:
    """One ``/markets?series_ticker=...`` call, USD-filtered post-fetch.

    The existing ``pm_micro.clients.kalshi.search_markets`` helper covers this
    exact request; we re-target the same endpoint here so the caller can
    apply USD-vs-contracts filtering inside this module without forking the
    helper. The ``min_volume`` argument on the existing helper filters on the
    integer ``volume`` field (contracts), which Phase 2 documented as
    unreliable; ``volume_fp`` is the dollar-denominated truth.
    """
    params: dict[str, str | int] = {
        "status": status,
        "limit": limit,
        "series_ticker": series_ticker.upper(),
    }
    with httpx.Client(timeout=15.0, base_url=KALSHI_BASE_URL) as client:
        resp = client.get("/markets", params=params)
        resp.raise_for_status()
        markets = resp.json().get("markets", []) or []
    return [m for m in markets if kalshi_volume_usd(m) >= min_volume_usd]


def is_parlay_market(market: dict) -> bool:
    """Heuristic — is this an auto-generated parlay/multi-game market?

    Kalshi's parlay markets surface as standalone records under series like
    ``KXMVESPORTSMULTIGAMEEXTENDED`` with comma-separated leg titles and very
    long composite tickers. We catch them via:
     * Ticker-prefix length (the part before the first ``-``) > 25 chars.
     * Title containing any parlay keyword.
     * Title containing a comma (the leg-list signature).
    """
    ticker = market.get("ticker") or ""
    title = (market.get("title") or "").strip()
    prefix = ticker.split("-", 1)[0]
    if len(prefix) > KALSHI_PARLAY_TICKER_MAX_LEN:
        return True
    haystack = f"{ticker} {title}".lower()
    if any(kw in haystack for kw in PARLAY_KEYWORDS):
        return True
    # Comma-separated leg lists are a strong parlay signal; legitimate
    # event titles rarely use commas at the body level.
    if title.count(",") >= 2:
        return True
    return False


def fetch_polymarket_active_markets(
    page_size: int = 100,
    max_pages: int = 60,
    sleep_between_pages: float = 0.4,
) -> list[dict]:
    """Pull active+open Polymarket markets via the Gamma ``/markets`` endpoint.

    Returns the **raw** Gamma payload per market, including ``endDate``,
    ``conditionId``, ``clobTokenIds``, and ``volume``. We need ``endDate`` for
    the date-proximity component of the match score, and the existing
    ``pm_micro.clients.polymarket.search_markets`` strips it to a fixed
    projection. Same endpoint, same filters — just the full record.

    Pagination: ``page_size`` records per page (Gamma caps at 100 regardless
    of the requested limit), up to ``max_pages``. Stops when a page returns
    fewer records than ``page_size`` or when no new conditionIds appear in
    the page (defensive — observed offsets sometimes loop on this endpoint).
    """
    out: list[dict] = []
    seen: set[str] = set()
    with httpx.Client(timeout=20.0, base_url=POLYMARKET_GAMMA_URL) as client:
        for page_idx in range(max_pages):
            params = {
                "active": "true",
                "closed": "false",
                "limit": page_size,
                "offset": page_idx * page_size,
            }
            resp = client.get("/markets", params=params)
            resp.raise_for_status()
            page = resp.json()
            if not page:
                break
            new_in_page = 0
            for m in page:
                cid = m.get("conditionId") or m.get("condition_id")
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                out.append(m)
                new_in_page += 1
            if len(page) < page_size or new_in_page == 0:
                break
            if page_idx < max_pages - 1:
                time.sleep(sleep_between_pages)
    return out


# ---------------------------------------------------------------------
# Field-extraction helpers (used by both scripts)
# ---------------------------------------------------------------------
def kalshi_volume_usd(market: dict) -> float:
    """Dollar-denominated volume from Kalshi /markets ``volume_fp`` field.

    The existing ``kalshi.search_markets(min_volume=...)`` post-filter uses the
    integer ``volume`` field (contracts), which Phase 2's mapping-notebook fix
    documented as the wrong field for USD comparisons (see commits 36b... and
    the Phase 2 prose). Discovery filters by ``volume_fp`` instead.
    """
    raw = market.get("volume_fp")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def polymarket_volume_usd(market: dict) -> float:
    """Dollar-denominated volume from a Gamma ``/markets`` record."""
    raw = market.get("volume")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def kalshi_yes_probability(market: dict) -> float | None:
    """Best-effort YES probability from a Kalshi /markets record.

    Kalshi's ``/markets`` payload exposes ``yes_bid_dollars`` and
    ``yes_ask_dollars`` (already in dollars / probability units). We prefer
    the bid as a conservative proxy for the standing-buy probability, falling
    back to the ask, then to the legacy integer ``yes_bid`` / ``yes_ask``
    cents fields if neither is present (older response shapes).
    """
    for key, scale in (
        ("yes_bid_dollars", 1.0),
        ("yes_ask_dollars", 1.0),
        ("yes_bid", 0.01),
        ("yes_ask", 0.01),
    ):
        v = market.get(key)
        if v is None:
            continue
        try:
            return float(v) * scale
        except (ValueError, TypeError):
            continue
    return None


def parse_clob_token_ids(raw) -> tuple[str | None, str | None]:
    """Coerce a Gamma-API ``clobTokenIds`` payload to (yes, no).

    Gamma sometimes returns this as a JSON-encoded string and sometimes as a
    list of two strings, depending on endpoint version.
    """
    if raw is None:
        return None, None
    if isinstance(raw, str):
        import json as _json  # local import to keep top-level lean
        try:
            raw = _json.loads(raw)
        except _json.JSONDecodeError:
            return None, None
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        yes_tid = raw[0] if isinstance(raw[0], str) else None
        no_tid = raw[1] if isinstance(raw[1], str) else None
        return yes_tid, no_tid
    return None, None


def kalshi_event_text(market: dict) -> str:
    """Compose a clean event description from a Kalshi /markets record."""
    parts = [market.get("title") or "", market.get("yes_sub_title") or ""]
    parts = [p.strip() for p in parts if p and p.strip()]
    return " — ".join(parts)
