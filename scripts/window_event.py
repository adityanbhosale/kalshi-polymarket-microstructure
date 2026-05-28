"""F.2 windowed analysis scaffold for an event-window capture.

Run AFTER the event with the catalyst time and pre/post window lengths.
Loads two CSVs:

  * the dense F.1 capture          (``data/processed/event_<label>_poll.csv``)
  * the E.1 30 s baseline           (``data/processed/timeofday_poll.csv``)

and merges them per (market, venue) so the pre-event baseline coverage
from E.1 fills in any time before the dense poller actually started.
For overlapping timestamps the dense series wins.

Computes, per market:

  1. **Lead-lag** between Kalshi YES mid and Polymarket YES mid via
     cross-correlation of first-difference series at lags
     ``-60 s … +60 s`` (1 s grid). Sign convention:

         lag > 0  ⇒  Kalshi leads Polymarket
         lag < 0  ⇒  Polymarket leads Kalshi
         lag = 0  ⇒  synchronous

     The reported (best_lag, best_corr) is argmax over ``|corr|``. This
     is the *core* output — it seeds the latency/agent thread.

  2. **Cross-venue mid-discrepancy time series** plotted across the full
     window with a vertical line at the catalyst.

  3. **Discrepancy distribution pre vs post catalyst** (count, mean, std)
     to answer: does the gap blow out at the catalyst and converge, stay
     blown out, or invert?

Outputs:

  * ``data/processed/event_<label>_analysis.md`` — summary tables.
  * ``data/processed/event_<label>_leadlag_<market_id>.png``  (one per market)
  * ``data/processed/event_<label>_discrepancy_<market_id>.png`` (one per market)

The catalyst instant is a CLI argument because the exact results-release
time isn't known until the event is over — for Colombia, results release
around 19:00 Colombia local but counting can stretch the "catalyst" by an
hour or more. Pass the timestamp at which **preliminary results begin
appearing**, not poll-close.

Usage:

    uv run python scripts/window_event.py \\
        --label colombia_r1 \\
        --catalyst-utc 2026-06-01T00:00:00+00:00 \\
        --pre-hours 2 --post-hours 4
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless rendering — no display required
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def _parse_iso_utc(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"invalid ISO timestamp {s!r}: {e}") from e
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"--catalyst-utc must be tz-aware (e.g. ...+00:00); got {s!r}"
        )
    return dt.astimezone(timezone.utc)


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["utc_ts"] = pd.to_datetime(df["utc_ts"], utc=True, format="ISO8601")
    return df


def _series_for(
    df: pd.DataFrame,
    market_id: str,
    venue: str,
    column: str,
    t_min: pd.Timestamp,
    t_max: pd.Timestamp,
) -> pd.Series:
    if df.empty or column not in df.columns:
        return pd.Series(dtype=float)
    sub = df[
        (df["market_id"] == market_id)
        & (df["venue"] == venue)
        & (df["utc_ts"] >= t_min)
        & (df["utc_ts"] <= t_max)
    ]
    sub = sub.dropna(subset=[column])
    if sub.empty:
        return pd.Series(dtype=float)
    return sub.set_index("utc_ts")[column].sort_index()


def _combine(base: pd.Series, dense: pd.Series) -> pd.Series:
    """Concatenate base + dense, preferring dense at duplicate timestamps."""
    if base.empty and dense.empty:
        return base
    s = pd.concat([base, dense]).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s


def _cross_corr_lead_lag(
    k: pd.Series, p: pd.Series, max_lag_s: int = 60, step_s: int = 1
) -> tuple[int | None, float | None, list[tuple[int, float]]]:
    """corr(Δp, Δk.shift(L)) for L ∈ [-max_lag_s, +max_lag_s].

    Sign convention: ``L > 0`` means past-Kalshi-changes-correlate-with-current-
    Polymarket-changes, i.e. Kalshi leads by L seconds. ``L < 0`` means
    past-Polymarket-changes-correlate-with-current-Kalshi-changes, i.e.
    Polymarket leads by |L| seconds. Returns ``(best_lag, best_corr,
    all_lags_corrs)``; best is argmax over ``|corr|``. On insufficient
    data returns ``(None, None, [])``.
    """
    if k.empty or p.empty:
        return None, None, []

    # Resample to a uniform 1 s grid so first-differences align exactly.
    rule = f"{step_s}s"
    k_r = k.resample(rule).mean().interpolate(limit_direction="both")
    p_r = p.resample(rule).mean().interpolate(limit_direction="both")
    common = k_r.index.intersection(p_r.index)
    if len(common) < 2 * max_lag_s + 5:
        return None, None, []

    dk = k_r.loc[common].diff().dropna()
    dp = p_r.loc[common].diff().dropna()
    common = dk.index.intersection(dp.index)
    dk = dk.loc[common]
    dp = dp.loc[common]
    if len(dk) < 2 * max_lag_s + 5:
        return None, None, []

    lags = list(range(-max_lag_s, max_lag_s + 1))
    corrs: list[float] = []
    for L in lags:
        ds = dk.shift(L)
        mask = ds.notna() & dp.notna()
        if mask.sum() < 5:
            corrs.append(float("nan"))
            continue
        ds_v = ds[mask]
        dp_v = dp[mask]
        if ds_v.std() == 0 or dp_v.std() == 0:
            corrs.append(float("nan"))
            continue
        corrs.append(float(np.corrcoef(ds_v, dp_v)[0, 1]))

    arr = np.array(corrs, dtype=float)
    if np.all(np.isnan(arr)):
        return None, None, list(zip(lags, corrs))
    best_i = int(np.nanargmax(np.abs(arr)))
    return lags[best_i], float(arr[best_i]), list(zip(lags, corrs))


def _plot_lead_lag(
    label: str, market_id: str, lags_corrs: list[tuple[int, float]],
    best_lag: int, best_corr: float, out_path: Path,
) -> None:
    lags = np.array([L for L, _ in lags_corrs])
    corrs = np.array([c for _, c in lags_corrs])
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.plot(lags, corrs, lw=1.2, color="steelblue")
    ax.axhline(0, color="black", lw=0.5)
    ax.axvline(0, color="black", lw=0.5, ls="--", alpha=0.6)
    ax.axvline(
        best_lag, color="crimson", lw=1.2, ls=":",
        label=f"best lag = {best_lag:+d} s   (r = {best_corr:+.3f})",
    )
    ax.set_xlabel("lag (seconds)   [+ ⇒ Kalshi leads, − ⇒ Polymarket leads]")
    ax.set_ylabel("corr(Δ Kalshi mid, Δ Polymarket mid)")
    ax.set_title(f"Lead-lag — {market_id} — {label}")
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def _plot_discrepancy(
    label: str, market_id: str, series: pd.Series,
    catalyst_utc: datetime, out_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 3.4))
    ax.plot(series.index, series.values, lw=0.8, color="steelblue")
    ax.axhline(0, color="black", lw=0.5)
    ax.axvline(catalyst_utc, color="crimson", lw=1.2, ls="--", label="catalyst")
    ax.set_xlabel("UTC time")
    ax.set_ylabel("mid_disc_direct (cents)\n+ ⇒ Polymarket richer than Kalshi")
    ax.set_title(f"Cross-venue discrepancy — {market_id} — {label}")
    ax.legend(loc="best", fontsize=9)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Windowed lead-lag + discrepancy analysis for an event capture."
    )
    ap.add_argument("--label", required=True, help="Event label (matches F.1 --label)")
    ap.add_argument("--catalyst-utc", type=_parse_iso_utc, required=True,
                    help="ISO-8601 tz-aware timestamp of the catalyst instant")
    ap.add_argument("--pre-hours", type=float, default=2.0)
    ap.add_argument("--post-hours", type=float, default=4.0)
    ap.add_argument("--markets", default=None,
                    help="Comma-separated market_ids to analyze. Default: every market_id "
                         "present in the event CSV.")
    args = ap.parse_args()

    event_path = PROCESSED_DIR / f"event_{args.label}_poll.csv"
    base_path = PROCESSED_DIR / "timeofday_poll.csv"
    out_md = PROCESSED_DIR / f"event_{args.label}_analysis.md"

    event_df = _load_csv(event_path)
    base_df = _load_csv(base_path)
    if event_df.empty:
        print(f"❌ no rows in {event_path}; nothing to analyze")
        return 1

    if args.markets:
        markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    else:
        markets = sorted(event_df["market_id"].unique())

    catalyst = pd.Timestamp(args.catalyst_utc)
    t_min = pd.Timestamp(args.catalyst_utc - timedelta(hours=args.pre_hours))
    t_max = pd.Timestamp(args.catalyst_utc + timedelta(hours=args.post_hours))

    md: list[str] = []
    md.append(f"# Event window analysis — `{args.label}`")
    md.append("")
    md.append(f"- Catalyst (UTC): `{catalyst.isoformat()}`")
    md.append(f"- Pre-window:  {args.pre_hours:.1f} h  →  `{t_min.isoformat()}`")
    md.append(f"- Post-window: {args.post_hours:.1f} h  →  `{t_max.isoformat()}`")
    md.append(
        f"- Sources: dense `{event_path.name}` "
        f"({len(event_df):,} rows) + 30 s baseline `{base_path.name}` "
        f"({len(base_df):,} rows)"
    )
    md.append("")
    md.append("Sign convention: `mid_disc_direct = poly_yes_mid − kalshi_yes_mid`, in cents. "
              "Positive ⇒ Polymarket pricing YES higher than Kalshi.")
    md.append("")
    md.append("Lead-lag sign convention: `lag > 0` ⇒ Kalshi leads Polymarket; "
              "`lag < 0` ⇒ Polymarket leads Kalshi; lag = 0 ⇒ synchronous.")
    md.append("")

    md.append("## Lead-lag (Kalshi YES vs Polymarket YES)")
    md.append("")
    md.append("| market | best_lag (s) | best_corr | interp |")
    md.append("|---|---:|---:|---|")

    for mid_id in markets:
        k_dense = _series_for(event_df, mid_id, "kalshi_yes",     "mid", t_min, t_max)
        k_base  = _series_for(base_df,  mid_id, "kalshi_yes",     "mid", t_min, t_max)
        p_dense = _series_for(event_df, mid_id, "polymarket_yes", "mid", t_min, t_max)
        p_base  = _series_for(base_df,  mid_id, "polymarket_yes", "mid", t_min, t_max)
        k = _combine(k_base, k_dense)
        p = _combine(p_base, p_dense)

        best_lag, best_corr, all_lc = _cross_corr_lead_lag(k, p)
        if best_lag is None:
            md.append(f"| `{mid_id}` | — | — | insufficient data |")
        else:
            if best_lag > 0:
                interp = f"Kalshi leads by {best_lag} s"
            elif best_lag < 0:
                interp = f"Polymarket leads by {abs(best_lag)} s"
            else:
                interp = "synchronous"
            md.append(f"| `{mid_id}` | {best_lag:+d} | {best_corr:+.3f} | {interp} |")
            _plot_lead_lag(
                args.label, mid_id, all_lc, best_lag, best_corr,
                PROCESSED_DIR / f"event_{args.label}_leadlag_{mid_id}.png",
            )

    md.append("")
    md.append("## Discrepancy distribution: pre vs post catalyst")
    md.append("")
    md.append(
        "| market | n_pre | n_post | mean_pre (¢) | mean_post (¢) | "
        "std_pre (¢) | std_post (¢) | Δmean (¢) |"
    )
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")

    for mid_id in markets:
        e_disc = _series_for(event_df, mid_id, "kalshi_yes", "mid_disc_direct", t_min, t_max)
        b_disc = _series_for(base_df,  mid_id, "kalshi_yes", "mid_disc_direct", t_min, t_max)
        all_disc = _combine(b_disc, e_disc)
        if all_disc.empty:
            md.append(f"| `{mid_id}` | 0 | 0 | — | — | — | — | — |")
            continue

        pre = all_disc[all_disc.index < catalyst]
        post = all_disc[all_disc.index >= catalyst]
        mean_pre = pre.mean() if not pre.empty else float("nan")
        mean_post = post.mean() if not post.empty else float("nan")
        std_pre = pre.std() if len(pre) > 1 else float("nan")
        std_post = post.std() if len(post) > 1 else float("nan")
        delta = (mean_post - mean_pre) if (not pre.empty and not post.empty) else float("nan")
        md.append(
            f"| `{mid_id}` | {len(pre)} | {len(post)} | "
            f"{mean_pre:+.3f} | {mean_post:+.3f} | "
            f"{std_pre:.3f} | {std_post:.3f} | "
            f"{delta:+.3f} |"
        )

        _plot_discrepancy(
            args.label, mid_id, all_disc, args.catalyst_utc,
            PROCESSED_DIR / f"event_{args.label}_discrepancy_{mid_id}.png",
        )

    md.append("")
    md.append("## Sample density inside the window")
    md.append("")
    md.append("| market | event rows | baseline rows | combined snapshots |")
    md.append("|---|---:|---:|---:|")
    for mid_id in markets:
        e_n = ((event_df["market_id"] == mid_id)
               & (event_df["utc_ts"] >= t_min) & (event_df["utc_ts"] <= t_max)).sum()
        b_n = ((base_df["market_id"] == mid_id)
               & (base_df["utc_ts"] >= t_min) & (base_df["utc_ts"] <= t_max)).sum() if not base_df.empty else 0
        # combined unique snapshots = rows / 4 venues (long format)
        combined_dist_ts = pd.concat([
            event_df[(event_df["market_id"] == mid_id) & (event_df["utc_ts"] >= t_min)
                     & (event_df["utc_ts"] <= t_max)]["utc_ts"]
            if not event_df.empty else pd.Series(dtype="datetime64[ns, UTC]"),
            base_df[(base_df["market_id"] == mid_id) & (base_df["utc_ts"] >= t_min)
                    & (base_df["utc_ts"] <= t_max)]["utc_ts"]
            if not base_df.empty else pd.Series(dtype="datetime64[ns, UTC]"),
        ]).nunique()
        md.append(f"| `{mid_id}` | {int(e_n)} | {int(b_n)} | {int(combined_dist_ts)} |")

    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Wrote {out_md}")
    print(f"Plots: data/processed/event_{args.label}_leadlag_*.png and "
          f"data/processed/event_{args.label}_discrepancy_*.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
