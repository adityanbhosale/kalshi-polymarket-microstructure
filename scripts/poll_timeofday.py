"""Build E.1 — long-running 30-second poller for the time-of-day study.

Single long-running process. Each cycle, for every market in
``markets.yaml``, fetches:

  * 1× Kalshi orderbook (yields both YES and NO books after reconstruction)
  * 1× Polymarket YES token book
  * 1× Polymarket NO token book

= 3 API calls per market × 16 markets = 48 calls per cycle, paced ~75 ms
apart. Target cadence is 30 s; the cycle measures its own work time and
sleeps `POLL_INTERVAL_SEC − elapsed`, clamped ≥ 0, so cadence stays ~30 s
and consecutive cycles never overlap.

Non-negotiables (Build D lessons):

  * Every datetime is tz-aware UTC. Each ISO-8601 timestamp ends in
    ``+00:00`` and that suffix is asserted before write — no naive
    timestamps are ever persisted (load-bearing for a time-of-day study).
  * The series cannot crash. Per-market or per-book fetch failures are
    captured into the row's ``error`` column; the cycle continues.
  * Compute is reused, not reimplemented. Microstructure metrics come
    from ``pm_micro.microstructure.compute_microstructure``; cross-venue
    discrepancy comes from ``pm_micro.arb.compute_mid_discrepancy``.
    fetch_snapshot.py is NOT forked.

Output:

  * ``data/processed/timeofday_poll.csv`` — long-format, one row per
    (utc_ts, market_id, venue) triple. ``venue`` ∈
    ``{kalshi_yes, kalshi_no, polymarket_yes, polymarket_no}`` to keep
    both venues' both sides in scope without adding a separate ``side``
    column. Cross-venue ``mid_disc_*`` values are denormalized onto each
    of the 4 rows for the same (utc_ts, market_id) pair.
  * ``data/raw/timeofday/<UTC-date>/<utc_ts>_<market_id>.json.gz`` — the
    bundled raw Kalshi + Polymarket-YES + Polymarket-NO orderbooks,
    gzipped, one file per (cycle, market). Gitignored.

Signal handling: SIGTERM / SIGINT request graceful shutdown — the current
cycle's CSV write completes and stderr flushes before exit(0).

Smoke-test: set ``POLL_MAX_CYCLES=4`` to exit after 4 cycles instead of
running forever; this is what the foreground integration test uses.

Usage:

    uv run python scripts/poll_timeofday.py
    POLL_MAX_CYCLES=4 uv run python scripts/poll_timeofday.py   # smoke test
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from pm_micro.arb import compute_mid_discrepancy
from pm_micro.clients import kalshi, polymarket
from pm_micro.microstructure import compute_microstructure
from pm_micro.normalize import (
    NormalizedBook,
    normalize_kalshi_orderbook,
    normalize_polymarket_orderbook,
)

POLL_INTERVAL_SEC = 30
INTER_CALL_PACING_S = 0.075
# Exponential backoff on 429s (max 3 retries, so up to 4 attempts total).
RETRY_BACKOFFS_S: tuple[float, ...] = (0.5, 1.0, 2.0)
SCHEMA_VERSION = 1

REPO_ROOT = Path(__file__).parent.parent
MARKETS_YAML = REPO_ROOT / "markets.yaml"
RAW_DIR = REPO_ROOT / "data" / "raw" / "timeofday"
CSV_PATH = REPO_ROOT / "data" / "processed" / "timeofday_poll.csv"
LOGS_DIR = REPO_ROOT / "logs"

CSV_FIELDS: tuple[str, ...] = (
    "utc_ts",
    "market_id",
    "category",
    "prob_bucket",
    "is_degenerate",
    "venue",
    "best_bid",
    "best_ask",
    "mid",
    "spread_bps",
    "depth_within_1c",
    "mid_disc_direct",
    "mid_disc_synth",
    "schema_version",
    "error",
)

VENUE_KEYS: tuple[str, ...] = (
    "kalshi_yes",
    "kalshi_no",
    "polymarket_yes",
    "polymarket_no",
)

_shutdown_requested = False


# --- Time helpers ------------------------------------------------------
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(dt: datetime) -> str:
    """Tz-aware UTC ISO-8601 with ``+00:00`` suffix.

    Asserts the input is tz-aware UTC and the formatted string ends in
    ``+00:00`` so a naive timestamp can never reach the CSV.
    """
    assert dt.tzinfo is not None, "naive datetime forbidden"
    assert dt.utcoffset() == _ZERO_OFFSET, f"non-UTC datetime: {dt}"
    s = dt.isoformat()
    assert s.endswith("+00:00"), f"unexpected ISO suffix: {s!r}"
    return s


from datetime import timedelta as _td  # noqa: E402  — used only for the offset
_ZERO_OFFSET = _td(0)


# --- Signal handling ---------------------------------------------------
def _request_shutdown(signum: int, _frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    try:
        sys.stderr.write(
            f"[{_iso_utc(_utc_now())}] received signal {signum}; "
            "finishing current cycle and exiting\n"
        )
        sys.stderr.flush()
    except Exception:
        pass


def _install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)


# --- markets.yaml flag inspection -------------------------------------
def _polymarket_status(market: dict, side: str) -> str:
    pm = market.get("polymarket", {}) or {}
    return str(pm.get(f"{side}_token_orderbook_status", "active"))


def _is_expected_404(market: dict, side: str) -> bool:
    """Whether a 404 on this side is documented as ``404_*`` in markets.yaml."""
    return _polymarket_status(market, side).startswith("404")


def _is_degenerate_market(market: dict) -> bool:
    """Heuristic: tail buckets and explicit-delisting markers signal that
    the market is expected to be thin / partly empty / partly 404. Used
    so the CSV reader can filter degenerate rows from health stats."""
    bucket = market.get("prob_bucket", "")
    if bucket in ("tail_low", "tail_high"):
        return True
    if _is_expected_404(market, "yes") or _is_expected_404(market, "no"):
        return True
    return False


# --- Fetch with bounded backoff ---------------------------------------
def _classify_error(exc: Exception) -> tuple[str, bool]:
    """Return ``(error_str, is_rate_limited)``."""
    msg = str(exc)
    msg_lower = msg.lower()
    if "429" in msg or "rate limit" in msg_lower or "too many requests" in msg_lower:
        return "429", True
    if "404" in msg:
        return "404", False
    return f"{type(exc).__name__}: {msg[:200]}", False


def _fetch_with_retries(call: Callable[[], Any]) -> tuple[Any | None, str | None]:
    """Run ``call`` once, retrying with exponential backoff on 429.

    Non-429 errors return immediately with a typed error string. After
    exhausting ``RETRY_BACKOFFS_S`` retries on 429s, returns
    ``(None, "429_backoff_exhausted")``.
    """
    last_err: str | None = None
    for attempt in range(1 + len(RETRY_BACKOFFS_S)):
        if attempt > 0:
            time.sleep(RETRY_BACKOFFS_S[attempt - 1])
        try:
            return call(), None
        except Exception as e:
            err_str, is_rl = _classify_error(e)
            last_err = err_str
            if not is_rl:
                return None, err_str
    return None, "429_backoff_exhausted"


# --- Per-cycle work ----------------------------------------------------
def _book_metrics(book: NormalizedBook | None) -> dict:
    """Pull ``best_bid/best_ask/mid/spread_bps/depth_within_1c`` (or
    ``None``) from a normalized book using the shared microstructure
    compute. Empty books return all-``None`` metrics."""
    if book is None or (not book.bids and not book.asks):
        return {
            "best_bid": None, "best_ask": None, "mid": None,
            "spread_bps": None, "depth_within_1c": None,
        }
    micro = compute_microstructure(book)
    return {
        "best_bid": micro.best_bid,
        "best_ask": micro.best_ask,
        "mid": micro.mid_simple,
        "spread_bps": micro.spread_bps,
        # depth_within_1c is always a float in the dataclass; preserve
        # 0.0 as 0.0 so we can distinguish "empty book" from "missing".
        "depth_within_1c": micro.depth_within_1c,
    }


def _polymarket_book_to_dict(book) -> dict | None:
    """Polymarket SDK returns OrderBookSummary objects with ``.bids`` /
    ``.asks`` lists of OrderSummary objects (string-encoded floats).
    Convert to plain dicts for gzipped JSON dumping."""
    if book is None:
        return None
    return {
        "bids": [{"price": b.price, "size": b.size} for b in (book.bids or [])],
        "asks": [{"price": a.price, "size": a.size} for a in (book.asks or [])],
    }


def _gzip_dump(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))


def _ensure_csv_header() -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        with CSV_PATH.open("w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()


def _append_rows(rows: list[dict]) -> None:
    """Single fsync-bounded append per cycle; stays small even at week-scale."""
    with CSV_PATH.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        for row in rows:
            w.writerow({k: row.get(k) for k in CSV_FIELDS})


def _safe_normalize_kalshi(raw: dict, market_id: str, ts: str):
    try:
        return normalize_kalshi_orderbook(raw, market_id, ts), None
    except Exception as e:
        return (None, None), f"normalize_kalshi: {type(e).__name__}: {str(e)[:120]}"


def _safe_normalize_polymarket(raw, market_id: str, side: str, ts: str):
    try:
        return normalize_polymarket_orderbook(raw, market_id, side, ts), None
    except Exception as e:
        return None, f"normalize_pm_{side}: {type(e).__name__}: {str(e)[:120]}"


def poll_one_market(market: dict, cycle_ts: str, raw_subdir: Path) -> tuple[list[dict], bool]:
    """Fetch + normalize + metric one market for one cycle.

    Returns ``(rows, market_had_real_error)`` where ``rows`` is the list
    of 4 venue-rows for the CSV. ``market_had_real_error`` is True iff
    any venue produced an error string that is **not** ``expected_404``.
    """
    mid_id = market["id"]
    cat = market.get("category", "")
    bucket = market.get("prob_bucket", "")
    degen = _is_degenerate_market(market)

    kalshi_ticker = market["kalshi"]["ticker"]
    yes_tid = market["polymarket"]["yes_token_id"]
    no_tid = market["polymarket"]["no_token_id"]

    raw_kalshi, err_k = _fetch_with_retries(lambda: kalshi.get_orderbook(kalshi_ticker))
    time.sleep(INTER_CALL_PACING_S)
    raw_pyes, err_pyes = _fetch_with_retries(lambda: polymarket.get_orderbook(yes_tid))
    time.sleep(INTER_CALL_PACING_S)
    raw_pno, err_pno = _fetch_with_retries(lambda: polymarket.get_orderbook(no_tid))
    time.sleep(INTER_CALL_PACING_S)

    # Demote documented 404s to "expected_404" so they don't drive the
    # health-stat error rate. A 404 on a side NOT marked delisted in the
    # YAML is still a real error worth flagging.
    if err_pyes == "404" and _is_expected_404(market, "yes"):
        err_pyes = "expected_404"
    if err_pno == "404" and _is_expected_404(market, "no"):
        err_pno = "expected_404"

    # Normalize whatever we have. Don't let a normalize bug crash the cycle.
    kyes = kno = pyes_book = pno_book = None
    if raw_kalshi is not None:
        (kyes, kno), nerr = _safe_normalize_kalshi(raw_kalshi, mid_id, cycle_ts)
        if nerr and err_k is None:
            err_k = nerr
    if raw_pyes is not None:
        pyes_book, nerr = _safe_normalize_polymarket(raw_pyes, mid_id, "yes", cycle_ts)
        if nerr and err_pyes is None:
            err_pyes = nerr
    if raw_pno is not None:
        pno_book, nerr = _safe_normalize_polymarket(raw_pno, mid_id, "no", cycle_ts)
        if nerr and err_pno is None:
            err_pno = nerr

    # Cross-venue mid-discrepancy (per-market; denormalized onto each row).
    mid_disc_direct = None
    mid_disc_synth = None
    try:
        if kyes is not None and pyes_book is not None:
            md = compute_mid_discrepancy(kyes, pyes_book, pno_book, mid_id)
            mid_disc_direct = md.discrepancy_direct_cents
            mid_disc_synth = md.discrepancy_synthetic_cents
    except Exception:
        pass  # silent: mid_disc is best-effort, error rows already cover the failure

    venue_data = {
        "kalshi_yes":     (kyes,       err_k),
        "kalshi_no":      (kno,        err_k),
        "polymarket_yes": (pyes_book,  err_pyes),
        "polymarket_no":  (pno_book,   err_pno),
    }

    rows: list[dict] = []
    for venue, (book, err) in venue_data.items():
        rows.append({
            "utc_ts": cycle_ts,
            "market_id": mid_id,
            "category": cat,
            "prob_bucket": bucket,
            "is_degenerate": degen,
            "venue": venue,
            **_book_metrics(book),
            "mid_disc_direct": mid_disc_direct,
            "mid_disc_synth": mid_disc_synth,
            "schema_version": SCHEMA_VERSION,
            "error": err,
        })

    market_had_real_error = any(
        err and err != "expected_404"
        for _, err in venue_data.values()
    )

    # Best-effort raw dump. If serialization fails we keep going — a
    # missing gzip is better than a missing CSV row.
    try:
        ts_compact = cycle_ts.replace(":", "").replace("+00:00", "Z")
        payload = {
            "utc_ts": cycle_ts,
            "market_id": mid_id,
            "kalshi_orderbook": raw_kalshi,
            "polymarket_yes_orderbook": _polymarket_book_to_dict(raw_pyes),
            "polymarket_no_orderbook": _polymarket_book_to_dict(raw_pno),
            "errors": {
                "kalshi": err_k,
                "polymarket_yes": err_pyes,
                "polymarket_no": err_pno,
            },
        }
        _gzip_dump(payload, raw_subdir / f"{ts_compact}_{mid_id}.json.gz")
    except Exception as e:
        try:
            sys.stderr.write(f"[{_iso_utc(_utc_now())}] gzip dump failed for {mid_id}: {e}\n")
            sys.stderr.flush()
        except Exception:
            pass

    return rows, market_had_real_error


def poll_one_cycle(markets: list[dict]) -> tuple[int, int]:
    """Run one full cycle. Returns ``(n_ok_markets, n_err_markets)``."""
    cycle_dt = _utc_now()
    cycle_ts = _iso_utc(cycle_dt)
    raw_subdir = RAW_DIR / cycle_dt.date().isoformat()

    all_rows: list[dict] = []
    n_ok = 0
    n_err = 0
    for market in markets:
        try:
            rows, had_err = poll_one_market(market, cycle_ts, raw_subdir)
        except Exception as e:
            # Last-resort guard — a per-market failure must NEVER kill the
            # series. Synthesize 4 null rows with the bare error string.
            err_str = f"poll_market_unhandled: {type(e).__name__}: {str(e)[:200]}"
            sys.stderr.write(
                f"[{_iso_utc(_utc_now())}] unhandled per-market exception "
                f"on {market.get('id', '?')}: {err_str}\n"
            )
            sys.stderr.flush()
            mid_id = market.get("id", "?")
            rows = [{
                "utc_ts": cycle_ts,
                "market_id": mid_id,
                "category": market.get("category", ""),
                "prob_bucket": market.get("prob_bucket", ""),
                "is_degenerate": _is_degenerate_market(market),
                "venue": v,
                "best_bid": None, "best_ask": None, "mid": None,
                "spread_bps": None, "depth_within_1c": None,
                "mid_disc_direct": None, "mid_disc_synth": None,
                "schema_version": SCHEMA_VERSION,
                "error": err_str,
            } for v in VENUE_KEYS]
            had_err = True

        all_rows.extend(rows)
        if had_err:
            n_err += 1
        else:
            n_ok += 1

        if _shutdown_requested:
            break

    _append_rows(all_rows)
    return n_ok, n_err


# --- Main loop ---------------------------------------------------------
def main() -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_csv_header()
    _install_signal_handlers()

    max_cycles = int(os.environ.get("POLL_MAX_CYCLES", "0"))

    markets = yaml.safe_load(MARKETS_YAML.read_text()) or []
    sys.stderr.write(
        f"[{_iso_utc(_utc_now())}] poller starting; pid={os.getpid()} "
        f"markets={len(markets)} cadence={POLL_INTERVAL_SEC}s "
        f"max_cycles={max_cycles or 'unlimited'}\n"
    )
    sys.stderr.flush()

    cycle_idx = 0
    while not _shutdown_requested:
        cycle_idx += 1
        cycle_start = time.monotonic()
        cycle_ts_for_log = _iso_utc(_utc_now())
        try:
            n_ok, n_err = poll_one_cycle(markets)
        except Exception as e:
            n_ok, n_err = 0, len(markets)
            sys.stderr.write(
                f"[{_iso_utc(_utc_now())}] CYCLE EXCEPTION (cycle {cycle_idx}): "
                f"{type(e).__name__}: {e}\n"
            )
            sys.stderr.flush()
        elapsed = time.monotonic() - cycle_start
        sys.stderr.write(
            f"[{cycle_ts_for_log}] cycle={cycle_idx} n_ok={n_ok} "
            f"n_err={n_err} elapsed={elapsed:.2f}s\n"
        )
        sys.stderr.flush()

        if _shutdown_requested:
            break
        if max_cycles and cycle_idx >= max_cycles:
            sys.stderr.write(
                f"[{_iso_utc(_utc_now())}] reached POLL_MAX_CYCLES={max_cycles}, "
                "exiting\n"
            )
            sys.stderr.flush()
            break

        sleep_s = max(0.0, POLL_INTERVAL_SEC - elapsed)
        sleep_until = time.monotonic() + sleep_s
        # Sleep in small slices so SIGTERM gets honored within ~0.5 s.
        while not _shutdown_requested and time.monotonic() < sleep_until:
            remaining = sleep_until - time.monotonic()
            time.sleep(min(0.5, max(0.001, remaining)))

    sys.stderr.write(f"[{_iso_utc(_utc_now())}] poller exiting cleanly\n")
    sys.stderr.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
