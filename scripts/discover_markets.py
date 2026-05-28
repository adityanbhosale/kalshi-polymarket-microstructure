"""Discover candidate Kalshi-Polymarket cross-venue pairs (D.1).

Pipeline:
 1. Enumerate Kalshi series via ``/series`` and prune to enumeration targets
    via :func:`discovery.filter_recent_eligible_series` — drop parlay-style
    series, keep only those updated in the last 7 days, sort by recency, cap
    at 500. This deviates from the spec's "limit=1000" assumption; the API
    actually returns ~10,440 series and ignores the limit param. The full
    series list is also used for the per-category footer.
 2. For each surviving series, call
    :func:`discovery.fetch_kalshi_markets_for_series` (one
    ``/markets?series_ticker=...`` request, USD-filtered on ``volume_fp`` —
    the existing helper's ``min_volume`` post-filter operates on a
    contracts-denominated field that Phase 2 documented as unreliable, hence
    the parallel implementation here). Drop parlay/multi-game markets via
    :func:`discovery.is_parlay_market` and markets resolving in
    < ``MIN_DAYS_TO_RESOLUTION`` days.
 3. Pull all active+open Polymarket markets in one paginated batch via
    :func:`discovery.fetch_polymarket_active_markets` (full Gamma payload,
    including ``endDate`` which the existing ``polymarket.search_markets``
    helper drops). Filter to >= ``MIN_POLYMARKET_VOLUME_USD``.
 4. For each Kalshi candidate, find the best Polymarket match by composite
    score: rapidfuzz token-set ratio on event description + resolution-date
    proximity within ±14 days (see :func:`discovery.score_match`).
    Conservative bias — scores < 0.5 are flagged "uncertain".
 5. Validate the matched Polymarket entry: ``condition_id`` length 66 with
    ``0x`` prefix, both ``token_id`` lengths 77, and a single orderbook fetch
    (top-N candidates only, to bound runtime). A 404 on the YES book zeroes
    the match score and adds a ``POLYMARKET_404`` annotation.
 6. Render ``data/processed/discovery_candidates.md`` — table sorted by
    match-score desc, summary footer with totals, per-bucket distribution,
    and per-Kalshi-series category breakdown.

Failure policy: per the D.1 guardrails this script does not auto-retry.
Hard structural failures (HTTP 429 on the unfiltered ``/markets`` walk, the
Polymarket pool fetch, etc.) propagate up and abort the run. Per-row
orderbook fetch failures are recorded as ``POLYMARKET_404`` annotations and
do not abort the overall script.

Usage:
    uv run python scripts/discover_markets.py
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pm_micro.clients import polymarket
from pm_micro.discovery import (
    MIN_COMBINED_OI_USD,
    MIN_DAYS_TO_RESOLUTION,
    MIN_KALSHI_VOLUME_USD,
    MIN_POLYMARKET_VOLUME_USD,
    POLYMARKET_GAMMA_URL,
    PROB_BUCKETS,
    assign_prob_bucket,
    days_until,
    fetch_kalshi_markets_for_series,
    fetch_polymarket_active_markets,
    filter_recent_eligible_series,
    is_parlay_market,
    kalshi_event_text,
    kalshi_volume_usd,
    kalshi_yes_probability,
    list_kalshi_series,
    parse_clob_token_ids,
    parse_iso_dt,
    polymarket_volume_usd,
    score_match,
    validate_polymarket_ids,
)

REPO_ROOT = Path(__file__).parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OUT_PATH = PROCESSED_DIR / "discovery_candidates.md"
MARKETS_YAML_PATH = REPO_ROOT / "markets.yaml"

# Cap how many top-scoring matches get a live orderbook fetch. Anything below
# that simply doesn't get the POLYMARKET_404 annotation; ID validation still
# applies to every row.
ORDERBOOK_VALIDATE_TOP_N = 30
ORDERBOOK_VALIDATE_MIN_SCORE = 0.5
ORDERBOOK_FETCH_SLEEP_S = 1.0

# Per-series-call politeness sleep on Kalshi /markets?series_ticker=...
# Empirically the unfiltered /markets walk hits 429 fast, but the
# series-filtered query is light. 0.7s is a balance between throughput and
# leaving headroom for the public endpoint.
KALSHI_SERIES_SLEEP_S = 0.7

# Cap how many series we enumerate. With ~2,700 recently-updated non-parlay
# series and 0.7s/call, 500 = ~6 minutes of Kalshi calls. Increase if you
# want broader coverage at the cost of runtime.
KALSHI_MAX_SERIES_TO_ENUMERATE = 500
KALSHI_SERIES_RECENCY_DAYS = 7.0


def _category_from_series_ticker(ticker: str) -> str:
    """Coarse 'category' label = leading non-numeric prefix of the series ticker.

    e.g. ``KXNBA-26-OKC`` -> ``KXNBA``, ``KXFEDHIKE`` -> ``KXFEDHIKE``.
    """
    if not ticker:
        return "<unknown>"
    head = ticker.split("-", 1)[0]
    return head or "<unknown>"


def _build_series_category_index(series: list[dict]) -> dict[str, str]:
    """Map series-ticker -> series category (e.g. 'Sports', 'Politics')."""
    out: dict[str, str] = {}
    for s in series:
        tk = s.get("ticker")
        if isinstance(tk, str):
            out[tk.upper()] = (s.get("category") or "<unknown>")
    return out


def _kalshi_market_category(market: dict, series_index: dict[str, str]) -> str:
    """Resolve a market's Kalshi-series category via its event_ticker prefix.

    Falls back to the ticker prefix when the series isn't in the index.
    """
    candidate_keys = [
        market.get("event_ticker"),
        # event_ticker often appends a date suffix; strip after first dash.
        (market.get("event_ticker") or "").split("-", 1)[0],
        # Final fallback: same logic on the market ticker.
        (market.get("ticker") or "").split("-", 1)[0],
    ]
    for key in candidate_keys:
        if isinstance(key, str) and key:
            cat = series_index.get(key.upper())
            if cat:
                return cat
    return _category_from_series_ticker(market.get("ticker") or "")


def _anchor_series_tickers_from_markets_yaml() -> list[str]:
    """Extract the set of Kalshi series tickers referenced in markets.yaml.

    The series ticker is the prefix before the first ``-`` in a market
    ticker (e.g. ``KXNBA-26-OKC`` -> ``KXNBA``). Used as anchors so the
    discovery run always re-enumerates currently-curated series, even if
    their ``last_updated_ts`` has aged past the recency window.
    """
    if not MARKETS_YAML_PATH.exists():
        return []
    try:
        with open(MARKETS_YAML_PATH) as f:
            entries = yaml.safe_load(f) or []
    except Exception:
        return []
    out: set[str] = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        ticker = (entry.get("kalshi") or {}).get("ticker") or ""
        if isinstance(ticker, str) and "-" in ticker:
            out.add(ticker.split("-", 1)[0].upper())
        elif isinstance(ticker, str) and ticker:
            out.add(ticker.upper())
    return sorted(out)


def _within_resolution_window(market: dict, *, now: datetime) -> bool:
    close_dt = parse_iso_dt(market.get("close_time")) or parse_iso_dt(
        market.get("expected_expiration_time")
    )
    days = days_until(close_dt, now=now)
    if days is None:
        return False
    return days >= MIN_DAYS_TO_RESOLUTION


def _best_match(
    kalshi_event: str,
    kalshi_close_dt: datetime | None,
    poly_pool: list[dict],
) -> tuple[dict | None, float]:
    best_score = 0.0
    best_match: dict | None = None
    for pm in poly_pool:
        question = pm.get("question") or ""
        if not question:
            continue
        end_dt = parse_iso_dt(
            pm.get("endDate") or pm.get("end_date_iso") or pm.get("endDateIso")
        )
        score = score_match(kalshi_event, question, kalshi_close_dt, end_dt)
        if score > best_score:
            best_score = score
            best_match = pm
    return best_match, best_score


def _truncate(text: str, n: int) -> str:
    text = (text or "").replace("|", "\\|").replace("\n", " ").strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _format_row(row: dict) -> str:
    return (
        f"| {row['kalshi_ticker']} "
        f"| {_truncate(row['kalshi_event'], 70)} "
        f"| {_truncate(row['polymarket_question'], 70)} "
        f"| ${row['kalshi_vol']:,.0f} "
        f"| ${row['poly_vol']:,.0f} "
        f"| {row['prob_bucket'] or '—'} "
        f"| {row['days_to_resolution']:.1f} "
        f"| {row['match_score']:.3f} "
        f"| {row['notes'] or ''} |"
    )


def _write_markdown(
    rows: list[dict],
    series_count: int,
    eligible_series_count: int,
    kalshi_market_count: int,
    poly_pool_count: int,
    generated_at: datetime,
) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    bucket_counts = Counter(r["prob_bucket"] or "unknown" for r in rows)
    category_counts = Counter(r["kalshi_category"] for r in rows)
    high_conf = sum(1 for r in rows if r["match_score"] >= 0.5)
    poly_404s = sum(1 for r in rows if r.get("polymarket_404"))

    lines: list[str] = []
    lines.append("# Discovery candidates — D.1\n")
    lines.append(
        f"_Generated {generated_at.strftime('%Y-%m-%d %H:%M:%SZ')}_  "
        f"_Source: scripts/discover_markets.py_\n"
    )
    lines.append("## Constants used\n")
    lines.append(f"- `MIN_KALSHI_VOLUME_USD`     = ${MIN_KALSHI_VOLUME_USD:,.0f}")
    lines.append(f"- `MIN_POLYMARKET_VOLUME_USD` = ${MIN_POLYMARKET_VOLUME_USD:,.0f}")
    lines.append(f"- `MIN_COMBINED_OI_USD`       = ${MIN_COMBINED_OI_USD:,.0f}")
    lines.append(f"- `MIN_DAYS_TO_RESOLUTION`    = {MIN_DAYS_TO_RESOLUTION:.0f} days")
    lines.append(
        "- Probability buckets: "
        + ", ".join(f"`{k}`={v[0]:.2f}-{v[1]:.2f}" for k, v in PROB_BUCKETS.items())
    )
    lines.append("")

    lines.append("## Pipeline counts\n")
    lines.append(f"- Kalshi series fetched: **{series_count}**")
    lines.append(f"- Kalshi series after parlay filter: **{eligible_series_count}**")
    lines.append(f"- Kalshi markets surviving volume + days-to-resolution filters: **{kalshi_market_count}**")
    lines.append(f"- Polymarket active markets in matching pool: **{poly_pool_count}**")
    lines.append(f"- Candidate rows below: **{len(rows)}** (high-confidence ≥0.5: **{high_conf}**)")
    if poly_404s:
        lines.append(f"- Rows annotated `POLYMARKET_404`: **{poly_404s}**")
    lines.append("")

    lines.append("## Candidates (sorted by match score)\n")
    lines.append(
        "| kalshi_ticker | kalshi_event | polymarket_question | kalshi_vol "
        "| poly_vol | prob_bucket | days_to_resolution | match_score | notes |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    if not rows:
        lines.append("| _no candidates_ | | | | | | | | |")
    else:
        for r in rows:
            lines.append(_format_row(r))
    lines.append("")

    lines.append("## Summary footer\n")
    lines.append(f"- **Total candidates:** {len(rows)}\n")
    lines.append("- **By probability bucket:**")
    for bucket in list(PROB_BUCKETS.keys()) + ["unknown"]:
        if bucket_counts.get(bucket):
            lines.append(f"  - `{bucket}`: {bucket_counts[bucket]}")
    lines.append("")
    lines.append("- **By Kalshi series category:**")
    for cat, n in category_counts.most_common():
        lines.append(f"  - `{cat}`: {n}")
    lines.append("")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    print("=== D.1 candidate discovery ===")
    started_at = datetime.now(timezone.utc)
    now = started_at

    # --- Step 1: Kalshi series ---
    print("\nStep 1: enumerating Kalshi series via /series ...")
    try:
        all_series = list_kalshi_series(limit=1000)
    except Exception as e:
        print(f"❌ /series fetch failed: {e}", file=sys.stderr)
        return 1
    series_index = _build_series_category_index(all_series)
    anchor_tickers = _anchor_series_tickers_from_markets_yaml()
    if anchor_tickers:
        print(f"  anchor series from markets.yaml: {anchor_tickers}")
    eligible_series = filter_recent_eligible_series(
        all_series,
        recency_days=KALSHI_SERIES_RECENCY_DAYS,
        max_series=KALSHI_MAX_SERIES_TO_ENUMERATE,
        anchor_tickers=anchor_tickers,
        now=now,
    )
    print(
        f"  fetched {len(all_series)} series; "
        f"{len(eligible_series)} retained after parlay filter + "
        f"recency<= {KALSHI_SERIES_RECENCY_DAYS:.0f}d + cap "
        f"({KALSHI_MAX_SERIES_TO_ENUMERATE}, plus {len(anchor_tickers)} anchors)"
    )

    # --- Step 2: per-series Kalshi market enumeration ---
    print(
        f"\nStep 2: per-series enumeration "
        f"(volume_fp >= ${MIN_KALSHI_VOLUME_USD:,.0f}, "
        f"days_to_resolution >= {MIN_DAYS_TO_RESOLUTION:.0f}) "
        f"@ {KALSHI_SERIES_SLEEP_S:.1f}s sleep/call ..."
    )
    kalshi_candidates: list[dict] = []
    failed_series: list[tuple[str, str]] = []
    pre_parlay_kept = 0
    PROGRESS_EVERY = 50
    for idx, s in enumerate(eligible_series, start=1):
        ticker = s.get("ticker")
        if not isinstance(ticker, str):
            continue
        try:
            markets = fetch_kalshi_markets_for_series(
                ticker, min_volume_usd=MIN_KALSHI_VOLUME_USD
            )
        except Exception as e:
            failed_series.append((ticker, str(e)))
            time.sleep(KALSHI_SERIES_SLEEP_S)
            continue
        pre_parlay_kept += len(markets)
        markets = [m for m in markets if not is_parlay_market(m)]
        markets = [m for m in markets if _within_resolution_window(m, now=now)]
        kalshi_candidates.extend(markets)
        if idx % PROGRESS_EVERY == 0 or idx == len(eligible_series):
            print(
                f"  [{idx}/{len(eligible_series)}] series enumerated; "
                f"kept {len(kalshi_candidates)} markets so far",
                flush=True,
            )
        time.sleep(KALSHI_SERIES_SLEEP_S)
    if failed_series:
        print(f"  ⚠ {len(failed_series)} series fetches failed (skipped):")
        for ticker, msg in failed_series[:5]:
            print(f"    - {ticker}: {msg}")
    print(
        f"  {pre_parlay_kept} markets passed USD volume floor across "
        f"{len(eligible_series)} series; {len(kalshi_candidates)} survive "
        "parlay + days-to-resolution filters"
    )

    # --- Step 3: Polymarket pool ---
    print(f"\nStep 3: pulling Polymarket active+open markets (volume >= "
          f"${MIN_POLYMARKET_VOLUME_USD:,.0f}) from {POLYMARKET_GAMMA_URL} ...")
    try:
        poly_raw = fetch_polymarket_active_markets()
    except Exception as e:
        print(f"❌ Polymarket pool fetch failed: {e}", file=sys.stderr)
        return 1
    poly_pool = [
        m for m in poly_raw if polymarket_volume_usd(m) >= MIN_POLYMARKET_VOLUME_USD
    ]
    print(f"  {len(poly_raw)} markets fetched; {len(poly_pool)} pass volume floor")

    # --- Step 4: matching ---
    print("\nStep 4: matching each Kalshi candidate to its best Polymarket peer ...")
    rows: list[dict] = []
    for k in kalshi_candidates:
        event = kalshi_event_text(k)
        close_dt = parse_iso_dt(k.get("close_time")) or parse_iso_dt(
            k.get("expected_expiration_time")
        )
        match, score = _best_match(event, close_dt, poly_pool)
        prob = kalshi_yes_probability(k)
        bucket = assign_prob_bucket(prob)
        kalshi_vol = kalshi_volume_usd(k)
        poly_vol = polymarket_volume_usd(match) if match else 0.0
        days = days_until(close_dt, now=now) or 0.0

        notes_parts: list[str] = []
        if score < 0.5:
            notes_parts.append("uncertain")
        if (kalshi_vol + poly_vol) < MIN_COMBINED_OI_USD:
            notes_parts.append("below combined-OI floor")

        rows.append({
            "kalshi_ticker": k.get("ticker", ""),
            "kalshi_event": event,
            "kalshi_category": _kalshi_market_category(k, series_index),
            "polymarket_question": (match or {}).get("question", "") if match else "",
            "polymarket_condition_id": (match or {}).get("conditionId")
                or (match or {}).get("condition_id"),
            "polymarket_clob_token_ids_raw": (match or {}).get("clobTokenIds"),
            "kalshi_vol": kalshi_vol,
            "poly_vol": poly_vol,
            "prob_bucket": bucket,
            "days_to_resolution": days,
            "match_score": score,
            "notes": ", ".join(notes_parts),
            "polymarket_404": False,
        })

    rows.sort(key=lambda r: r["match_score"], reverse=True)

    # --- Step 5: per-pair validation (top-N orderbook fetches) ---
    print(f"\nStep 5: validating top {ORDERBOOK_VALIDATE_TOP_N} matches with score "
          f">= {ORDERBOOK_VALIDATE_MIN_SCORE} ...")
    validated = 0
    for r in rows:
        if r["match_score"] < ORDERBOOK_VALIDATE_MIN_SCORE:
            break  # rows are score-desc, so we can stop here
        if validated >= ORDERBOOK_VALIDATE_TOP_N:
            break
        if not r["polymarket_condition_id"]:
            r["notes"] = (r["notes"] + ", " if r["notes"] else "") + "no condition_id"
            continue
        yes_tid, no_tid = parse_clob_token_ids(r["polymarket_clob_token_ids_raw"])
        v = validate_polymarket_ids(r["polymarket_condition_id"], yes_tid, no_tid)
        if not v.ok:
            r["notes"] = (r["notes"] + ", " if r["notes"] else "") + "id_validation:" + "; ".join(v.errors)
            r["match_score"] = 0.0
            continue

        # Single orderbook fetch (YES) — primary signal that the pair is live.
        try:
            polymarket.get_orderbook(yes_tid)
        except Exception as e:
            r["polymarket_404"] = True
            r["match_score"] = 0.0
            r["notes"] = (r["notes"] + ", " if r["notes"] else "") + f"POLYMARKET_404 ({e.__class__.__name__})"
        validated += 1
        time.sleep(ORDERBOOK_FETCH_SLEEP_S)
    print(f"  validated {validated} match(es) with live orderbook fetch")

    # Re-sort after potential score-zeroing.
    rows.sort(key=lambda r: r["match_score"], reverse=True)

    # --- Step 6: write markdown ---
    print(f"\nStep 6: writing {OUT_PATH} ...")
    _write_markdown(
        rows=rows,
        series_count=len(all_series),
        eligible_series_count=len(eligible_series),
        kalshi_market_count=len(kalshi_candidates),
        poly_pool_count=len(poly_pool),
        generated_at=started_at,
    )

    # --- Console summary ---
    bucket_counts = Counter(r["prob_bucket"] or "unknown" for r in rows)
    print("\n=== summary ===")
    print(f"  total candidates : {len(rows)}")
    print(f"  high-confidence  : {sum(1 for r in rows if r['match_score'] >= 0.5)}")
    print(f"  POLYMARKET_404   : {sum(1 for r in rows if r['polymarket_404'])}")
    print(f"  by bucket        : "
          + ", ".join(f"{b}={bucket_counts[b]}" for b in list(PROB_BUCKETS.keys()) + ["unknown"] if bucket_counts.get(b)))
    print(f"  output           : {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
