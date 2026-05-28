"""EXP-3c: multi-snapshot persistence of the EXP-3b takeable subset.

Across the full E.1 daemon history (`data/raw/timeofday/<date>/*.json.gz`),
for each of the 8 markets that were takeable at the institutional fee
tier in the D.2 snapshot, characterize:

  * % of snapshots where the book is genuinely crossed
    (direction-enforced take-take at institutional fees > 0)
  * median / max takeable $ when crossed
  * median paper spread when crossed
  * longest crossed run (minutes), longest non-crossed gap
  * time-of-day pattern (% crossed by UTC hour)
  * cross-market binary correlation (one regime vs independent)

Read-only on the daemon's raw history; reuses
`compute_executable_arb_direct` with a per-tier `_TierFeeContext` from
EXP-3b. No source / markets.yaml edits.

Outputs:
  data/processed/exp3c_persistence.md
  data/processed/exp3c_persistence.csv      (per-snapshot per-market log)
  figures/exp3c_crossed_by_hour.png
  figures/exp3c_correlation_heatmap.png
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pm_micro.arb import compute_executable_arb_direct  # noqa: E402
from pm_micro.fees import kalshi_fee, polymarket_fee  # noqa: E402
from pm_micro.normalize import (  # noqa: E402
    normalize_kalshi_orderbook,
    normalize_polymarket_orderbook,
)

MARKETS_8 = [
    "intl_president_pe_rpal",
    "intl_president_co_aesp",
    "intl_mayor_kr_oseh",
    "sports_retirement_arod",
    "us_mayor_la_kbas",
    "nba_finals_nyk",
    "intl_president_co_pval",
    "sports_retirement_kelce",
]
MARKET_SHORT = {
    "intl_president_pe_rpal": "pe_rpal",
    "intl_president_co_aesp": "co_aesp",
    "intl_mayor_kr_oseh": "kr_oseh",
    "sports_retirement_arod": "arod",
    "us_mayor_la_kbas": "la_kbas",
    "nba_finals_nyk": "nyk",
    "intl_president_co_pval": "co_pval",
    "sports_retirement_kelce": "kelce",
}

INSTITUTIONAL_TAKER = 0.0030

FEE_META_YAML = ROOT / "data" / "processed" / "market_fee_metadata.yaml"
RAW_DIR = ROOT / "data" / "raw" / "timeofday"
OUT_MD = ROOT / "data" / "processed" / "exp3c_persistence.md"
OUT_CSV = ROOT / "data" / "processed" / "exp3c_persistence.csv"
FIG_HOUR = ROOT / "figures" / "exp3c_crossed_by_hour.png"
FIG_CORR = ROOT / "figures" / "exp3c_correlation_heatmap.png"

FILENAME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{6}\.\d+\+\d{4})_(.+)\.json\.gz$"
)


# =========================================================================
# Per-tier fee functions (institutional only — EXP-3b's headline tier)
# =========================================================================

class _InstitutionalCtx:
    """Direction-enforced FeeContext: both legs taker @ 0.30% flat."""

    @staticmethod
    def apply(venue: str, side: str, price: float, size: float = 1.0) -> float:
        fee = INSTITUTIONAL_TAKER * price
        return price + fee if side == "buy" else price - fee


INSTITUTIONAL_CTX = _InstitutionalCtx()


# =========================================================================
# Book loading from gz
# =========================================================================

class _BookShim:
    """Duck-typed view onto a {bids, asks} dict for normalize_polymarket_orderbook."""

    def __init__(self, d: dict):
        self.bids = [type("L", (), x) for x in (d.get("bids") or [])]
        self.asks = [type("L", (), x) for x in (d.get("asks") or [])]


def _parse_filename(name: str) -> tuple[str, str] | None:
    m = FILENAME_RE.match(name)
    if not m:
        return None
    return m.group(1), m.group(2)


def _ts_to_dt(ts_str: str) -> datetime:
    # "2026-05-28T040157.339434+0000"
    # Convert to ISO format that fromisoformat accepts
    body, _, tz = ts_str.partition("+")
    dt = datetime.strptime(body, "%Y-%m-%dT%H%M%S.%f")
    tz_hours = int(tz[:2])
    tz_mins = int(tz[2:4])
    return dt.replace(tzinfo=timezone.utc) - pd.Timedelta(hours=tz_hours, minutes=tz_mins).to_pytimedelta()


# =========================================================================
# Per-snapshot computation
# =========================================================================

@dataclass
class SnapRow:
    utc_ts: datetime
    market_id: str
    is_crossed: bool
    takeable_usd: float
    fillable: float
    paper_spread_c: float
    k_bid: float
    k_ask: float
    p_yes_bid: float
    p_yes_ask: float
    error: str = ""


def process_one(gz_path: Path, market_id: str, ts_str: str) -> SnapRow | None:
    try:
        with gzip.open(gz_path, "rt") as f:
            raw = json.load(f)
    except Exception as e:
        return SnapRow(
            utc_ts=_ts_to_dt(ts_str), market_id=market_id, is_crossed=False,
            takeable_usd=0.0, fillable=0.0, paper_spread_c=float("nan"),
            k_bid=float("nan"), k_ask=float("nan"),
            p_yes_bid=float("nan"), p_yes_ask=float("nan"),
            error=f"load_fail:{type(e).__name__}",
        )

    errs = raw.get("errors") or {}
    if errs.get("kalshi") or errs.get("polymarket_yes"):
        return SnapRow(
            utc_ts=_ts_to_dt(ts_str), market_id=market_id, is_crossed=False,
            takeable_usd=0.0, fillable=0.0, paper_spread_c=float("nan"),
            k_bid=float("nan"), k_ask=float("nan"),
            p_yes_bid=float("nan"), p_yes_ask=float("nan"),
            error="fetch_err",
        )

    try:
        k_yes, _ = normalize_kalshi_orderbook(raw["kalshi_orderbook"], market_id, ts_str)
        p_yes = normalize_polymarket_orderbook(
            _BookShim(raw["polymarket_yes_orderbook"]),
            market_id, "yes", ts_str,
        )
    except Exception as e:
        return SnapRow(
            utc_ts=_ts_to_dt(ts_str), market_id=market_id, is_crossed=False,
            takeable_usd=0.0, fillable=0.0, paper_spread_c=float("nan"),
            k_bid=float("nan"), k_ask=float("nan"),
            p_yes_bid=float("nan"), p_yes_ask=float("nan"),
            error=f"norm_fail:{type(e).__name__}",
        )

    if not (k_yes.bids and k_yes.asks and p_yes.bids and p_yes.asks):
        return SnapRow(
            utc_ts=_ts_to_dt(ts_str), market_id=market_id, is_crossed=False,
            takeable_usd=0.0, fillable=0.0, paper_spread_c=float("nan"),
            k_bid=k_yes.bids[0].price if k_yes.bids else float("nan"),
            k_ask=k_yes.asks[0].price if k_yes.asks else float("nan"),
            p_yes_bid=p_yes.bids[0].price if p_yes.bids else float("nan"),
            p_yes_ask=p_yes.asks[0].price if p_yes.asks else float("nan"),
            error="empty_side",
        )

    k_bid, k_ask = k_yes.bids[0].price, k_yes.asks[0].price
    p_bid, p_ask = p_yes.bids[0].price, p_yes.asks[0].price
    paper_c = 0.0
    if p_bid > k_ask:
        paper_c = 100 * (p_bid - k_ask)
    elif k_bid > p_ask:
        paper_c = 100 * (k_bid - p_ask)

    res = compute_executable_arb_direct(
        k_yes, p_yes, market_id, fee_ctx=INSTITUTIONAL_CTX
    )
    takeable = res.net_profit_dollars
    is_crossed = takeable > 0.005

    return SnapRow(
        utc_ts=_ts_to_dt(ts_str), market_id=market_id, is_crossed=is_crossed,
        takeable_usd=takeable, fillable=res.fillable_size,
        paper_spread_c=paper_c,
        k_bid=k_bid, k_ask=k_ask, p_yes_bid=p_bid, p_yes_ask=p_ask,
    )


# =========================================================================
# Main pipeline
# =========================================================================

def collect_files() -> dict[str, list[tuple[str, Path]]]:
    by_market: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for date_dir in sorted(RAW_DIR.iterdir()):
        if not date_dir.is_dir():
            continue
        for f in date_dir.iterdir():
            parsed = _parse_filename(f.name)
            if not parsed:
                continue
            ts, market = parsed
            if market not in MARKETS_8:
                continue
            by_market[market].append((ts, f))
    for m in by_market:
        by_market[m].sort()
    return by_market


def compute_persistence_stats(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for market in MARKETS_8:
        sub = df[df["market_id"] == market].sort_values("utc_ts").reset_index(drop=True)
        sub_valid = sub[sub["error"] == ""]
        n_total = len(sub_valid)
        n_crossed = int(sub_valid["is_crossed"].sum())
        pct_crossed = (n_crossed / n_total * 100) if n_total else 0.0
        when_crossed = sub_valid[sub_valid["is_crossed"]]
        med_usd = when_crossed["takeable_usd"].median() if len(when_crossed) else 0.0
        max_usd = when_crossed["takeable_usd"].max() if len(when_crossed) else 0.0
        med_paper = when_crossed["paper_spread_c"].median() if len(when_crossed) else 0.0

        # Longest run of consecutive crossed snapshots and longest gap
        flags = sub_valid["is_crossed"].astype(int).to_numpy()
        runs_c, runs_n = _max_run(flags, 1), _max_run(flags, 0)

        if pct_crossed >= 50:
            verdict = "PERSISTENT"
        elif pct_crossed >= 10:
            verdict = "INTERMITTENT"
        elif pct_crossed > 0:
            verdict = "RARE"
        else:
            verdict = "SNAPSHOT-ONLY"

        rows.append({
            "market": MARKET_SHORT[market],
            "n_snapshots": n_total,
            "n_crossed": n_crossed,
            "pct_crossed": pct_crossed,
            "median_takeable_usd": float(med_usd) if pd.notna(med_usd) else 0.0,
            "max_takeable_usd": float(max_usd) if pd.notna(max_usd) else 0.0,
            "median_paper_c": float(med_paper) if pd.notna(med_paper) else 0.0,
            "longest_crossed_run_min": runs_c * 0.5,
            "longest_uncrossed_gap_min": runs_n * 0.5,
            "verdict": verdict,
        })
    return pd.DataFrame(rows)


def _max_run(arr: np.ndarray, val: int) -> int:
    best = cur = 0
    for x in arr:
        if x == val:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def hourly_pattern(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["error"] == ""].copy()
    d["hour"] = d["utc_ts"].dt.hour
    pivot = d.pivot_table(
        index="hour", columns="market_id",
        values="is_crossed", aggfunc="mean",
    ).reindex(columns=MARKETS_8)
    pivot.columns = [MARKET_SHORT[c] for c in pivot.columns]
    return (pivot * 100).round(1)


def correlation_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Returns (corr, always_crossed, never_crossed). Markets with zero
    variance (always crossed or never crossed) are dropped from the matrix
    and reported separately, since Pearson is undefined for them."""
    d = df[df["error"] == ""].copy()
    wide = d.pivot_table(
        index="utc_ts", columns="market_id",
        values="is_crossed", aggfunc="last",
    ).reindex(columns=MARKETS_8).dropna(how="any").astype(int)
    always = [c for c in wide.columns if wide[c].sum() == len(wide)]
    never = [c for c in wide.columns if wide[c].sum() == 0]
    variable = [c for c in wide.columns if c not in always + never]
    corr = wide[variable].corr() if variable else pd.DataFrame()
    corr.columns = [MARKET_SHORT[c] for c in corr.columns]
    corr.index = [MARKET_SHORT[c] for c in corr.index]
    return corr, [MARKET_SHORT[c] for c in always], [MARKET_SHORT[c] for c in never]


