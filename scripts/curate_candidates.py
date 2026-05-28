"""Categorize and annotate the 92 high-confidence candidates from
discovery_candidates.md for human-readable manual selection.

Reads ``data/processed/discovery_candidates.md`` (the source of truth from
discovery), drops the score-<0.5 "uncertain" tail, then for each remaining
row attaches:
  * ``category``: one of {Sports, Politics, Macro, Crypto, Cultural/Tail}
    derived from the Kalshi ticker prefix (and a small list of explicit
    ticker overrides for Trump/M&A markets that don't fit the prefix rule).
  * ``match_type``: one of {same_event, same_race_diff_side,
    shared_entity_only, shared_domain_only, shared_date_only, ambiguous},
    determined by hand-reading every row's kalshi_event/polymarket_question
    pair. The lookup is per-ticker; updating discovery without updating this
    script will fall back to ``ambiguous`` for unrecognized tickers.

Sort order in the output: by category (display order: Sports, Politics,
Macro, Crypto, Cultural/Tail), then by match_type within category
(same_event first), then by combined_vol_k descending.

Usage: ``uv run python scripts/curate_candidates.py``
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SRC = REPO_ROOT / "data" / "processed" / "discovery_candidates.md"
DST = REPO_ROOT / "data" / "processed" / "discovery_curated.md"

CATEGORY_ORDER = (
    "Sports",
    "Politics",
    "Macro",
    "Crypto",
    "Cultural / Tail-event",
)

MATCH_TYPE_ORDER = (
    "same_event",
    "same_race_diff_side",
    "shared_entity_only",
    "shared_domain_only",
    "shared_date_only",
    "ambiguous",
)

# --- Category by ticker (prefix or explicit) ---------------------------
SPORTS_TICKERS = {
    "KXKELCERETIRE-26",
    "KXARODGRETIRE-26",
    "KXLBJRETIRE-26",
}
SPORTS_PREFIXES = ("KXNBA-",)

CULTURAL_PREFIXES = (
    "KXTRUMPATTEND",
    "KXTRUMPNBAFINALS",
    "KXTRUMPBALLROOM",
    "KXTRUMPUFC",
    "KXTAKEOVERACQWB",
)

# Macro / financial / corporate-numerical Kalshi series.
MACRO_PREFIXES = (
    "KXUSDBRLMAX",
    "KXFM30YMTG",
    "KXTARIFFCHECKS",
    "KXCOREUND",
    "KXCHAICUTS",
    "KXCOST-",
    "KXTSLA-",
    "KXECONSTATCPI",
    "KXECONSTATCORECPIYOY",
    "KXDEFGDP",
    "KXNFPROD",
)


def assign_category(ticker: str) -> str:
    t = ticker.upper()
    if t in SPORTS_TICKERS or any(t.startswith(p) for p in SPORTS_PREFIXES):
        return "Sports"
    if any(t.startswith(p) for p in CULTURAL_PREFIXES):
        return "Cultural / Tail-event"
    if any(t.startswith(p) for p in MACRO_PREFIXES):
        return "Macro"
    # No Crypto-prefixed Kalshi series in this discovery batch.
    return "Politics"


# --- Per-row match_type ------------------------------------------------
# Each entry was set by hand-reading the (kalshi_event, polymarket_question)
# pair in the source markdown. Updating discovery without updating this map
# falls back to "ambiguous".
MATCH_TYPE: dict[str, str] = {
    # Sports
    "KXKELCERETIRE-26":            "same_event",
    "KXARODGRETIRE-26":            "same_event",
    "KXLBJRETIRE-26":              "shared_domain_only",  # PM = government shutdown
    "KXNBA-26-OKC":                "same_event",
    "KXNBA-26-SAS":                "same_event",
    "KXNBA-26-NYK":                "shared_domain_only",  # PM = NY governor

    # Politics — same_event (Kalshi + PM quote the same outcome)
    "KXCOLOMBIAPRESR1-26MAY31-ICAS": "same_event",       # both 1st round / ICAS
    "KXCOLOMBIAPRES-26-AESP":      "same_event",
    "KXCOLOMBIAPRES-26-PVAL":      "same_event",
    "KXPERUPRES-26-RPAL":          "same_event",
    "KXPERUPRES-26-KFUJ":          "same_event",
    "KXAKSENATE-26NOV03-MPEL":     "same_event",
    "KXSEOULMAYOR-26JUN03-OSEH":   "same_event",
    "KXMAYORLA-26-SPRA":           "same_event",
    "KXMAYORLA-26-NRAM":           "same_event",
    "KXMAYORLA-26-AMIL":           "same_event",
    "KXMAYORLA-26-RCAR":           "same_event",
    "KXMAYORLA-26-KBAS":           "same_event",
    "KXMAYORLA-26-RHUA":           "same_event",

    # Politics — shared_entity_only (same person, different stage of the race)
    # CA gov primary (Kalshi) vs CA gov general (Polymarket)
    "KXGOVCAPRIMARY-26-XBEC":      "shared_entity_only",
    "KXGOVCAPRIMARY-26-ESWA":      "shared_entity_only",
    "KXGOVCAPRIMARY-26-SHIL":      "shared_entity_only",
    "KXGOVCAPRIMARY-26-KPOR":      "shared_entity_only",
    "KXGOVCAPRIMARY-26-CBIA":      "shared_entity_only",
    "KXGOVCAPRIMARY-26-TSTE":      "shared_entity_only",
    # Colombia round-1 (Kalshi) vs Colombia full election (Polymarket)
    "KXCOLOMBIAPRESR1-26MAY31-PVAL": "shared_entity_only",
    "KXCOLOMBIAPRESR1-26MAY31-AESP": "shared_entity_only",
    # Colombia full election (Kalshi) vs Colombia round-1 (Polymarket)
    "KXCOLOMBIAPRES-26-ICAS":      "shared_entity_only",
    # LA mayor 1st round (Kalshi) vs full mayoral election (Polymarket)
    "KXLAMAYOR1R-26-SPRA":         "shared_entity_only",
    "KXLAMAYOR1R-26-NRAM":         "shared_entity_only",
    "KXLAMAYOR1R-26-KBAS":         "shared_entity_only",

    # Politics — shared_domain_only (broad election/Senate/etc. overlap only)
    "KXBERNIEENDORSE-26NOV03-JTAL":   "shared_domain_only",
    "KXCA11PRIMARY-26-SWIE":         "shared_domain_only",
    "KXCA11PRIMARY-26-CCHA":         "shared_domain_only",
    "KXCA11PRIMARY-26-SCHA":         "shared_domain_only",
    "KXAKSENATE-26NOV03-DSUL":       "shared_domain_only",
    "KXMAKERFIELDBY-27JAN01-LAB":    "shared_domain_only",
    "KXMAKERFIELDBY-27JAN01-RES":    "shared_domain_only",
    "KXSENATEDEMLEAD-28JAN01-CMUR":  "shared_domain_only",
    "KXSEOULMAYOR-26JUN03-CWON":     "shared_domain_only",
    "KXISRAELKNESSET-26-BEN":        "shared_domain_only",
    "KXIRANDEMOCRACY-27MAR01-T6":    "shared_domain_only",
    "KXHOUSEPOPVOTEMARGIN-27NOV03-B50": "shared_domain_only",
    "KXHOUSEPOPVOTEMARGIN-27NOV03-B1":  "shared_domain_only",
    "KXGOVCAPRIMARYPARTY-26-2D":     "shared_domain_only",
    "KXGOVCAPRIMARYPARTY-26-2R":     "shared_domain_only",
    "KXCA14SWINNER-26-AWAH":         "shared_domain_only",
    "KXCA14SWINNER-26-RSIN":         "shared_domain_only",
    "KXINSOSNOMR-26-DMOR":           "shared_domain_only",

    # Macro
    "KXUSDBRLMAX-26DEC31-T7.2499":   "shared_date_only",  # PM = XRP $5
    "KXUSDBRLMAX-26DEC31-T6.9999":   "shared_date_only",
    "KXUSDBRLMAX-26DEC31-T6.7499":   "shared_date_only",
    "KXUSDBRLMAX-26DEC31-T6.4999":   "shared_date_only",
    "KXUSDBRLMAX-26DEC31-T5.9999":   "shared_date_only",
    "KXFM30YMTG-26DEC31-T5.75":      "shared_entity_only",  # Freddie Mac PMMS vs FM IPO
    "KXTARIFFCHECKS-26-27":          "shared_domain_only",  # PM = Monero $1000
    "KXTARIFFCHECKS-26-JUN":         "shared_domain_only",
    "KXTARIFFCHECKS-26-JUL":         "shared_domain_only",
    "KXTARIFFCHECKS-26-AUG":         "shared_domain_only",
    "KXCOREUND-26DEC10-T2.2":        "shared_domain_only",  # CPI vs Fed funds
    "KXCHAICUTS-26JUN04-T1":         "shared_domain_only",
    "KXCOST-26MAYCARDS-150000000.0": "shared_domain_only",
    "KXCOST-26MAYCARDS-149000000.0": "shared_domain_only",
    "KXCOST-26MAYCARDS-147000000.0": "shared_domain_only",
    "KXTSLA-26JULPROD-440000.0":     "shared_domain_only",
    "KXTSLA-26JULPROD-420000.0":     "shared_domain_only",
    "KXTSLA-26JULDELIV-450000.0":    "shared_domain_only",
    "KXECONSTATCPICORE-26MAY-T0.5":  "shared_domain_only",
    "KXECONSTATCPICORE-26MAY-T0.3":  "shared_domain_only",
    "KXECONSTATCPICORE-26MAY-T0.0":  "shared_domain_only",
    "KXECONSTATCPICORE-26MAY-T-0.2": "shared_domain_only",
    "KXECONSTATCPICORE-26MAY-T-0.1": "shared_domain_only",
    "KXECONSTATCPI-26JUN-T0.0":      "shared_domain_only",
    "KXECONSTATCPI-26JUN-T-0.2":     "shared_domain_only",
    "KXECONSTATCPI-26JUN-T-0.1":     "shared_domain_only",
    "KXECONSTATCORECPIYOY-26JUL-T3.7": "shared_domain_only",
    "KXECONSTATCORECPIYOY-26JUL-T2.5": "shared_domain_only",
    "KXECONSTATCORECPIYOY-26JUL-T2.3": "shared_domain_only",
    "KXECONSTATCORECPIYOY-26JUL-T2.2": "shared_domain_only",
    "KXECONSTATCORECPIYOY-26JUN-T3.6": "shared_domain_only",
    "KXECONSTATCORECPIYOY-26JUN-T3.5": "shared_domain_only",
    "KXECONSTATCORECPIYOY-26JUN-T2.3": "shared_domain_only",
    "KXECONSTATCORECPIYOY-26JUN-T2.2": "shared_domain_only",
    "KXDEFGDP-26OCT20-T5":           "shared_domain_only",
    "KXNFPROD-27MAR04-T3":           "shared_domain_only",

    # Cultural / Tail-event
    "KXTRUMPATTEND":                "shared_domain_only",  # FIFA Final attend vs USA win
    "KXTRUMPNBAFINALS-26JUN-DJT":   "shared_domain_only",  # Trump@NBA vs Colombia pres
    "KXTRUMPUFC-26JUL-DJT":         "shared_domain_only",
    "KXTRUMPBALLROOM-28JAN01":      "shared_domain_only",
    "KXTAKEOVERACQWB-27JUN30-PSKY": "same_event",  # Paramount close WB
    "KXTAKEOVERACQWB-27JUN30-NFLX": "same_event",  # Netflix close WB
    "KXTAKEOVERACQWB-27JUN30-NONE": "shared_domain_only",  # PM = Ramp IPO
}


# --- Markdown parsing --------------------------------------------------
ROW_RE = re.compile(r"^\|\s*(?P<ticker>KX[^|]+?)\s*\|")
DOLLAR_RE = re.compile(r"\$([\d,]+)")


def _to_int_dollars(s: str) -> int:
    m = DOLLAR_RE.search(s or "")
    if not m:
        return 0
    return int(m.group(1).replace(",", ""))


def parse_candidates(md: str) -> list[dict]:
    """Extract candidate rows from the discovery markdown table."""
    out: list[dict] = []
    for line in md.splitlines():
        if not line.startswith("|") or "kalshi_ticker" in line or set(line) <= set("|-: "):
            continue
        if line.startswith("| _no candidates_"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 9:
            continue
        ticker = cells[0]
        if not ticker.startswith("KX"):
            continue
        try:
            score = float(cells[7])
        except ValueError:
            continue
        out.append({
            "ticker": ticker,
            "kalshi_event": cells[1],
            "polymarket_question": cells[2],
            "kalshi_vol": _to_int_dollars(cells[3]),
            "poly_vol": _to_int_dollars(cells[4]),
            "prob_bucket": cells[5],
            "days_to_resolution": cells[6],
            "match_score": score,
            "notes": cells[8],
        })
    return out


# --- Output formatting -------------------------------------------------
def _truncate(text: str, n: int) -> str:
    text = (text or "").replace("|", "\\|")
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _row_md(r: dict) -> str:
    combined_k = (r["kalshi_vol"] + r["poly_vol"]) / 1000.0
    days = r["days_to_resolution"]
    try:
        days_str = f"{float(days):.1f}"
    except (ValueError, TypeError):
        days_str = str(days)
    return (
        f"| `{r['ticker']}` "
        f"| {_truncate(r['kalshi_event'], 60)} "
        f"| {_truncate(r['polymarket_question'], 60)} "
        f"| `{r['match_type']}` "
        f"| `{r['prob_bucket']}` "
        f"| {combined_k:,.0f} "
        f"| {days_str} |"
    )


def _section_footer(rows: list[dict]) -> str:
    counts = Counter(r["match_type"] for r in rows)
    parts = []
    for mt in MATCH_TYPE_ORDER:
        n = counts.get(mt, 0)
        if n:
            parts.append(f"{n} {mt}")
    return "_" + ", ".join(parts) + "._" if parts else "_(empty)_"


def main() -> int:
    if not SRC.exists():
        print(f"❌ {SRC} not found", file=sys.stderr)
        return 1

    md = SRC.read_text(encoding="utf-8")
    all_rows = parse_candidates(md)

    # Drop the score < 0.5 tail per spec ("92 candidates").
    rows = [r for r in all_rows if r["match_score"] >= 0.5]

    # Annotate.
    unknown_tickers: list[str] = []
    for r in rows:
        r["category"] = assign_category(r["ticker"])
        mt = MATCH_TYPE.get(r["ticker"])
        if mt is None:
            mt = "ambiguous"
            unknown_tickers.append(r["ticker"])
        r["match_type"] = mt

    # Bucket and sort.
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    mt_rank = {mt: i for i, mt in enumerate(MATCH_TYPE_ORDER)}
    for cat_rows in by_cat.values():
        cat_rows.sort(
            key=lambda r: (mt_rank.get(r["match_type"], 99),
                           -(r["kalshi_vol"] + r["poly_vol"]))
        )

    # Render.
    lines: list[str] = []
    lines.append("# Discovery candidates — curated for manual review (D.1)\n")
    lines.append(
        f"_Source: `{SRC.relative_to(REPO_ROOT)}`. "
        f"{len(rows)} of {len(all_rows)} candidates retained "
        f"(dropped {len(all_rows) - len(rows)} flagged `uncertain` / score < 0.5)._\n"
    )
    lines.append("## How to read this\n")
    lines.append(
        "- `match_type` is hand-assigned by reading each row's "
        "`kalshi_event` ↔ `polymarket_question` pair (not derived from "
        "`match_score`). Values:"
    )
    lines.append(
        "  - `same_event` — both venues quote the same real-world outcome.\n"
        "  - `same_race_diff_side` — same race/contest, different candidates.\n"
        "  - `shared_entity_only` — share a candidate/team/asset name but "
        "ask different questions (e.g., primary vs general election with the "
        "same candidate).\n"
        "  - `shared_domain_only` — share category words only (e.g., generic "
        "\"Senate 2026\" / \"Republicans\" overlap).\n"
        "  - `shared_date_only` — coincide only on dates or generic terms "
        "(e.g., the USDBRL/XRP \"Dec 31, 2026\" pattern).\n"
        "  - `ambiguous` — cannot determine from the title alone."
    )
    lines.append(
        "- `combined_vol_k` = `(kalshi_vol + poly_vol) / 1,000` (USD, "
        "thousands), as a quick liquidity proxy.\n"
    )
    lines.append(
        "- Within each category, rows are sorted by `match_type` "
        "(`same_event` first) then by `combined_vol_k` descending.\n"
    )

    overall_counts: Counter[str] = Counter()
    for cat in CATEGORY_ORDER:
        cat_rows = by_cat.get(cat, [])
        lines.append(f"## {cat}\n")
        lines.append(
            "| kalshi_ticker | kalshi_event | polymarket_question | "
            "match_type | prob_bucket | combined_vol_k | days_to_resolution |"
        )
        lines.append("|---|---|---|---|---|---:|---:|")
        if not cat_rows:
            lines.append("| _no candidates_ | | | | | | |")
        else:
            for r in cat_rows:
                lines.append(_row_md(r))
        lines.append("")
        lines.append(_section_footer(cat_rows))
        lines.append("")
        overall_counts.update(r["match_type"] for r in cat_rows)

    lines.append("## Overall match_type distribution\n")
    for mt in MATCH_TYPE_ORDER:
        n = overall_counts.get(mt, 0)
        if n:
            lines.append(f"- `{mt}`: {n}")
    lines.append("")

    if unknown_tickers:
        lines.append("## Tickers without a hand-assigned match_type "
                     "(treated as `ambiguous`)\n")
        for tk in unknown_tickers:
            lines.append(f"- `{tk}`")
        lines.append("")

    DST.write_text("\n".join(lines), encoding="utf-8")

    # Console summary.
    print(f"Wrote {DST}")
    print(f"  rows curated: {len(rows)} (dropped {len(all_rows) - len(rows)} uncertain)")
    for cat in CATEGORY_ORDER:
        cat_rows = by_cat.get(cat, [])
        if not cat_rows:
            print(f"  {cat:<30} 0")
            continue
        cnts = Counter(r["match_type"] for r in cat_rows)
        bits = ", ".join(f"{cnts[mt]} {mt}" for mt in MATCH_TYPE_ORDER if cnts.get(mt))
        print(f"  {cat:<30} {len(cat_rows):>3} ({bits})")
    if unknown_tickers:
        print(f"  ⚠ {len(unknown_tickers)} tickers without explicit match_type:")
        for tk in unknown_tickers:
            print(f"    - {tk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
