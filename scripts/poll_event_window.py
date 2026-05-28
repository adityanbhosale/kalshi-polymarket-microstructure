"""F.1 event-window dense burst poller (Build F.1).

Used to overlay a tight-cadence (default 5 s) capture on a small set of
markets during a known catalyst window — e.g., Colombia first round
2026-05-31 — *while* the E.1 30-second daemon keeps running across all
16 markets in the background. This is NOT a replacement for E.1; it's
an overlay that makes the lead-lag analysis viable.

Reuse, not rewrite: every per-cycle helper (retry, expected_404
demotion, normalize, microstructure compute, mid-discrepancy compute,
gzip dump) is imported directly from ``poll_timeofday`` so both pollers
go through the identical compute path. We touch nothing in
``poll_timeofday.py`` itself — the running daemon is unaffected.

Schema parity with ``timeofday_poll.csv`` plus an extra ``event_label``
column so dense rows can be merged into the baseline series cleanly in
``window_event.py``.

Usage (interactive — caffeinate keeps the laptop awake on battery):

    caffeinate -i uv run python scripts/poll_event_window.py \\
        --markets intl_president_co_aesp,intl_president_co_pval,intl_president_r1_co_icas \\
        --interval-sec 5 \\
        --start-utc 2026-05-31T22:00:00+00:00 \\
        --end-utc   2026-06-01T05:00:00+00:00 \\
        --label colombia_r1

Behavior:
    * Idles (sleeping in slices, SIGTERM-responsive) until ``--start-utc``.
    * Each cycle: 3 API calls per market (1 Kalshi + 2 Polymarket), paced
      ~75 ms apart, exponential backoff on 429s, expected 404s demoted.
    * Writes 4 venue rows per market to
      ``data/processed/event_<label>_poll.csv``.
    * Dumps gzipped raw bundles to
      ``data/raw/event/<label>/<UTC-date>/<utc_ts>_<market_id>.json.gz``.
    * Exits cleanly at ``--end-utc`` or on SIGTERM/SIGINT (Ctrl-C).
"""
from __future__ import annotations

import argparse
import csv
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Make sibling scripts importable without modifying poll_timeofday.py.
# The daemon's helpers are stateless — they don't read or write the
# daemon's CSV / RAW_DIR globals; they just pure-functionally compute on
# their arguments. Importing this script does not start its main loop
# (guarded by ``if __name__ == "__main__"`` over there).
sys.path.insert(0, str(Path(__file__).parent))
from poll_timeofday import (  # noqa: E402  — import-from-sibling-script
    INTER_CALL_PACING_S,
    SCHEMA_VERSION,
    VENUE_KEYS,
    _fetch_with_retries,
    _gzip_dump,
    _is_degenerate_market,
    _is_expected_404,
    _iso_utc,
    _polymarket_book_to_dict,
    _safe_normalize_kalshi,
    _safe_normalize_polymarket,
    _utc_now,
)
from pm_micro.arb import compute_mid_discrepancy
from pm_micro.clients import kalshi, polymarket
from pm_micro.microstructure import compute_microstructure

REPO_ROOT = Path(__file__).parent.parent
MARKETS_YAML = REPO_ROOT / "markets.yaml"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RAW_BASE = REPO_ROOT / "data" / "raw" / "event"
LOGS_DIR = REPO_ROOT / "logs"

# Long-format schema: same as timeofday_poll.csv, plus event_label so
# rows from different events can be merged or filtered downstream.
CSV_FIELDS_EVENT: tuple[str, ...] = (
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
    "event_label",
    "error",
)

_shutdown_requested = False


def _request_shutdown(signum: int, _frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    try:
        sys.stderr.write(
            f"[{_iso_utc(_utc_now())}] received signal {signum}; "
            "finishing cycle and exiting\n"
        )
        sys.stderr.flush()
    except Exception:
        pass


def _book_metrics(book) -> dict:
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
        "depth_within_1c": micro.depth_within_1c,
    }