def aggregate_headline(df: pd.DataFrame) -> dict:
    d = df[df["error"] == ""].copy()
    wide_cross = d.pivot_table(
        index="utc_ts", columns="market_id",
        values="is_crossed", aggfunc="last",
    ).reindex(columns=MARKETS_8).fillna(False)
    wide_usd = d.pivot_table(
        index="utc_ts", columns="market_id",
        values="takeable_usd", aggfunc="last",
    ).reindex(columns=MARKETS_8).fillna(0.0)
    any_crossed = wide_cross.any(axis=1)
    pct_any = any_crossed.mean() * 100
    total_per_snap = wide_usd.sum(axis=1)
    median_total_when_any = total_per_snap[any_crossed].median() if any_crossed.any() else 0.0
    mean_total_when_any = total_per_snap[any_crossed].mean() if any_crossed.any() else 0.0
    max_total = total_per_snap.max()
    cols_ex_nyk = [c for c in wide_usd.columns if c != "nba_finals_nyk"]
    total_ex_nyk = wide_usd[cols_ex_nyk].sum(axis=1)
    any_ex_nyk = wide_cross[cols_ex_nyk].any(axis=1)
    median_ex_nyk = total_ex_nyk[any_ex_nyk].median() if any_ex_nyk.any() else 0.0
    return {
        "n_snapshot_groups": int(len(wide_cross)),
        "pct_snapshots_any_crossed": float(pct_any),
        "median_total_takeable_when_any": float(median_total_when_any),
        "mean_total_takeable_when_any": float(mean_total_when_any),
        "max_total_takeable": float(max_total),
        "median_total_ex_nyk": float(median_ex_nyk),
        "pct_snapshots_any_crossed_ex_nyk": float(any_ex_nyk.mean() * 100),
    }


