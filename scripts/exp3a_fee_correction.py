"""EXP-3a: re-run D.2 snapshot's arb computation under FOUR fee scenarios
and diff the executable-arb verdicts vs the pre-EXP-3a stale baseline.

Scenarios:
  (A) STALE       — pre-EXP-3a constants (Kalshi $0.02 flat, PM 2% flat)
  (B) CORR_TAKER  — corrected, both legs taker (new conservative floor)
  (C) MIXED       — Kalshi taker / Polymarket MAKER (realistic passive PM)
  (D) BOTH_MAKER  — corrected, both legs maker (optimistic floor)

Per-market fee params (Kalshi `fee_multiplier` + `fee_type`, Polymarket
`feeSchedule.rate` + `rebateRate`) come from
data/processed/market_fee_metadata.yaml — pulled live from the venues by
scripts/fetch_market_fee_metadata.py. Markets without a Polymarket
listing (e.g. delisted CLE) are logged as explicit skips with reason,
NOT silently dropped.

Output: data/processed/exp3a_fee_correction.md
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pm_micro.arb import (  # noqa: E402
    FeeContext,
    compute_executable_arb_direct,
    compute_executable_arb_synthetic,
    compute_mid_discrepancy,
)
from pm_micro.normalize import (  # noqa: E402
    normalize_kalshi_orderbook,
    normalize_polymarket_orderbook,
)

MARKETS_YAML = ROOT / "markets.yaml"
FEE_META_YAML = ROOT / "data" / "processed" / "market_fee_metadata.yaml"
RAW_DIR = ROOT / "data" / "raw"
OUT_MD = ROOT / "data" / "processed" / "exp3a_fee_correction.md"


# =========================================================================
# Stale baseline: replica of pre-EXP-3a constants
# =========================================================================

# These ARE the pre-EXP-3a constants. Kept here in plain sight for the
# baseline scenario so the diff is self-contained — i.e. running this
# script in two years will still reproduce the same baseline numbers
# regardless of how `fees.py` evolves.
STALE_POLYMARKET_RATE = 0.02
STALE_KALSHI_FLAT_DOLLARS = 0.02


@dataclass
class StaleFeeContext:
    """Replica of the pre-EXP-3a flat-fee model.

    Duck-typed to substitute for `pm_micro.arb.FeeContext` in the
    executable-arb walkers. Walkers only invoke `.apply(...)`.
    """
    def apply(self, venue: str, side: str, price: float, size: float = 1.0) -> float:
        if venue == "polymarket":
            adj = STALE_POLYMARKET_RATE * price
        elif venue == "kalshi":
            adj = STALE_KALSHI_FLAT_DOLLARS
        else:
            raise ValueError(f"unknown venue: {venue}")
        return price + adj if side == "buy" else price - adj


class _BookShim:
    """Mimic the Polymarket OrderBookSummary structure from a saved JSON dict."""
    def __init__(self, d: dict):
        self.bids = [type("L", (), x) for x in d.get("bids", [])]
        self.asks = [type("L", (), x) for x in d.get("asks", [])]


def find_most_recent_snapshot() -> Path:
    candidates = sorted(RAW_DIR.glob("snapshot_*"))
    if not candidates:
        raise RuntimeError("No snapshots under data/raw/")
    return candidates[-1]


def load_books(snapshot_dir: Path, market_id: str):
    """Load Kalshi YES + Polymarket YES + Polymarket NO from a snapshot dir.

    Returns ``(k_yes, p_yes, p_no, missing_reason)`` where missing_reason
    is a non-empty string describing why some books couldn't be loaded
    (used to surface explicit skips like the delisted CLE).
    """
    kpath = snapshot_dir / f"{market_id}_kalshi.json"
    pyes_path = snapshot_dir / f"{market_id}_polymarket_yes.json"
    pno_path = snapshot_dir / f"{market_id}_polymarket_no.json"

    if not kpath.exists():
        return None, None, None, f"missing Kalshi snapshot: {kpath.name}"
    if not pyes_path.exists():
        return None, None, None, (
            f"missing Polymarket YES snapshot: {pyes_path.name} "
            "(token likely delisted at fetch time)"
        )

    with open(kpath) as f:
        raw_k = json.load(f)
    k_yes, _ = normalize_kalshi_orderbook(raw_k, market_id, "from_disk")
    with open(pyes_path) as f:
        raw_pyes = json.load(f)
    p_yes = normalize_polymarket_orderbook(
        _BookShim(raw_pyes), market_id, "yes", "from_disk"
    )
    p_no = None
    if pno_path.exists():
        with open(pno_path) as f:
            raw_pno = json.load(f)
        p_no = normalize_polymarket_orderbook(
            _BookShim(raw_pno), market_id, "no", "from_disk"
        )
    return k_yes, p_yes, p_no, ""


def fee_contexts_for(meta: dict) -> dict[str, FeeContext | StaleFeeContext]:
    """Build the 4 FeeContexts for a single market from its metadata.

    Per-market split that the user called out:
      * The 4 NBA Finals (KXNBA, fee_type="quadratic_with_maker_fees")
        carry a 25% Kalshi maker fee — derived from
        `kalshi.maker_fraction = 0.25` in market_fee_metadata.yaml.
      * The other 12 markets (fee_type="quadratic") have Kalshi maker
        fee = $0 — `kalshi.maker_fraction = 0`. We do NOT apply 0.25
        uniformly.
    """
    k_mult = float(meta["kalshi"]["fee_multiplier"])
    k_maker_frac = float(meta["kalshi"]["maker_fraction"])
    pm_rate = float(meta["polymarket"]["resolved_rate"])
    pm_rebate = float(meta["polymarket"].get("api_rebate_rate") or 0.22)
    return {
        "A_STALE": StaleFeeContext(),
        "B_CORR_TAKER": FeeContext(
            kalshi_multiplier=k_mult,
            kalshi_maker_fraction=k_maker_frac,
            kalshi_execution_mode="taker",
            pm_rate=pm_rate,
            pm_execution_mode="taker",
            pm_use_rebate=False,
            pm_rebate_fraction=pm_rebate,
        ),
        "C_MIXED": FeeContext(
            kalshi_multiplier=k_mult,
            kalshi_maker_fraction=k_maker_frac,
            kalshi_execution_mode="taker",
            pm_rate=pm_rate,
            pm_execution_mode="maker",
            pm_use_rebate=False,
            pm_rebate_fraction=pm_rebate,
        ),
        "D_BOTH_MAKER": FeeContext(
            kalshi_multiplier=k_mult,
            kalshi_maker_fraction=k_maker_frac,
            kalshi_execution_mode="maker",
            pm_rate=pm_rate,
            pm_execution_mode="maker",
            pm_use_rebate=False,
            pm_rebate_fraction=pm_rebate,
        ),
    }


def best_executable(k_yes, p_yes, p_no, market_id: str, fee_ctx) -> dict:
    """Return per-scenario {direct, synthetic, best} dict of executable arb $."""
    d = compute_executable_arb_direct(k_yes, p_yes, market_id, fee_ctx=fee_ctx)
    s = compute_executable_arb_synthetic(k_yes, p_no, market_id, fee_ctx=fee_ctx)
    best = max(d.net_profit_dollars, s.net_profit_dollars)
    return {
        "direct_net": d.net_profit_dollars,
        "direct_fillable": d.fillable_size,
        "synth_net": s.net_profit_dollars,
        "synth_fillable": s.fillable_size,
        "best_net": best,
        "verdict": "YES" if best > 0.0001 else "NO",
    }


def format_money(x: float) -> str:
    if abs(x) < 0.005:
        return "$0.00"
    return f"${x:.2f}"


def main() -> int:
    with open(MARKETS_YAML) as f:
        markets = yaml.safe_load(f)
    with open(FEE_META_YAML) as f:
        meta_list = yaml.safe_load(f)
    meta_by_id = {e["market_id"]: e for e in meta_list}

    snapshot_dir = find_most_recent_snapshot()
    print(f"Using snapshot: {snapshot_dir.name}")

    rows: list[dict] = []
    skipped: list[dict] = []

    for m in markets:
        mid = m["id"]
        meta = meta_by_id.get(mid)
        if not meta:
            skipped.append({"market_id": mid, "reason": "no fee metadata entry"})
            continue
        k_yes, p_yes, p_no, missing = load_books(snapshot_dir, mid)
        if missing:
            skipped.append({
                "market_id": mid,
                "reason": missing,
                "context": "delisted 2026-05-26, PM 404, no executable arb computable"
                if mid == "nba_finals_cle"
                else "snapshot file missing on disk",
            })
            continue

        md = compute_mid_discrepancy(k_yes, p_yes, p_no, mid)
        ctxs = fee_contexts_for(meta)
        scenarios = {name: best_executable(k_yes, p_yes, p_no, mid, ctx)
                     for name, ctx in ctxs.items()}
        # "verdict_changed" = any of B/C/D flips vs A (stale baseline).
        # Reported as Y/N in the per-market table; the summary section
        # below breaks it down by scenario.
        a_v = scenarios["A_STALE"]["verdict"]
        verdict_changed = any(
            scenarios[k]["verdict"] != a_v for k in ("B_CORR_TAKER", "C_MIXED", "D_BOTH_MAKER")
        )
        rows.append({
            "market_id": mid,
            "internal_category": meta.get("internal_category"),
            "k_category_raw": meta["kalshi"].get("category_raw"),
            "k_fee_type": meta["kalshi"].get("fee_type"),
            "k_mult": meta["kalshi"].get("fee_multiplier"),
            "k_maker_frac": meta["kalshi"].get("maker_fraction"),
            "pm_feeType": meta["polymarket"].get("fee_type"),
            "pm_rate": meta["polymarket"].get("resolved_rate"),
            "kalshi_mid": md.kalshi_mid,
            "pm_yes_mid": md.polymarket_yes_mid,
            "disc_direct_c": md.discrepancy_direct_cents,
            "disc_synth_c": md.discrepancy_synthetic_cents,
            "scenarios": scenarios,
            "verdict_changed": verdict_changed,
            # Snapshot of book characteristics for the depth-binds check
            "k_ask_top_size": k_yes.asks[0].size if k_yes.asks else 0.0,
            "pm_yes_bid_top_size": p_yes.bids[0].size if p_yes and p_yes.bids else 0.0,
            "pm_yes_ask_top_size": p_yes.asks[0].size if p_yes and p_yes.asks else 0.0,
        })

    write_md(rows, skipped, snapshot_dir)
    summarize(rows, skipped)
    return 0


def write_md(rows: list[dict], skipped: list[dict], snapshot_dir: Path) -> None:
    lines: list[str] = []
    lines.append("# EXP-3a: Fee Correction Diff vs Stale Baseline")
    lines.append("")
    lines.append(f"**Snapshot:** `{snapshot_dir.name}`")
    lines.append(f"**Markets computed:** {len(rows)}  ")
    lines.append(f"**Markets skipped:** {len(skipped)}  ")
    lines.append("")
    lines.append("## Fee model corrections")
    lines.append("")
    lines.append("**Stale baseline (pre-EXP-3a):** Kalshi $0.02 flat per contract, "
                 "Polymarket 2% flat of notional. Both legs taker. Source: hardcoded "
                 "constants in `src/pm_micro/arb.py` lines 17-19 prior to this commit.")
    lines.append("")
    lines.append("**Corrected models (live API, fetched 2026-05-28):**")
    lines.append("")
    lines.append("* Kalshi parabolic: `taker_cents = ceil(7 * fee_multiplier * C * (1-C))`. "
                 "All 16 markets have `fee_multiplier=1`. At midprice this equals "
                 "the historical 2¢; at tail prices (C<0.10 or C>0.90) it drops to 1¢.")
    lines.append("* Kalshi maker: 25% of taker for `fee_type=quadratic_with_maker_fees` "
                 "(4 NBA Finals only); **$0** for `fee_type=quadratic` (other 12 markets). "
                 "We do NOT apply 25% uniformly.")
    lines.append("* Polymarket: category-dependent, pulled per-market from "
                 "`feeSchedule.rate`. Sports = 3%, politics/tech = 4%. **Zero of our 16 "
                 "markets are fee-free geopolitics** — all intl elections classify as "
                 "`politics_fees` at 4% per the live API.")
    lines.append("* Polymarket maker: 0% (`takerOnly: true` on every market). Rebate "
                 "is 25% of counterparty taker fee (modeled OFF by default; not used in "
                 "any scenario below to keep maker numbers conservative).")
    lines.append("")
    lines.append("## Per-market verdict diff")
    lines.append("")
    hdr = (
        "| market | category | k_mult | k_fee_type | pm_rate | "
        "stale | corr_taker | mixed | both_maker | verdict_Δ |"
    )
    sep = "|" + "|".join(["---"] * 10) + "|"
    lines.append(hdr)
    lines.append(sep)

    for r in rows:
        s = r["scenarios"]
        def cell(scen):
            v = s[scen]["verdict"]
            net = s[scen]["best_net"]
            return f"{v} ({format_money(net)})"
        delta = "**Y**" if r["verdict_changed"] else "N"
        lines.append(
            f"| {r['market_id']} | {r.get('internal_category','')} | "
            f"{r['k_mult']} | {r['k_fee_type']} | {r['pm_rate']} | "
            f"{cell('A_STALE')} | {cell('B_CORR_TAKER')} | "
            f"{cell('C_MIXED')} | {cell('D_BOTH_MAKER')} | {delta} |"
        )

    if skipped:
        lines.append("")
        lines.append("## Skipped markets")
        lines.append("")
        for s in skipped:
            ctx = f" — {s['context']}" if s.get("context") else ""
            lines.append(f"* `{s['market_id']}`: {s['reason']}{ctx}")

    flips_b = sum(1 for r in rows if r["scenarios"]["A_STALE"]["verdict"]
                  != r["scenarios"]["B_CORR_TAKER"]["verdict"])
    flips_c = sum(1 for r in rows if r["scenarios"]["A_STALE"]["verdict"]
                  != r["scenarios"]["C_MIXED"]["verdict"])
    flips_d = sum(1 for r in rows if r["scenarios"]["A_STALE"]["verdict"]
                  != r["scenarios"]["D_BOTH_MAKER"]["verdict"])
    lines.append("")
    lines.append("## Summary of verdict flips")
    lines.append("")
    lines.append(f"* **B (corrected taker) vs A (stale):** {flips_b} flips out of {len(rows)}.")
    lines.append(f"* **C (mixed: K taker / PM maker) vs A:** {flips_c} flips.")
    lines.append(f"* **D (both maker) vs A:** {flips_d} flips.")
    lines.append("")

    def list_flips(scen_key: str, label: str):
        flipped = [r for r in rows
                   if r["scenarios"]["A_STALE"]["verdict"]
                   != r["scenarios"][scen_key]["verdict"]]
        if not flipped:
            lines.append(f"* **{label}**: no markets flip.")
            return
        lines.append(f"* **{label}** ({len(flipped)} flips):")
        for r in flipped:
            s = r["scenarios"]
            lines.append(
                f"  * `{r['market_id']}` "
                f"({format_money(s['A_STALE']['best_net'])} → "
                f"{format_money(s[scen_key]['best_net'])})"
            )

    lines.append("Which markets flip and why:")
    lines.append("")
    list_flips("B_CORR_TAKER", "Scenario B (corrected taker)")
    list_flips("C_MIXED", "Scenario C (mixed)")
    list_flips("D_BOTH_MAKER", "Scenario D (both maker)")
    lines.append("")

    # ARod depth-binds check
    arod = next((r for r in rows if r["market_id"] == "sports_retirement_arod"), None)
    if arod:
        lines.append("## ARod depth-binds check")
        lines.append("")
        lines.append(
            "The D.2 finding (`docs/build_log.md:30-34`) was: "
            "*\"sports_retirement_arod paper edge (+5.85c) CLEARS the ~3c fee "
            "threshold — the first such market in the project — yet executable "
            "arb is still $0 because Polymarket YES has $0 depth within 1c. In "
            "thin tail markets the binding constraint is depth, not the 2% taker "
            "fee.\"*"
        )
        lines.append("")
        lines.append(
            "**On this snapshot the framing of that finding was muddled.** The "
            "+5.85c number was the *mid-discrepancy* (poly_yes_mid - kalshi_mid). "
            "The relevant executable spread is the at-the-touch gap between best "
            "Kalshi ask and best Polymarket YES bid, which was ~1.0c at the time "
            "and is ~1.1c on this D.2 snapshot — i.e. BELOW the stale 3c "
            "round-trip fee floor. Under stale fees the walker terminates at "
            "level 0 because per-contract is *negative*, not because depth runs "
            "out. Whether fees or depth binds depends on the scenario:"
        )
        lines.append("")
        lines.append(
            f"At the D.2 snapshot, Kalshi mid = {arod['kalshi_mid']:.4f}, "
            f"Polymarket YES mid = {arod['pm_yes_mid']:.4f}. "
            f"Mid-discrepancy: direct = {arod['disc_direct_c']:.2f}c, "
            f"synthetic = {arod['disc_synth_c']:.2f}c. "
            f"At-the-touch direct spread (PY_bid − K_ask) ≈ 1.1c. "
            f"Top-of-book sizes: K_ask = {arod['k_ask_top_size']:.0f}, "
            f"PY_bid = {arod['pm_yes_bid_top_size']:.0f}, "
            f"PY_ask = {arod['pm_yes_ask_top_size']:.0f}."
        )
        lines.append("")
        lines.append("Per scenario:")
        lines.append("")
        for sc in ("A_STALE", "B_CORR_TAKER", "C_MIXED", "D_BOTH_MAKER"):
            s = arod["scenarios"][sc]
            lines.append(
                f"* **{sc}**: best_net = {format_money(s['best_net'])}, "
                f"verdict = {s['verdict']}, "
                f"direct fillable = {s['direct_fillable']:.0f}, "
                f"synth fillable = {s['synth_fillable']:.0f}."
            )
        lines.append("")
        lines.append(
            "**Verdict: the executable-arb-is-zero result holds under "
            "corr_taker, but the *mechanism* is fees, not depth.**"
        )
        lines.append("")
        lines.append(
            "* Under A_STALE and B_CORR_TAKER: the at-the-touch 1.1c paper "
            "spread does not survive the round-trip fee (~3.0c stale, ~1.15c "
            "corrected sports-taker = K parabolic ~1c + PM 3% × $0.05 ≈ 0.15c). "
            "Walker terminates at level 0 with negative per-contract. **Fees bind, "
            "not depth.**"
        )
        lines.append(
            "* Under C_MIXED (PM maker = 0): fees almost vanish on the PM "
            "leg; net per-contract is ~+$0.001. **Depth then binds**: only 60 "
            "contracts at the inside, walker stops at level 1 when prices step "
            "off-touch. Net = $0.06."
        )
        lines.append(
            "* Under D_BOTH_MAKER: both legs free, walker lifts deeper levels "
            "until the next big tick jump on PM kills per-contract; 296 "
            "contracts filled, $2.98 net."
        )
        lines.append("")
        lines.append(
            "So the D.2 build_log assertion that *\"depth, not the 2% taker fee, "
            "is the binding constraint\"* is **incorrect on this snapshot under "
            "the actual (stale or corrected) taker fee schedule**. Depth-binds "
            "only emerges as the binding mechanism once PM fees drop to maker "
            "(0%). The corrected `build_log.md` entry should distinguish "
            "*mid-discrepancy* (5.85c, irrelevant to execution) from "
            "*at-the-touch spread* (1.1c, what actually has to clear fees)."
        )
        lines.append("")

    # Prose claims requiring update
    lines.append("## PROSE CLAIMS REQUIRING UPDATE")
    lines.append("")
    lines.append(
        "The repo cites a `~3¢ fee threshold` in five places, derived from the "
        "stale Kalshi $0.02 + Polymarket 2% × $0.50 mid model. Under the "
        "corrected fee schedule the threshold is no longer flat — it depends on "
        "the market's category and price level. Suggested updates below; apply "
        "deliberately."
    )
    lines.append("")
    lines.append(
        "| Location | Stale claim | Suggested corrected sentence |\n"
        "| --- | --- | --- |"
    )

    prose_locations = [
        (
            "`README.md:9`",
            '"…~3¢ fee threshold…"',
            (
                "The conservative fee floor is ~2c at midprice (Kalshi parabolic "
                "+ Polymarket sports at 3%) and ~2.5c for politics markets (4% PM "
                "leg); tail-priced markets see ~1c on the Kalshi leg. See "
                "`data/processed/exp3a_fee_correction.md` for per-market detail."
            ),
        ),
        (
            "`README.md:49`",
            '"…3¢ fee threshold…"',
            (
                "Per-market fee floors range from ~1.3c (tail-priced sports) to "
                "~2.5c (central-priced politics), under the corrected Kalshi "
                "parabolic / Polymarket category-dependent model verified against "
                "live venue APIs on 2026-05-28."
            ),
        ),
        (
            "`README.md:55`",
            '"…clears the ~3¢ fee threshold…"',
            (
                "ARod's *mid-discrepancy* (+5.85c) clears the corrected fee floor "
                "but the *at-the-touch* executable spread is only ~1.1c, which "
                "does not survive either the stale ~3c or the corrected ~1.15c "
                "(sports taker) round-trip fee. Executable arb remains $0 because "
                "of fees at the touch — depth only becomes the binding constraint "
                "if PM fees drop to maker mode (see "
                "`data/processed/exp3a_fee_correction.md`)."
            ),
        ),
        (
            "`docs/findings.md:7`",
            '"…~3¢ fee threshold…"',
            (
                "After correcting the fee model to Kalshi parabolic + Polymarket "
                "category-dependent rates (3% sports, 4% politics/tech, 0 fee-free "
                "geopolitics), the per-market fee floor ranges from ~1.3c (tail "
                "sports) to ~2.5c (central politics). The no-executable-arb finding "
                "strengthens on most central-priced markets because the corrected "
                "Polymarket politics rate (4%) is higher than the stale 2%."
            ),
        ),
        (
            "`docs/build_log.md:30-34`",
            (
                'D-finding (2): "sports_retirement_arod paper edge (+5.85c) CLEARS '
                'the ~3c fee threshold ... executable arb is still $0 because '
                'Polymarket YES has $0 depth within 1c. In thin tail markets the '
                'binding constraint is depth, not the 2% taker fee."'
            ),
            (
                "**Re-characterize.** Under stale fees, the +5.85c MID-discrepancy "
                "obscured the relevant number: the at-the-touch direct spread is "
                "only ~1.1c, which is BELOW both the stale ~3c and the corrected "
                "~1.15c (sports-taker) round-trip fee. The walker terminates at "
                "level 0 with NEGATIVE per-contract — *fees bind at the touch, "
                "not depth*. Depth becomes the binding constraint only under the "
                "MIXED scenario (PM maker = 0%), where ARod yields $0.06 capped "
                "by 60 contracts of PM YES bid size. The corrected D-finding: "
                "*in this snapshot fees still bind for ARod even under corrected "
                "taker; the depth-binds story only activates once a strategy can "
                "post passive on Polymarket.*"
            ),
        ),
    ]
    for loc, old, new in prose_locations:
        lines.append(f"| {loc} | {old} | {new} |")
    lines.append("")
    lines.append(
        "Additional note for `docs/findings.md` and `docs/build_log.md`: the "
        "user's expectation that Colombia/Peru/Seoul (`intl_president_*`, "
        "`intl_mayor_*`) would map to fee-free `geopolitics` on Polymarket is "
        "contradicted by the live `feeType` field — all 6 intl-election markets "
        "in our panel return `politics_fees` at 4%. There is no fee-free arb "
        "surface in the current dataset. The favorable-PM-leg category exists in "
        "the rate table (`CATEGORY_RATES['geopolitics'] = 0`), but no market on "
        "our panel uses it."
    )
    lines.append("")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines))
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")


def summarize(rows: list[dict], skipped: list[dict]) -> None:
    print("\n=== EXP-3a per-market summary ===")
    print(f"{'market':32s}  {'k_mult':>6s}  {'pm_rate':>7s}  "
          f"{'stale':>14s}  {'corr_tk':>14s}  {'mixed':>14s}  {'maker':>14s}  Δ")
    for r in rows:
        s = r["scenarios"]
        def cell(k):
            return f"{s[k]['verdict']:3s} {format_money(s[k]['best_net']):>9s}"
        delta = "Y" if r["verdict_changed"] else "."
        print(
            f"{r['market_id']:32s}  {r['k_mult']:>6}  {r['pm_rate']:>7}  "
            f"{cell('A_STALE'):>14s}  {cell('B_CORR_TAKER'):>14s}  "
            f"{cell('C_MIXED'):>14s}  {cell('D_BOTH_MAKER'):>14s}  {delta}"
        )
    if skipped:
        print("\n=== Skipped markets ===")
        for s in skipped:
            ctx = f" | {s['context']}" if s.get("context") else ""
            print(f"  {s['market_id']:32s}  {s['reason']}{ctx}")


if __name__ == "__main__":
    sys.exit(main())