def _ensure_csv_header(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists():
        with csv_path.open("w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS_EVENT).writeheader()


def _append_rows(csv_path: Path, rows: list[dict]) -> None:
    with csv_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS_EVENT)
        for row in rows:
            w.writerow({k: row.get(k) for k in CSV_FIELDS_EVENT})


def poll_one_market(
    market: dict, cycle_ts: str, raw_subdir: Path, label: str
) -> tuple[list[dict], bool]:
    """Same per-market logic as ``poll_timeofday.poll_one_market``, with
    the event-label column appended to each row and the gzip-dump path
    routed under ``data/raw/event/<label>/``."""
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

    if err_pyes == "404" and _is_expected_404(market, "yes"):
        err_pyes = "expected_404"
    if err_pno == "404" and _is_expected_404(market, "no"):
        err_pno = "expected_404"

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

    mid_disc_direct = None
    mid_disc_synth = None
    try:
        if kyes is not None and pyes_book is not None:
            md = compute_mid_discrepancy(kyes, pyes_book, pno_book, mid_id)
            mid_disc_direct = md.discrepancy_direct_cents
            mid_disc_synth = md.discrepancy_synthetic_cents
    except Exception:
        pass

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
            "event_label": label,
            "error": err,
        })

    market_had_real_error = any(
        err and err != "expected_404" for _, err in venue_data.values()
    )

    try:
        ts_compact = cycle_ts.replace(":", "").replace("+00:00", "Z")
        payload = {
            "utc_ts": cycle_ts,
            "market_id": mid_id,
            "event_label": label,
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
            sys.stderr.write(
                f"[{_iso_utc(_utc_now())}] gzip dump failed for {mid_id}: {e}\n"
            )
            sys.stderr.flush()
        except Exception:
            pass

    return rows, market_had_real_error


def _parse_iso_utc(s: str) -> datetime:
    """Reject naive timestamps so the event-window CLI can never schedule
    against an ambiguous local time."""
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"invalid ISO timestamp {s!r}: {e}") from e
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"timestamp must be tz-aware (e.g. ...+00:00); got {s!r}"
        )
    return dt.astimezone(timezone.utc)