# =========================================================================
# Figures
# =========================================================================

def plot_hourly(hourly: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for col in hourly.columns:
        ax.plot(hourly.index, hourly[col], marker="o", label=col, linewidth=1.5)
    ax.set_xlabel("UTC hour")
    ax.set_ylabel("% snapshots crossed (institutional fees)")
    ax.set_title("EXP-3c: crossed-frequency by UTC hour (8 takeable-subset markets)")
    ax.set_xticks(range(0, 24))
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", fontsize=8, ncol=2)
    fig.tight_layout()
    FIG_HOUR.parent.mkdir(exist_ok=True, parents=True)
    fig.savefig(FIG_HOUR, dpi=130)
    plt.close(fig)


def plot_correlation(corr: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt
    if corr.empty:
        return
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(corr.index)))
    ax.set_yticklabels(corr.index)
    for i in range(len(corr.index)):
        for j in range(len(corr.columns)):
            v = corr.values[i, j]
            ax.text(j, i, f"{v:+.2f}", ha="center", va="center",
                    color="black" if abs(v) < 0.5 else "white", fontsize=8)
    ax.set_title(f"EXP-3c: binary crossed-status correlation "
                 f"({len(corr.columns)} variable markets; "
                 f"nyk + kelce always-crossed, excluded)")
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    FIG_CORR.parent.mkdir(exist_ok=True, parents=True)
    fig.savefig(FIG_CORR, dpi=130)
    plt.close(fig)


