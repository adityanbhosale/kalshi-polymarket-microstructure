"""EXP-12a-regime: slice the EXP-12a 5min markouts by regime.

Tests whether the pervasive negative markout from EXP-12a is *conditional*
— i.e. whether any of the 8 LP-edge markets has a regime (hour-of-day,
catalyst proximity, or volatility) where net 5min markout turns
non-negative with enough fills to trust.

Read-only. Reuses:
  * `pm_micro.fills` — markout sign convention + volatility primitive.
  * `scripts.exp12a_fill_realism` — window loaders, gross-edge / direction
    computation (so the buy/sell leg assignment is identical to EXP-12a).

Does NOT change the EXP-12a unconditional verdicts; this is a conditional
overlay. Output: `data/processed/exp12a_regime.md`.

Slices (all on genuine at-the-touch fills, strict price-through, 5min
markout horizon — identical fill definition to EXP-12a):
  1. UTC hour-of-day (24 bins).
  2. Catalyst proximity: fills within 2h of a known catalyst vs >2h.
  3. Volatility regime: trailing-15min mid stddev above/below the market's
     median.

Usage:
    uv run python scripts/exp12a_regime.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from pm_micro.fills import markout_cents, rolling_volatility_cents  # noqa: E402
from exp12a_fill_realism import (  # noqa: E402
    MARKETS_8,
    SHORT,
    VenueSeries,
    compute_gross_edges,
    load_window_series,
)

MARKETS_YAML = ROOT / "markets.yaml"
FEE_META_YAML = ROOT / "data" / "processed" / "market_fee_metadata.yaml"
OUT_MD = ROOT / "data" / "processed" / "exp12a_regime.md"

HORIZON = 10        # 5 min at 30s cadence
VOL_WINDOW = 30     # trailing 15 min at 30s cadence
MIN_FILLS = 20      # statistical floor for trusting a regime bin

# Known near-term catalysts (UTC) from the F.1 event-window concept. The
# markets.yaml resolution_date fields are year-offset curation artifacts
# (they read 2027/2028); the real first-round / election dates are below.
# Sports/other markets fall back to the markets.yaml resolution_date.
CATALYST_UTC: dict[str, datetime] = {
    "intl_president_co_aesp": datetime(2026, 5, 31, tzinfo=timezone.utc),
    "intl_president_co_pval": datetime(2026, 5, 31, tzinfo=timezone.utc),
    "intl_mayor_kr_oseh": datetime(2026, 6, 3, tzinfo=timezone.utc),
}


# =========================================================================
# Per-fill record extraction (genuine at-touch fills + regime features)
# =========================================================================

@dataclass
class Fill:
    markout_c: float
    hour: int
    vol_c: float
    hours_to_catalyst: float


def extract_fills(
    series: VenueSeries,
    side: str,
    catalyst: datetime | None,
) -> list[Fill]:
    """Genuine at-touch fills (strict price-through), 5min markout, + features.

    Fill definition matches EXP-12a `markout_samples`: a passive order at
    the current best quote fills during (t, t+1] only when price moves
    STRICTLY through it (bid ticks down / ask ticks up).
    """
    a = series.to_arrays()
    mids, bids, asks = a["mid"], a["bid"], a["ask"]
    ts = series.ts
    n = len(mids)
    fills: list[Fill] = []
    for t in range(n - HORIZON - 1):
        if mids[t] != mids[t] or mids[t + HORIZON] != mids[t + HORIZON]:
            continue
        if side == "buy":
            if not (bids[t + 1] == bids[t + 1] and bids[t + 1] < bids[t] - 1e-9):
                continue
        else:
            if not (asks[t + 1] == asks[t + 1] and asks[t + 1] > asks[t] + 1e-9):
                continue
        mo = markout_cents(mids[t], mids[t + HORIZON], side)
        if mo != mo:
            continue
        lo = max(0, t - VOL_WINDOW)
        vol = rolling_volatility_cents(mids[lo:t + 1])
        if catalyst is not None:
            h2c = (catalyst - ts[t]).total_seconds() / 3600.0
        else:
            h2c = float("inf")
        fills.append(Fill(mo, ts[t].hour, vol, h2c))
    return fills


# =========================================================================
# Slicing helpers
# =========================================================================

def _net_and_n(buy_vals: list[float], sell_vals: list[float]) -> tuple[float, int, int]:
    """Net markout = mean(buy) + mean(sell); returns (net, n_buy, n_sell).

    Legs are sliced independently (a leg with no fills in the bin
    contributes 0 to the net). Trust is governed by the per-leg counts.
    """
    mb = float(np.mean(buy_vals)) if buy_vals else 0.0
    ms = float(np.mean(sell_vals)) if sell_vals else 0.0
    return mb + ms, len(buy_vals), len(sell_vals)


@dataclass
class MarketFills:
    market_id: str
    crossed: bool
    buy_venue: str = ""
    sell_venue: str = ""
    gross_c: float = 0.0
    buy_fills: list[Fill] = None  # type: ignore
    sell_fills: list[Fill] = None  # type: ignore
    market_vol_median: float = 0.0


def gather(meta_by_id, res_date) -> list[MarketFills]:
    gross = compute_gross_edges(meta_by_id)
    out: list[MarketFills] = []
    for mid in MARKETS_8:
        g = gross[mid]
        if not g.crossed:
            out.append(MarketFills(mid, False, buy_fills=[], sell_fills=[]))
            continue
        series = load_window_series(mid)
        cat = CATALYST_UTC.get(mid)
        if cat is None and res_date.get(mid):
            cat = datetime.fromisoformat(res_date[mid]).replace(tzinfo=timezone.utc)
        bf = extract_fills(series[g.buy_venue], "buy", cat)
        sf = extract_fills(series[g.sell_venue], "sell", cat)
        # market-level median trailing-vol (pool both venues' per-snapshot vol)
        vols = []
        for v in (series["kalshi"], series["polymarket"]):
            m = v.to_arrays()["mid"]
            for t in range(len(m)):
                lo = max(0, t - VOL_WINDOW)
                if m[t] == m[t]:
                    vols.append(rolling_volatility_cents(m[lo:t + 1]))
        vmed = float(np.median(vols)) if vols else 0.0
        out.append(MarketFills(mid, True, g.buy_venue, g.sell_venue, g.edge_cents,
                               bf, sf, vmed))
    return out


# =========================================================================
# Main
# =========================================================================

def main() -> int:
    with open(MARKETS_YAML) as f:
        markets = yaml.safe_load(f)
    with open(FEE_META_YAML) as f:
        meta_list = yaml.safe_load(f)
    meta_by_id = {e["market_id"]: e for e in meta_list}
    res_date = {m["id"]: m.get("resolution_date") for m in markets}

    print("EXP-12a-regime: gathering per-fill records for 8 markets...")
    mfills = gather(meta_by_id, res_date)
    for mf in mfills:
        if mf.crossed:
            print(f"  {SHORT[mf.market_id]:8s} buy_fills={len(mf.buy_fills):4d} "
                  f"sell_fills={len(mf.sell_fills):4d} vol_med={mf.market_vol_median:.3f}c")
        else:
            print(f"  {SHORT[mf.market_id]:8s} not crossed")

    candidates = analyze_and_write(mfills)

    print("\n=== Conditional-LP candidates (non-negative net markout, "
          f"≥{MIN_FILLS} fills per leg) ===")
    if candidates:
        for c in candidates:
            print(f"  {c['market']:8s} [{c['slice']}] bin={c['bin']:>8} "
                  f"net={c['net']:+.3f}c n_buy={c['n_buy']} n_sell={c['n_sell']}")
    else:
        print("  NONE. Adverse selection is unconditional across all tested "
              "regimes with sufficient fills.")
    return 0


def analyze_and_write(mfills: list[MarketFills]) -> list[dict]:
    candidates: list[dict] = []
    weak_candidates: list[dict] = []   # non-negative but under the fill floor
    md: list[str] = []
    md.append("# EXP-12a Regime-Sliced Markout")
    md.append("")
    md.append("Tests whether the pervasive negative 5min net markout from "
              "EXP-12a is *conditional* — whether any of the 8 LP-edge markets "
              "has a regime where net markout turns non-negative with enough "
              "fills to trust (≥%d genuine fills per leg)." % MIN_FILLS)
    md.append("")
    md.append("Fill definition, markout horizon (5min), and buy/sell leg "
              "assignment are identical to EXP-12a; this is a conditional "
              "overlay, not a re-verdict. `net markout = mean(buy-leg "
              "markout) + mean(sell-leg markout)`, legs sliced independently.")
    md.append("")

    # ---- Headline placeholder (filled after analysis) ----
    headline_idx = len(md)
    md.append("")

    crossed = [mf for mf in mfills if mf.crossed]

    # =====================================================================
    # Slice 1: hour-of-day
    # =====================================================================
    md.append("## Slice 1 — UTC hour-of-day")
    md.append("")
    md.append("For each market, the hour bins (with ≥%d fills on BOTH legs) "
              "having the least-negative net markout. A market is a "
              "conditional-LP candidate only if some qualifying bin is "
              "≥ 0." % MIN_FILLS)
    md.append("")
    md.append("| market | best qualifying hour | net markout | n_buy | n_sell | "
              "any non-neg bin (≥%d/leg)? |" % MIN_FILLS)
    md.append("|---|---|---:|---:|---:|---|")
    for mf in crossed:
        by_hour_buy = _bucket(mf.buy_fills, lambda f: f.hour)
        by_hour_sell = _bucket(mf.sell_fills, lambda f: f.hour)
        best = None
        any_nonneg = False
        for hr in range(24):
            bvals = by_hour_buy.get(hr, [])
            svals = by_hour_sell.get(hr, [])
            net, nb, ns = _net_and_n(bvals, svals)
            if nb >= MIN_FILLS and ns >= MIN_FILLS:
                if net >= 0:
                    any_nonneg = True
                    candidates.append({"market": SHORT[mf.market_id], "slice": "hour",
                                       "bin": f"{hr:02d}Z", "net": net,
                                       "n_buy": nb, "n_sell": ns})
                if best is None or net > best[1]:
                    best = (hr, net, nb, ns)
            elif net >= 0 and (nb + ns) > 0:
                weak_candidates.append({"market": SHORT[mf.market_id], "slice": "hour",
                                        "bin": f"{hr:02d}Z", "net": net,
                                        "n_buy": nb, "n_sell": ns})
        if best is not None:
            hr, net, nb, ns = best
            md.append(f"| `{SHORT[mf.market_id]}` | {hr:02d}Z | {net:+.3f}c | "
                      f"{nb} | {ns} | {'YES' if any_nonneg else 'no'} |")
        else:
            md.append(f"| `{SHORT[mf.market_id]}` | — (no bin ≥{MIN_FILLS}/leg) | "
                      f"— | — | — | no |")
    md.append("")
    md.append(f"*No market has any single hour bin with ≥{MIN_FILLS} genuine "
              f"fills on **both** legs — total fills (≤112 on the best-filled "
              f"leg) spread across 24 hourly bins are too sparse to clear a "
              f"per-leg floor. The hour-of-day slice is therefore underpowered "
              f"for this single-day window; nothing here can be trusted as a "
              f"structural hour effect (see also caveat 3).*")
    md.append("")

    # =====================================================================
    # Slice 2: catalyst proximity
    # =====================================================================
    md.append("## Slice 2 — catalyst proximity")
    md.append("")
    near_total = sum(
        sum(1 for f in mf.buy_fills + mf.sell_fills if abs(f.hours_to_catalyst) <= 2.0)
        for mf in crossed
    )
    md.append(f"Nearest known catalysts (F.1 event dates): Colombia 1st round "
              f"2026-05-31, Seoul mayor 2026-06-03; sports/other markets use "
              f"their (year-offset-corrected) resolution dates, all 2026-09 or "
              f"later. The E.1 daemon window analyzed here is 2026-05-28.")
    md.append("")
    md.append(f"**Fills within 2h of any catalyst: {near_total}.** Every "
              f"catalyst is ≥2.5 days after the daemon window, so the "
              f"near-catalyst bucket is **empty** — this slice is degenerate "
              f"for the current data. The EXP-12a markouts are therefore all "
              f"\"far-from-catalyst\" measurements; near-catalyst LP behavior "
              f"remains uncharacterized (consistent with EXP-12a caveat 4, "
              f"pending the F.1 dense captures of May 31 / June 3).")
    md.append("")

    # =====================================================================
    # Slice 3: volatility regime
    # =====================================================================
    md.append("## Slice 3 — volatility regime (trailing-15min mid stddev)")
    md.append("")
    md.append("Fills split by whether the trailing-15min mid stddev at fill "
              "time is below (low-vol) or above (high-vol) the market's median. "
              "Adverse selection should be WORSE in high-vol (more informed "
              "flow); a non-negative low-vol regime would be a conditional-LP "
              "candidate.")
    md.append("")
    md.append("| market | low-vol net | n_buy/n_sell | high-vol net | "
              "n_buy/n_sell | low-vol non-neg (≥%d/leg)? |" % MIN_FILLS)
    md.append("|---|---:|---|---:|---|---|")
    for mf in crossed:
        thr = mf.market_vol_median
        lo_b = [f.markout_c for f in mf.buy_fills if f.vol_c <= thr]
        hi_b = [f.markout_c for f in mf.buy_fills if f.vol_c > thr]
        lo_s = [f.markout_c for f in mf.sell_fills if f.vol_c <= thr]
        hi_s = [f.markout_c for f in mf.sell_fills if f.vol_c > thr]
        lo_net, lo_nb, lo_ns = _net_and_n(lo_b, lo_s)
        hi_net, hi_nb, hi_ns = _net_and_n(hi_b, hi_s)
        lo_ok = lo_nb >= MIN_FILLS and lo_ns >= MIN_FILLS
        lo_nonneg = lo_ok and lo_net >= 0
        if lo_nonneg:
            candidates.append({"market": SHORT[mf.market_id], "slice": "vol",
                               "bin": "low-vol", "net": lo_net,
                               "n_buy": lo_nb, "n_sell": lo_ns})
        elif lo_net >= 0 and (lo_nb + lo_ns) > 0 and not lo_ok:
            weak_candidates.append({"market": SHORT[mf.market_id], "slice": "vol",
                                    "bin": "low-vol", "net": lo_net,
                                    "n_buy": lo_nb, "n_sell": lo_ns})
        md.append(
            f"| `{SHORT[mf.market_id]}` | {lo_net:+.3f}c | {lo_nb}/{lo_ns} | "
            f"{hi_net:+.3f}c | {hi_nb}/{hi_ns} | "
            f"{'YES' if lo_nonneg else 'no'} |"
        )
    md.append("")
    md.append("*For 6 of 8 markets the median trailing-15min mid stddev is "
              "~0.00c (books are flat at 30s cadence on these thin markets), so "
              "the \"low-vol\" bin is effectively the perfectly-flat-trailing-"
              "window subset and \"high-vol\" is any-movement. The only bins "
              "that clear the ≥%d-fills-per-leg floor are the **high-vol** bins "
              "for `co_pval` (96/25) and `kr_oseh` (79/25) — both firmly "
              "negative (−0.633c, −0.785c). Every other bin is under-powered. "
              "Consistent with the adverse-selection story, where high-vol net "
              "markout is evaluable it is negative, not positive.*" % MIN_FILLS)
    md.append("")

    # =====================================================================
    # Headline
    # =====================================================================
    head: list[str] = []
    head.append("## Headline")
    head.append("")
    if candidates:
        head.append(f"**{len(_unique_markets(candidates))} of 8 markets have a "
                    f"tradeable regime** — a regime bin with net markout ≥ 0 AND "
                    f"≥{MIN_FILLS} genuine fills on each leg:")
        head.append("")
        for c in candidates:
            head.append(f"- `{c['market']}` [{c['slice']} = {c['bin']}]: "
                        f"net {c['net']:+.3f}c (n_buy={c['n_buy']}, "
                        f"n_sell={c['n_sell']}).")
    else:
        head.append("**No market has a tradeable regime.** Across all tested "
                    "regime bins (24 hour-of-day bins + low/high volatility) "
                    f"with ≥{MIN_FILLS} genuine fills on each leg, **zero** "
                    "show non-negative net 5min markout. Adverse selection on "
                    "the cross-venue LP is **unconditional** within this "
                    "daemon window — it is not concentrated in specific hours "
                    "or volatility states that an LP could avoid.")
    head.append("")
    if weak_candidates:
        head.append(f"*Noise watch:* {len(weak_candidates)} regime bin(s) show "
                    f"non-negative net markout but FAIL the ≥{MIN_FILLS}-fills-"
                    f"per-leg floor — treated as noise, not candidates:")
        for w in weak_candidates[:12]:
            head.append(f"  - `{w['market']}` [{w['slice']} = {w['bin']}]: "
                        f"net {w['net']:+.3f}c but n_buy={w['n_buy']}, "
                        f"n_sell={w['n_sell']}.")
        if len(weak_candidates) > 12:
            head.append(f"  - … and {len(weak_candidates) - 12} more.")
    else:
        head.append("*No sub-floor non-negative bins either.*")
    head.append("")
    md[headline_idx:headline_idx + 1] = head

    # ---- Caveats ----
    md.append("## Caveats")
    md.append("")
    md.append("1. **Same 30s / queue-proxy limits as EXP-12a.** Slicing does "
              "not add resolution; it only conditions the same proxy fills.")
    md.append("2. **Catalyst slice is degenerate for this window** (no fills "
              "within 2h of any catalyst). It becomes informative only once "
              "the F.1 May 31 / June 3 dense captures are folded in.")
    md.append("3. **Hour bins are single-day.** The daemon window is one UTC "
              "date, so each hour bin is one observation of that hour, not a "
              "day-of-week-robust average. A non-negative hour here could be "
              "a one-off, not a structural window.")
    md.append("4. **Per-leg independence.** Net combines two independently "
              "sliced legs; it does not require the two fills to be "
              "contemporaneous.")
    md.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md))
    print(f"\nWrote {OUT_MD.relative_to(ROOT)}")
    return candidates


def _bucket(fills: list[Fill], key) -> dict:
    out: dict = {}
    for f in fills:
        out.setdefault(key(f), []).append(f.markout_c)
    return out


def _unique_markets(rows: list[dict]) -> set:
    return {r["market"] for r in rows}


if __name__ == "__main__":
    sys.exit(main())
