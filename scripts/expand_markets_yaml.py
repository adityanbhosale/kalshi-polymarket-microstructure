"""D.2: expand markets.yaml from 3 to 16 entries.

Inputs are the locked picks list from the D.2 spec. For each ticker (13 new
picks plus the 3 existing entries), this script:

 1. Fetches the live Kalshi market record (``/markets/{ticker}``) for
    title, volume_fp, close_time, yes_bid_dollars, yes_ask_dollars.
 2. Looks up the best Polymarket match against a single paginated Gamma
    pool, using the same scoring helper that powers ``discover_markets.py``
    (rapidfuzz token-set ratio + 14-day date proximity).
 3. Validates the matched Polymarket condition_id and both token_ids via
    the loosened rule (``76 ≤ len ≤ 78`` and ``isdigit()``) — see
    ``pm_micro.discovery.validate_polymarket_ids``.
 4. Probes both Polymarket orderbooks; on 404 we attach the
    ``*_token_orderbook_status: "404_delisted"`` marker so the validator
    will tolerate the missing book.

Two algorithmic picks are resolved at runtime:
 * LA Mayor (``KXMAYORLA-26-*``): pick the candidate with the **highest**
   Kalshi mid-price and the candidate with the **lowest** Kalshi mid-price.
   Tie-breaks: combined cross-venue volume desc, then ticker alphabetical.
 * Cultural / M&A (``KXTAKEOVERACQWB-27JUN30-{PSKY,NFLX}``): pick the
   ticker with the higher combined cross-venue volume.

The two picks' rationale is recorded both in the ``notes`` field of the
selected entry and in the file-level header comment.

Existing OKC/CLE/NYK entries are preserved with their original
``condition_id``, ``token_ids``, ``category``, ``description``,
``volume_at_curation`` (kalshi + polymarket), and ``match_notes``. The four
schema-addition fields (``prob_bucket``, ``resolution_date``, ``notes``,
plus per-token ``*_token_orderbook_status`` markers where applicable) are
appended.

No edits to ``src/pm_micro/`` per D.2 guardrail; this script lives in
``scripts/`` and only imports from ``pm_micro.discovery`` /
``pm_micro.clients``.

Usage:
    uv run python scripts/expand_markets_yaml.py
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pm_micro.clients import kalshi, polymarket
from pm_micro.discovery import (
    MIN_POLYMARKET_VOLUME_USD,
    assign_prob_bucket,
    fetch_polymarket_active_markets,
    kalshi_event_text,
    kalshi_volume_usd,
    kalshi_yes_probability,
    parse_clob_token_ids,
    parse_iso_dt,
    polymarket_volume_usd,
    score_match,
    validate_polymarket_ids,
)

REPO_ROOT = Path(__file__).parent.parent
MARKETS_YAML = REPO_ROOT / "markets.yaml"

# --- Locked picks (per D.2 spec) ---------------------------------------
PICKS_DIRECT: list[str] = [
    "KXNBA-26-SAS",
    "KXARODGRETIRE-26",
    "KXKELCERETIRE-26",
    "KXAKSENATE-26NOV03-MPEL",
    "KXCOLOMBIAPRES-26-AESP",
    "KXCOLOMBIAPRES-26-PVAL",
    "KXPERUPRES-26-KFUJ",
    "KXPERUPRES-26-RPAL",
    "KXCOLOMBIAPRESR1-26MAY31-ICAS",
    "KXSEOULMAYOR-26JUN03-OSEH",
]
LAMAYOR_CANDIDATES: list[str] = [
    "KXMAYORLA-26-SPRA",
    "KXMAYORLA-26-KBAS",
    "KXMAYORLA-26-AMIL",
    "KXMAYORLA-26-RHUA",
    "KXMAYORLA-26-RCAR",
    "KXMAYORLA-26-NRAM",
]
CULTURAL_CANDIDATES: list[str] = [
    "KXTAKEOVERACQWB-27JUN30-PSKY",
    "KXTAKEOVERACQWB-27JUN30-NFLX",
]

EXISTING_TICKERS: list[str] = [
    "KXNBA-26-OKC",
    "KXNBA-26-CLE",
    "KXNBA-26-NYK",
]

# Per-pick must-contain name filter applied to the Polymarket pool before
# matching. token_set_ratio alone gets fooled when a low-volume Polymarket
# question shares more generic tokens (e.g., "2026", "Senate", "race") with
# the Kalshi event than the actual same-event Polymarket counterpart does;
# requiring the entity name shared by the Kalshi pick (player, candidate,
# corporate acquirer) eliminates that failure mode without re-tuning the
# scorer. Case-insensitive substring match against ``question``.
PER_TICKER_NAME_FILTER: dict[str, tuple[str, ...]] = {
    "KXNBA-26-SAS":                   ("Spurs", "San Antonio"),
    "KXARODGRETIRE-26":               ("Rodgers",),
    "KXKELCERETIRE-26":               ("Kelce",),
    "KXAKSENATE-26NOV03-MPEL":        ("Peltola",),
    "KXCOLOMBIAPRES-26-AESP":         ("Espriella",),
    "KXCOLOMBIAPRES-26-PVAL":         ("Valencia",),
    "KXPERUPRES-26-KFUJ":             ("Fujimori",),
    "KXPERUPRES-26-RPAL":             ("Sánchez Palomino", "Palomino"),
    "KXCOLOMBIAPRESR1-26MAY31-ICAS":  ("Cepeda",),
    "KXSEOULMAYOR-26JUN03-OSEH":      ("Oh Se-hoon", "Se-hoon"),
    "KXMAYORLA-26-SPRA":              ("Spencer Pratt",),
    "KXMAYORLA-26-KBAS":              ("Karen Bass",),
    "KXMAYORLA-26-AMIL":              ("Adam Miller",),
    "KXMAYORLA-26-RHUA":              ("Rae Huang",),
    "KXMAYORLA-26-RCAR":              ("Rick Caruso",),
    "KXMAYORLA-26-NRAM":              ("Nithya Raman",),
    "KXTAKEOVERACQWB-27JUN30-PSKY":   ("Paramount",),
    "KXTAKEOVERACQWB-27JUN30-NFLX":   ("Netflix",),
}

# --- Per-ticker category and id-builder --------------------------------
CATEGORY_BY_TICKER: dict[str, str] = {
    "KXNBA-26-SAS": "nba_finals",
    "KXARODGRETIRE-26": "sports_retirement",
    "KXKELCERETIRE-26": "sports_retirement",
    "KXAKSENATE-26NOV03-MPEL": "us_senate",
    "KXCOLOMBIAPRES-26-AESP": "intl_president",
    "KXCOLOMBIAPRES-26-PVAL": "intl_president",
    "KXPERUPRES-26-KFUJ": "intl_president",
    "KXPERUPRES-26-RPAL": "intl_president",
    "KXCOLOMBIAPRESR1-26MAY31-ICAS": "intl_president_round1",
    "KXSEOULMAYOR-26JUN03-OSEH": "intl_mayor",
    # LA Mayor and Cultural categories filled in after pick resolution.
}

# Required delisted markers on existing entries (per D.2 spec).
EXISTING_DELISTED_MARKERS: dict[str, dict[str, str]] = {
    "nba_finals_cle": {
        "yes_token_orderbook_status": "404_delisted",
        "no_token_orderbook_status": "404_delisted",
    },
    "nba_finals_nyk": {
        "no_token_orderbook_status": "404_delisted",
    },
}

KALSHI_FETCH_SLEEP_S = 0.5
POLYMARKET_ORDERBOOK_SLEEP_S = 0.5


# --- Helpers -----------------------------------------------------------
def _make_id(ticker: str, category: str) -> str:
    """Mint a snake-case yaml id keyed on ticker shape + category."""
    tail = ticker.split("-")[-1].lower()
    if ticker.startswith("KXCOLOMBIAPRESR1"):
        return f"intl_president_r1_co_{tail}"
    if ticker.startswith("KXCOLOMBIAPRES"):
        return f"intl_president_co_{tail}"
    if ticker.startswith("KXPERUPRES"):
        return f"intl_president_pe_{tail}"
    if ticker.startswith("KXSEOULMAYOR"):
        return f"intl_mayor_kr_{tail}"
    if ticker.startswith("KXAKSENATE"):
        return f"us_senate_ak_{tail}"
    if ticker.startswith("KXMAYORLA"):
        return f"us_mayor_la_{tail}"
    if ticker.startswith("KXTAKEOVERACQWB"):
        return f"ma_acquisition_wb_{tail}"
    if ticker.startswith("KXNBA"):
        return f"nba_finals_{tail}"
    if ticker == "KXARODGRETIRE-26":
        return "sports_retirement_arod"
    if ticker == "KXKELCERETIRE-26":
        return "sports_retirement_kelce"
    return f"{category}_{tail}"


def _kalshi_mid_dollars(market: dict) -> float | None:
    """Mean of yes_bid_dollars + yes_ask_dollars when both present."""
    bid = market.get("yes_bid_dollars")
    ask = market.get("yes_ask_dollars")
    try:
        b = float(bid)
        a = float(ask)
    except (TypeError, ValueError):
        return None
    if b == 0.0 and a == 1.0:
        # Degenerate book (e.g., finalized/illiquid) — return None so caller
        # can fall back to last_price_dollars or skip mid-based ranking.
        return None
    return (b + a) / 2.0


def _kalshi_resolution_date(market: dict) -> str | None:
    """Best-effort ISO date (YYYY-MM-DD) for the Kalshi resolution time."""
    # Prefer expected_expiration_time: close_time/expiration_time on active
    # markets is often a year-offset contract ceiling (2027/2028), not the
    # actual event date. expected_expiration_time carries the real catalyst.
    dt = parse_iso_dt(
        market.get("expected_expiration_time") or market.get("close_time")
    )
    if dt is None:
        return None
    return dt.date().isoformat()


def _check_orderbook_status(token_id: str) -> str:
    """Return ``"active"`` or ``"404_delisted"`` for a Polymarket token id.

    Any non-404 exception propagates per the D.2 ``no auto-retry`` rule.
    """
    try:
        polymarket.get_orderbook(token_id)
    except Exception as e:
        msg = str(e).lower()
        if "404" in msg or "no orderbook" in msg:
            return "404_delisted"
        raise
    return "active"


def _fetch_kalshi(ticker: str) -> dict:
    resp = kalshi.get_market(ticker)
    if isinstance(resp, dict) and "market" in resp:
        return resp["market"]
    return resp  # already a market dict


def _best_polymarket_match(
    kalshi_event: str,
    kalshi_close_dt: datetime | None,
    pool: list[dict],
    name_filter: tuple[str, ...] | None = None,
) -> tuple[dict | None, float]:
    """Find the highest-scoring Polymarket question against ``kalshi_event``.

    When ``name_filter`` is provided, only Polymarket questions whose text
    contains at least one of those substrings (case-insensitive) are
    considered. This is the override that prevents the scorer from picking
    e.g. "Joe Flacco starts Week 1" over "Aaron Rodgers retires" merely
    because more generic tokens overlap.
    """
    best_score = 0.0
    best: dict | None = None
    needles = tuple(n.lower() for n in (name_filter or ()))
    for pm in pool:
        question = pm.get("question") or ""
        if not question:
            continue
        if needles and not any(n in question.lower() for n in needles):
            continue
        end_dt = parse_iso_dt(
            pm.get("endDate") or pm.get("end_date_iso") or pm.get("endDateIso")
        )
        s = score_match(kalshi_event, question, kalshi_close_dt, end_dt)
        if s > best_score:
            best_score = s
            best = pm
    return best, best_score


def _kalshi_combined_with_match(
    ticker: str, fetched: dict[str, dict], poly_pool_volumes: dict[str, float]
) -> float:
    km = fetched[ticker]["kalshi"]
    match = fetched[ticker]["polymarket_match"]
    kvol = kalshi_volume_usd(km)
    pvol = polymarket_volume_usd(match) if match else 0.0
    return kvol + pvol


# --- Entry construction ------------------------------------------------
def _build_entry(
    ticker: str,
    fetched_record: dict,
    category: str,
    notes: str | None = None,
    extra_match_notes: str = "",
) -> dict:
    km = fetched_record["kalshi"]
    pm = fetched_record["polymarket_match"]
    score = fetched_record["polymarket_score"]
    yes_status = fetched_record.get("yes_orderbook_status", "active")
    no_status = fetched_record.get("no_orderbook_status", "active")

    cid = pm.get("conditionId") or pm.get("condition_id")
    yes_tid, no_tid = parse_clob_token_ids(pm.get("clobTokenIds"))

    poly_block: dict = {
        "condition_id": cid,
        "yes_token_id": yes_tid,
        "no_token_id": no_tid,
        "volume_at_curation": int(round(polymarket_volume_usd(pm))),
    }
    if yes_status != "active":
        poly_block["yes_token_orderbook_status"] = yes_status
    if no_status != "active":
        poly_block["no_token_orderbook_status"] = no_status

    prob = kalshi_yes_probability(km)
    bucket = assign_prob_bucket(prob) or "tail_low"

    title = (km.get("title") or "").strip()
    sub = (km.get("yes_sub_title") or "").strip()
    description = title if not sub or sub.lower() == title.lower() else f"{title} — {sub}"

    match_summary = (
        f"D.1 discovery match (score={score:.3f}): "
        f"Kalshi '{title}' ↔ Polymarket '{(pm.get('question') or '').strip()}'."
    )
    if extra_match_notes:
        match_summary = f"{match_summary} {extra_match_notes}"

    entry = {
        "id": _make_id(ticker, category),
        "category": category,
        "description": description,
        "kalshi": {
            "ticker": ticker,
            "volume_at_curation": int(round(kalshi_volume_usd(km))),
        },
        "polymarket": poly_block,
        "prob_bucket": bucket,
        "resolution_date": _kalshi_resolution_date(km),
        "match_notes": match_summary,
    }
    if notes:
        entry["notes"] = notes
    return entry


# --- YAML rendering ----------------------------------------------------
HEADER = """\
# Cross-venue prediction-market pairings for microstructure analysis.
#
# D.2 expansion (2026-05-27/28): grew from 3 NBA Finals entries to 16 by
# adding 13 picks across sports, US/intl politics, and corporate M&A. Two
# of the picks are algorithmic — see the per-entry `notes` field on
# us_mayor_la_* and ma_acquisition_wb_* for the selection metric.
#
# Existing OKC/CLE/NYK entries were preserved (`condition_id`, `token_ids`,
# `category`, `description`, `match_notes` unchanged). Schema additions
# (`prob_bucket`, `resolution_date`, `notes`) and the
# `*_token_orderbook_status: "404_delisted"` markers required to satisfy
# `validate_markets_yaml.py` were appended.
#
# Generated by scripts/expand_markets_yaml.py on {ts}.
"""


def render_yaml(entries: list[dict], generated_at: datetime) -> str:
    body = yaml.safe_dump(
        entries, sort_keys=False, default_flow_style=False, allow_unicode=True
    )
    return HEADER.format(ts=generated_at.strftime("%Y-%m-%d %H:%M:%SZ")) + "\n" + body


# --- Main --------------------------------------------------------------
def main() -> int:
    started = datetime.now(timezone.utc)
    print(f"=== D.2 markets.yaml expansion ({started.isoformat()}) ===")

    if not MARKETS_YAML.exists():
        print(f"❌ {MARKETS_YAML} not found", file=sys.stderr)
        return 1
    raw_yaml = yaml.safe_load(MARKETS_YAML.read_text()) or []
    # Only the original 3 NBA Finals entries are treated as "existing" and
    # rewritten with schema additions + delisted markers. Anything else in
    # the file (e.g., the 13 picks from a prior run of this script) is
    # discarded so the script is idempotent on re-runs.
    existing_yaml = [
        entry for entry in raw_yaml
        if entry.get("kalshi", {}).get("ticker") in EXISTING_TICKERS
    ]
    if len(existing_yaml) != len(EXISTING_TICKERS):
        print(
            f"❌ expected {len(EXISTING_TICKERS)} existing entries "
            f"({EXISTING_TICKERS}); found {len(existing_yaml)}",
            file=sys.stderr,
        )
        return 1
    print(
        f"  loaded {len(raw_yaml)} entries from markets.yaml; "
        f"{len(existing_yaml)} preserved as 'existing'"
    )

    all_kalshi_tickers = (
        PICKS_DIRECT + LAMAYOR_CANDIDATES + CULTURAL_CANDIDATES + EXISTING_TICKERS
    )

    print(f"\nStep 1: pulling Polymarket active+open pool ...")
    poly_pool_raw = fetch_polymarket_active_markets()
    # Mirror the discovery-time volume floor so the matcher operates on the
    # same universe that produced D.1's match scores; below-threshold markets
    # are otherwise free to outrank the correct same-event match on shared
    # generic tokens.
    poly_pool = [
        m for m in poly_pool_raw
        if polymarket_volume_usd(m) >= MIN_POLYMARKET_VOLUME_USD
    ]
    print(
        f"  raw pool size: {len(poly_pool_raw)}; "
        f"after volume>=${MIN_POLYMARKET_VOLUME_USD:,.0f}: {len(poly_pool)}"
    )

    print(f"\nStep 2: fetching {len(all_kalshi_tickers)} Kalshi markets ...")
    fetched: dict[str, dict] = {}
    for tk in all_kalshi_tickers:
        try:
            km = _fetch_kalshi(tk)
        except Exception as e:
            print(f"❌ kalshi.get_market({tk!r}) failed: {e}", file=sys.stderr)
            return 1
        name_filter = PER_TICKER_NAME_FILTER.get(tk)
        match, score = _best_polymarket_match(
            kalshi_event_text(km),
            parse_iso_dt(km.get("close_time")),
            poly_pool,
            name_filter=name_filter,
        )
        fetched[tk] = {
            "kalshi": km,
            "polymarket_match": match,
            "polymarket_score": score,
        }
        match_q = (match or {}).get("question") if match else None
        print(
            f"  {tk:<35}  kvol_fp=${kalshi_volume_usd(km):>13,.0f}  "
            f"poly_score={score:.3f}  poly_q={(match_q or '<no match>')[:50]}"
        )
        time.sleep(KALSHI_FETCH_SLEEP_S)

    # --- Step 3: resolve algorithmic picks ---
    print(f"\nStep 3: resolving algorithmic picks ...")

    # LA Mayor — highest and lowest mid; tie-break: combined volume desc, ticker asc.
    la_rows: list[dict] = []
    for tk in LAMAYOR_CANDIDATES:
        rec = fetched[tk]
        km = rec["kalshi"]
        match = rec["polymarket_match"]
        mid = _kalshi_mid_dollars(km)
        kvol = kalshi_volume_usd(km)
        pvol = polymarket_volume_usd(match) if match else 0.0
        la_rows.append({
            "ticker": tk,
            "mid": mid,
            "combined_vol_usd": kvol + pvol,
        })
        print(
            f"  LA {tk:<25} mid={mid if mid is not None else 'n/a':>5}"
            f"  combined=${(kvol + pvol):>12,.0f}"
        )

    # Filter to rows where mid is computable; degenerate books are excluded
    # from ranking but reported.
    la_ranked = [r for r in la_rows if r["mid"] is not None]
    if len(la_ranked) < 2:
        print(
            f"❌ fewer than 2 LA Mayor candidates have computable mids "
            f"({len(la_ranked)} of {len(la_rows)}); cannot resolve picks",
            file=sys.stderr,
        )
        return 1

    la_high = sorted(
        la_ranked, key=lambda r: (-r["mid"], -r["combined_vol_usd"], r["ticker"])
    )[0]
    la_low = sorted(
        la_ranked, key=lambda r: (r["mid"], -r["combined_vol_usd"], r["ticker"])
    )[0]
    if la_high["ticker"] == la_low["ticker"]:
        print(
            "❌ LA Mayor highest and lowest resolved to the same ticker — "
            "every candidate has the same mid",
            file=sys.stderr,
        )
        return 1
    print(f"  → LA HIGH pick: {la_high['ticker']} (mid={la_high['mid']:.4f})")
    print(f"  → LA LOW  pick: {la_low['ticker']}  (mid={la_low['mid']:.4f})")

    # Cultural — higher combined cross-venue volume.
    cul_rows = []
    for tk in CULTURAL_CANDIDATES:
        rec = fetched[tk]
        km = rec["kalshi"]
        match = rec["polymarket_match"]
        kvol = kalshi_volume_usd(km)
        pvol = polymarket_volume_usd(match) if match else 0.0
        cul_rows.append({"ticker": tk, "combined_vol_usd": kvol + pvol})
        print(f"  CUL {tk:<35} combined=${kvol + pvol:>12,.0f}")
    cul_pick = sorted(cul_rows, key=lambda r: (-r["combined_vol_usd"], r["ticker"]))[0]
    print(f"  → Cultural pick: {cul_pick['ticker']} "
          f"(combined=${cul_pick['combined_vol_usd']:,.0f})")

    final_picks = list(PICKS_DIRECT) + [la_high["ticker"], la_low["ticker"], cul_pick["ticker"]]

    # --- Step 4: validate IDs + check orderbook for new picks ---
    print(f"\nStep 4: validating new picks (IDs + both orderbooks) ...")
    for tk in final_picks:
        rec = fetched[tk]
        match = rec["polymarket_match"]
        if match is None:
            print(f"❌ {tk}: no Polymarket match", file=sys.stderr)
            return 1
        cid = match.get("conditionId") or match.get("condition_id")
        yes_tid, no_tid = parse_clob_token_ids(match.get("clobTokenIds"))
        v = validate_polymarket_ids(cid, yes_tid, no_tid)
        if not v.ok:
            print(f"❌ {tk}: id validation failed: {v.errors}", file=sys.stderr)
            return 1

        try:
            yes_status = _check_orderbook_status(yes_tid)
            time.sleep(POLYMARKET_ORDERBOOK_SLEEP_S)
            no_status = _check_orderbook_status(no_tid)
            time.sleep(POLYMARKET_ORDERBOOK_SLEEP_S)
        except Exception as e:
            print(f"❌ {tk}: orderbook check failed (non-404): {e}", file=sys.stderr)
            return 1
        rec["yes_orderbook_status"] = yes_status
        rec["no_orderbook_status"] = no_status
        flag = ""
        if yes_status != "active" or no_status != "active":
            flag = f"  [yes={yes_status}, no={no_status}]"
        print(f"  ✓ {tk:<35}  cid_len={len(cid)} yes_len={len(yes_tid)} "
              f"no_len={len(no_tid)}{flag}")

    # --- Step 5: assemble new entries ---
    print(f"\nStep 5: assembling new entries ...")
    new_entries: list[dict] = []

    for tk in PICKS_DIRECT:
        cat = CATEGORY_BY_TICKER[tk]
        new_entries.append(_build_entry(tk, fetched[tk], cat))

    high_note = (
        f"Algorithmic D.2 pick: HIGHEST current Kalshi mid "
        f"({la_high['mid']:.4f}) among 6 LA Mayor candidates "
        f"({', '.join(LAMAYOR_CANDIDATES)}). Tie-break: combined volume desc, "
        f"ticker alphabetical."
    )
    low_note = (
        f"Algorithmic D.2 pick: LOWEST current Kalshi mid "
        f"({la_low['mid']:.4f}) among 6 LA Mayor candidates "
        f"({', '.join(LAMAYOR_CANDIDATES)}). Tie-break: combined volume desc, "
        f"ticker alphabetical."
    )
    new_entries.append(_build_entry(la_high["ticker"], fetched[la_high["ticker"]],
                                    "us_mayor", notes=high_note))
    new_entries.append(_build_entry(la_low["ticker"], fetched[la_low["ticker"]],
                                    "us_mayor", notes=low_note))

    cul_note = (
        f"Algorithmic D.2 pick: HIGHER combined cross-venue volume "
        f"(${cul_pick['combined_vol_usd']:,.0f}) of "
        f"{{{', '.join(CULTURAL_CANDIDATES)}}}."
    )
    new_entries.append(_build_entry(cul_pick["ticker"], fetched[cul_pick["ticker"]],
                                    "ma_acquisition", notes=cul_note))

    # --- Step 6: update existing entries ---
    print(f"\nStep 6: appending schema additions + delisted markers to "
          f"existing entries ...")
    updated_existing: list[dict] = []
    for entry in existing_yaml:
        ticker = entry["kalshi"]["ticker"]
        rec = fetched.get(ticker)
        # Compute prob_bucket / resolution_date from the live Kalshi record.
        bucket: str | None = None
        res_date: str | None = None
        if rec is not None:
            prob = kalshi_yes_probability(rec["kalshi"])
            bucket = assign_prob_bucket(prob)
            res_date = _kalshi_resolution_date(rec["kalshi"])

        # Rebuild in canonical key order while preserving values byte-for-byte
        # for fields the spec says we must not touch.
        new_entry: dict = {
            "id": entry["id"],
            "category": entry["category"],
            "description": entry["description"],
            "kalshi": dict(entry["kalshi"]),
            "polymarket": dict(entry["polymarket"]),
        }
        # Apply delisted markers if required for this id.
        markers = EXISTING_DELISTED_MARKERS.get(entry["id"], {})
        for k, v in markers.items():
            new_entry["polymarket"][k] = v

        new_entry["prob_bucket"] = bucket or entry.get("prob_bucket") or "tail_low"
        new_entry["resolution_date"] = res_date or entry.get("resolution_date")
        if entry.get("notes"):
            new_entry["notes"] = entry["notes"]
        if entry.get("match_notes"):
            new_entry["match_notes"] = entry["match_notes"]
        updated_existing.append(new_entry)
        marker_str = ", ".join(f"{k}={v}" for k, v in markers.items()) or "(none)"
        print(
            f"  {entry['id']:<20}  bucket={new_entry['prob_bucket']:<10}  "
            f"res={new_entry['resolution_date']}  delisted_markers={marker_str}"
        )

    # --- Step 7: combine and write ---
    all_entries = updated_existing + new_entries
    rendered = render_yaml(all_entries, started)
    MARKETS_YAML.write_text(rendered, encoding="utf-8")
    print(f"\nWrote {MARKETS_YAML} with {len(all_entries)} entries "
          f"({len(updated_existing)} existing + {len(new_entries)} new).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