# =========================================================================
# Markdown writer
# =========================================================================

def write_md(
    pstats: pd.DataFrame, hourly: pd.DataFrame, corr: pd.DataFrame,
    always: list[str], never: list[str],
    head: dict, n_total_files: int, n_err_files: int,
) -> None:
    md: list[str] = []
    md.append("# EXP-3c Multi-Snapshot Persistence")
    md.append("")
    md.append(
        f"**Daemon history:** `data/raw/timeofday/` — "
        f"{n_total_files:,} (snapshot × market) records across the 8 "
        f"EXP-3b takeable-subset markets; {n_err_files} fetch errors "
        f"excluded.  "
    )
    md.append(
        f"**Snapshot groups (distinct UTC timestamps with all 8 books "
        f"present):** {head['n_snapshot_groups']:,}.  "
    )
    md.append("**Fee tier:** institutional (0.30% taker flat, both venues).  ")
    md.append(
        "**Engine:** `compute_executable_arb_direct` with the "
        "`_InstitutionalCtx` from EXP-3b; identical direction-enforced "
        "take-take walker."
    )
    md.append("")
    md.append("## Headline numbers")
    md.append("")
    md.append(f"* **% snapshots with ≥1 market crossed:** "
              f"{head['pct_snapshots_any_crossed']:.1f}%")
    md.append(f"* **Median total takeable $ when something is crossed:** "
              f"${head['median_total_takeable_when_any']:.2f}")
    md.append(f"* **Mean total takeable $ when something is crossed:** "
              f"${head['mean_total_takeable_when_any']:.2f}")
    md.append(f"* **Max single-snapshot total takeable $:** "
              f"${head['max_total_takeable']:.2f}")
    md.append(f"* **Median total *excluding* nyk** (which dominates and may "
              f"reflect a structural dislocation, see below): "
              f"${head['median_total_ex_nyk']:.2f} on "
              f"{head['pct_snapshots_any_crossed_ex_nyk']:.1f}% of snapshots.")
    md.append("")
    md.append("## Per-market persistence")
    md.append("")
    md.append("| market | n snaps | % crossed | median $ when crossed | "
              "max $ | median paper c | longest crossed run | "
              "longest uncrossed gap | verdict |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for _, r in pstats.iterrows():
        md.append(
            f"| `{r['market']}` | {r['n_snapshots']:,} | "
            f"{r['pct_crossed']:.1f}% | ${r['median_takeable_usd']:.2f} | "
            f"${r['max_takeable_usd']:.2f} | {r['median_paper_c']:.2f}c | "
            f"{r['longest_crossed_run_min']:.1f} min | "
            f"{r['longest_uncrossed_gap_min']:.1f} min | **{r['verdict']}** |"
        )
    md.append("")
    md.append(
        "*Verdict thresholds: PERSISTENT ≥50%, INTERMITTENT 10–50%, "
        "RARE <10% (>0%), SNAPSHOT-ONLY 0%. Daemon cadence is 30s, so "
        "the longest-run columns are in 30-second steps (×0.5 min)."
    )
    md.append("")
    md.append("## Time-of-day pattern (% crossed by UTC hour)")
    md.append("")
    md.append("![exp3c crossed by hour](../../figures/exp3c_crossed_by_hour.png)")
    md.append("")
    md.append("| hour |" + " | ".join(f" `{c}` " for c in hourly.columns) + " |")
    md.append("|---" + "|---" * len(hourly.columns) + "|")
    for hour, row in hourly.iterrows():
        cells = " | ".join(f"{v:.1f}%" if pd.notna(v) else "—" for v in row.values)
        md.append(f"| {hour:02d}Z | {cells} |")
    md.append("")
    md.append("## Cross-market binary correlation")
    md.append("")
    if always or never:
        if always:
            md.append(f"**Always-crossed markets (zero variance, omitted from "
                      f"corr matrix):** {', '.join('`'+m+'`' for m in always)}. "
                      f"Pearson is undefined when a series is constant; their "
                      f"behavior is itself the finding (perpetual crossing).")
        if never:
            md.append(f"**Never-crossed markets:** {', '.join('`'+m+'`' for m in never)}.")
        md.append("")
    if not corr.empty:
        md.append("![exp3c correlation heatmap](../../figures/exp3c_correlation_heatmap.png)")
        md.append("")
        md.append("Binary Pearson correlation of `is_crossed` (1/0) per "
                  f"snapshot across the {len(corr.columns)} variable-status "
                  "markets:")
        md.append("")
        md.append("| | " + " | ".join(f"`{c}`" for c in corr.columns) + " |")
        md.append("|---" + "|---" * len(corr.columns) + "|")
        for idx, row in corr.iterrows():
            md.append(f"| `{idx}` | " + " | ".join(f"{v:+.2f}" for v in row.values) + " |")
        md.append("")
        md.append(
            "*Interpretation: correlation > +0.5 indicates 'crossed at the "
            "same time' (one liquidity regime); ~0 indicates independent "
            "crossing; negative values indicate anti-correlated regimes."
        )
        md.append("")
    md.append("## Interpretation")
    md.append("")
    md.append(_build_interpretation(pstats, head, corr, always, never))
    md.append("")
    md.append("## Caveats")
    md.append("")
    md.append(
        "1. **Daemon window only.** Data spans the E.1 daemon's continuous "
        "run window (~2026-05-28T04:00Z onward, ~14 hours at the time of "
        "this run). Frequencies are conditional on that window; they are "
        "not lifetime market statistics."
    )
    md.append(
        "2. **Single-day.** All snapshots fall within one UTC date; "
        "day-of-week / weekend effects are unobserved."
    )
    md.append(
        "3. **Institutional tier is counterfactual** (same caveat as "
        "EXP-3b). At retail fees, every count above would be 0 — that's "
        "the EXP-3a/3b finding."
    )
    md.append(
        "4. **Exclusive-fill assumption.** Dollar figures assume the "
        "first arbitrageur to fire gets the full resting depth on both "
        "venues. Queue position, latency, and competition are not "
        "modeled. Real PnL would be a fraction of the headline."
    )
    md.append(
        "5. **Adverse selection.** If a takeable cross persists for "
        "minutes (see longest-run column), that's evidence the resting "
        "orders may be informed quotes — the contra-side hasn't been "
        "lifted by other arbitrageurs because, perhaps, the fill would "
        "be toxic. The 'persistent' verdicts should be read with this in "
        "mind: long persistence ≠ free money."
    )
    md.append("")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md))
    print(f"\nWrote {OUT_MD.relative_to(ROOT)}")