def _idle_until(target_utc: datetime) -> None:
    """Sleep in small slices until ``target_utc``, honoring SIGTERM."""
    last_log = 0.0
    while not _shutdown_requested:
        now = _utc_now()
        if now >= target_utc:
            return
        wait_s = (target_utc - now).total_seconds()
        # Log roughly once a minute while idling.
        if time.monotonic() - last_log > 60:
            sys.stderr.write(
                f"[{_iso_utc(now)}] idling for {wait_s:.0f}s "
                f"until start_utc={_iso_utc(target_utc)}\n"
            )
            sys.stderr.flush()
            last_log = time.monotonic()
        time.sleep(min(0.5, max(0.1, wait_s)))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Dense event-window poller. See module docstring for usage."
    )
    ap.add_argument(
        "--markets", required=True,
        help="Comma-separated market_ids (must exist in markets.yaml)",
    )
    ap.add_argument("--interval-sec", type=float, default=5.0)
    ap.add_argument(
        "--start-utc", type=_parse_iso_utc, default=None,
        help="Idle until this tz-aware ISO UTC timestamp. Default: start now.",
    )
    ap.add_argument(
        "--end-utc", type=_parse_iso_utc, default=None,
        help="Exit when this tz-aware ISO UTC timestamp is reached. "
             "Default: run until SIGTERM/SIGINT.",
    )
    ap.add_argument(
        "--label", required=True,
        help="Event tag, used in output paths and the event_label column.",
    )
    ap.add_argument(
        "--max-cycles", type=int, default=0,
        help="Smoke-test override: exit after N cycles (0=unlimited).",
    )
    args = ap.parse_args()

    requested_ids = [m.strip() for m in args.markets.split(",") if m.strip()]
    yaml_data = yaml.safe_load(MARKETS_YAML.read_text()) or []
    by_id = {m["id"]: m for m in yaml_data}
    missing = [m for m in requested_ids if m not in by_id]
    if missing:
        print(f"❌ unknown market_ids in --markets: {missing}", file=sys.stderr)
        return 2
    if not requested_ids:
        print("❌ --markets must contain at least one id", file=sys.stderr)
        return 2
    markets = [by_id[m] for m in requested_ids]

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    raw_dir = RAW_BASE / args.label
    raw_dir.mkdir(parents=True, exist_ok=True)
    csv_path = PROCESSED_DIR / f"event_{args.label}_poll.csv"
    _ensure_csv_header(csv_path)

    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    sys.stderr.write(
        f"[{_iso_utc(_utc_now())}] event poller starting; pid={os.getpid()} "
        f"label={args.label!r} markets={requested_ids} "
        f"interval={args.interval_sec}s "
        f"start={_iso_utc(args.start_utc) if args.start_utc else 'now'} "
        f"end={_iso_utc(args.end_utc) if args.end_utc else 'until-shutdown'} "
        f"max_cycles={args.max_cycles or 'unlimited'}\n"
    )
    sys.stderr.flush()

    if args.start_utc is not None:
        _idle_until(args.start_utc)
        if _shutdown_requested:
            sys.stderr.write(f"[{_iso_utc(_utc_now())}] shutdown during idle, exiting\n")
            sys.stderr.flush()
            return 0

    cycle_idx = 0
    while not _shutdown_requested:
        if args.end_utc is not None and _utc_now() >= args.end_utc:
            sys.stderr.write(
                f"[{_iso_utc(_utc_now())}] reached --end-utc, exiting cleanly\n"
            )
            sys.stderr.flush()
            break

        cycle_idx += 1
        cycle_start = time.monotonic()
        cycle_dt = _utc_now()
        cycle_ts = _iso_utc(cycle_dt)
        raw_subdir = raw_dir / cycle_dt.date().isoformat()

        all_rows: list[dict] = []
        n_ok = 0
        n_err = 0
        for market in markets:
            try:
                mr, had_err = poll_one_market(market, cycle_ts, raw_subdir, args.label)
            except Exception as e:
                err_str = (
                    f"poll_market_unhandled: {type(e).__name__}: {str(e)[:200]}"
                )
                sys.stderr.write(
                    f"[{_iso_utc(_utc_now())}] unhandled per-market exception "
                    f"on {market.get('id', '?')}: {err_str}\n"
                )
                sys.stderr.flush()
                mr = [{
                    "utc_ts": cycle_ts,
                    "market_id": market.get("id", "?"),
                    "category": market.get("category", ""),
                    "prob_bucket": market.get("prob_bucket", ""),
                    "is_degenerate": _is_degenerate_market(market),
                    "venue": v,
                    "best_bid": None, "best_ask": None, "mid": None,
                    "spread_bps": None, "depth_within_1c": None,
                    "mid_disc_direct": None, "mid_disc_synth": None,
                    "schema_version": SCHEMA_VERSION,
                    "event_label": args.label,
                    "error": err_str,
                } for v in VENUE_KEYS]
                had_err = True
            all_rows.extend(mr)
            if had_err:
                n_err += 1
            else:
                n_ok += 1
            if _shutdown_requested:
                break

        _append_rows(csv_path, all_rows)
        elapsed = time.monotonic() - cycle_start
        sys.stderr.write(
            f"[{cycle_ts}] cycle={cycle_idx} markets={len(markets)} "
            f"n_ok={n_ok} n_err={n_err} elapsed={elapsed:.2f}s\n"
        )
        sys.stderr.flush()

        if _shutdown_requested:
            break
        if args.max_cycles and cycle_idx >= args.max_cycles:
            sys.stderr.write(
                f"[{_iso_utc(_utc_now())}] reached --max-cycles={args.max_cycles}, "
                "exiting\n"
            )
            sys.stderr.flush()
            break

        sleep_s = max(0.0, args.interval_sec - elapsed)
        sleep_until = time.monotonic() + sleep_s
        # Sleep in small slices so SIGTERM gets honored within ~250 ms.
        while not _shutdown_requested and time.monotonic() < sleep_until:
            remaining = sleep_until - time.monotonic()
            time.sleep(min(0.25, max(0.001, remaining)))

    sys.stderr.write(f"[{_iso_utc(_utc_now())}] event poller exiting cleanly\n")
    sys.stderr.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