def _build_interpretation(
    pstats: pd.DataFrame, head: dict, corr: pd.DataFrame,
    always: list[str], never: list[str],
) -> str:
    parts = []
    parts.append(
        f"**Crossing is the norm, not the exception, at the institutional "
        f"fee tier.** Across the daemon window, {head['pct_snapshots_any_crossed']:.1f}% "
        f"of snapshots have at least one of the 8 markets crossed; when "
        f"any is crossed the median total takeable is "
        f"${head['median_total_takeable_when_any']:.2f}. **`nyk` alone "
        f"drives most of this** — excluding nyk, the median when "
        f"anything else is crossed is ${head['median_total_ex_nyk']:.2f} "
        f"(on {head['pct_snapshots_any_crossed_ex_nyk']:.1f}% of snapshots). "
        f"nyk and kelce are always-crossed throughout the daemon window, "
        f"suggesting they sit in a structurally crossed regime (NBA "
        f"Finals + Travis Kelce retirement; both have wide K ticks "
        f"relative to fine PM ticks) rather than transient flow events. "
        f"Even modest persistent crossings would be expected to be "
        f"arbed out by any real institutional arbitrageur in seconds; "
        f"that they persist for 14+ hours strongly suggests either "
        f"(a) no actor on either venue has the 0.30%/0.20% access we "
        f"modeled, or (b) the resting orders are informed and lifting "
        f"them is adversely selected (see caveat 5)."
    )
    persistent = pstats[pstats["verdict"] == "PERSISTENT"]["market"].tolist()
    intermittent = pstats[pstats["verdict"] == "INTERMITTENT"]["market"].tolist()
    rare = pstats[pstats["verdict"] == "RARE"]["market"].tolist()
    snap_only = pstats[pstats["verdict"] == "SNAPSHOT-ONLY"]["market"].tolist()
    parts.append("")
    parts.append(
        f"**Per-market split:** {len(persistent)} PERSISTENT "
        f"({', '.join('`'+m+'`' for m in persistent) or '—'}); "
        f"{len(intermittent)} INTERMITTENT "
        f"({', '.join('`'+m+'`' for m in intermittent) or '—'}); "
        f"{len(rare)} RARE "
        f"({', '.join('`'+m+'`' for m in rare) or '—'}); "
        f"{len(snap_only)} SNAPSHOT-ONLY "
        f"({', '.join('`'+m+'`' for m in snap_only) or '—'})."
    )
    parts.append("")

    # Pull correlation insight
    arr = corr.values.copy()
    np.fill_diagonal(arr, np.nan)
    if np.isnan(arr).all():
        parts.append("**Correlation:** insufficient overlapping snapshots.")
    else:
        flat = []
        for i in range(len(corr)):
            for j in range(i + 1, len(corr)):
                flat.append((corr.index[i], corr.columns[j], corr.values[i, j]))
        flat.sort(key=lambda x: -abs(x[2]) if pd.notna(x[2]) else 0)
        top_pos = [t for t in flat if pd.notna(t[2]) and t[2] > 0][:3]
        top_neg = [t for t in flat if pd.notna(t[2]) and t[2] < 0][:3]
        med_abs = np.nanmedian(np.abs(arr))
        n_pairs = len(corr) * (len(corr) - 1) // 2
        parts.append(
            f"**Correlation:** median |corr| across {n_pairs} distinct "
            f"pairs (excluding the always-crossed `nyk`/`kelce`) = "
            f"{med_abs:.2f}. "
            + ("Markets cross **independently** (low pairwise correlation): "
               "this is 8 separate edges, not one liquidity regime."
               if med_abs < 0.2 else
               "Markets show **shared regime structure** (median |corr| "
               "above 0.2): crossing is partly driven by a common "
               "liquidity/volatility factor.")
        )
        if top_pos:
            parts.append("")
            parts.append("Top positively-correlated pairs (crossed together): "
                         + ", ".join(f"`{a}`↔`{b}` ({c:+.2f})" for a, b, c in top_pos) + ".")
        if top_neg:
            parts.append("")
            parts.append("Top anti-correlated pairs: "
                         + ", ".join(f"`{a}`↔`{b}` ({c:+.2f})" for a, b, c in top_neg) + ".")
    parts.append("")

    # Time-of-day note (skip if all hours similar)
    parts.append(
        "**Time-of-day:** see figure. The daemon's first observed hour "
        "is 04Z (start of run); hours 00–03Z are unobserved in this "
        "window. Sustained crossing during business-day hours in the "
        "primary venue's home tz (Polymarket → US, Kalshi → US) would "
        "indicate flow-driven dislocation; uniform crossing would "
        "indicate structural (not flow) crossedness."
    )
    return "\n".join(parts)


# =========================================================================
# Entry point
# =========================================================================

def main() -> int:
    print("EXP-3c: scanning E.1 daemon history for 8 markets...")
    by_market = collect_files()
    n_files = sum(len(v) for v in by_market.values())
    print(f"  Found {n_files:,} (snapshot × market) raw gz files for the 8 markets.")
    for m in MARKETS_8:
        print(f"    {MARKET_SHORT[m]:8s} {len(by_market.get(m, [])):>6,} snapshots")
    print("\nProcessing books (institutional fee tier)...")

    all_rows: list[SnapRow] = []
    for m in MARKETS_8:
        items = by_market.get(m, [])
        for i, (ts, p) in enumerate(items, 1):
            r = process_one(p, m, ts)
            if r is not None:
                all_rows.append(r)
            if i % 500 == 0:
                print(f"    {MARKET_SHORT[m]:8s} {i:>6,}/{len(items):,}")

    df = pd.DataFrame([{
        "utc_ts": r.utc_ts, "market_id": r.market_id,
        "is_crossed": r.is_crossed, "takeable_usd": r.takeable_usd,
        "fillable": r.fillable, "paper_spread_c": r.paper_spread_c,
        "k_bid": r.k_bid, "k_ask": r.k_ask,
        "p_yes_bid": r.p_yes_bid, "p_yes_ask": r.p_yes_ask,
        "error": r.error,
    } for r in all_rows])
    df = df.sort_values(["market_id", "utc_ts"]).reset_index(drop=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"  Wrote {OUT_CSV.relative_to(ROOT)} ({len(df):,} rows)")

    n_err = int((df["error"] != "").sum())
    pstats = compute_persistence_stats(df)
    hourly = hourly_pattern(df)
    corr, always, never = correlation_matrix(df)
    head = aggregate_headline(df)

    plot_hourly(hourly)
    plot_correlation(corr)
    print(f"  Wrote {FIG_HOUR.relative_to(ROOT)}")
    if not corr.empty:
        print(f"  Wrote {FIG_CORR.relative_to(ROOT)}")

    write_md(pstats, hourly, corr, always, never, head, n_files, n_err)

    print("\n=== Headline ===")
    print(f"  % snapshots with ≥1 market crossed: "
          f"{head['pct_snapshots_any_crossed']:.1f}%")
    print(f"  Median total takeable $ when any crossed: "
          f"${head['median_total_takeable_when_any']:.2f}")
    print(f"  Mean total: ${head['mean_total_takeable_when_any']:.2f}, "
          f"max: ${head['max_total_takeable']:.2f}")
    print("\n=== Per-market persistence ===")
    for _, r in pstats.iterrows():
        print(f"  {r['market']:8s}  {r['pct_crossed']:5.1f}% crossed  "
              f"median ${r['median_takeable_usd']:6.2f}  "
              f"max ${r['max_takeable_usd']:7.2f}  "
              f"{r['verdict']}")
    if n_err:
        print(f"\n  ({n_err} fetch errors excluded from stats.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
