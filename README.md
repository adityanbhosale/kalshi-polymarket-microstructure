# kalshi-polymarket-microstructure-analysis

This is an empirical cross-venue microstructure analysis of prediction markets on Kalshi and Polymarket. I curated a dataset of 3 NBA Finals 2026 markets ($110M combined open interest). Four timestamped snapshots demonstrate cross-venue price convergence, and conservative fee modeling shows zero executable arb survives realistic transaction costs.

![OKC cross-venue discrepancy decay](data/processed/fig_okc_convergence.png)

## Headline findings

**1. Paper discrepancies are real but small.** Across the three curated NBA Finals markets, observed cross-venue mid-price discrepancies ranged from 0.0¢ to 1.0¢. These exist at the level of fair-value disagreement between venues but are well below the conservative fee threshold. No takeable cross-venue arb exists at any accessible fee tier on Kalshi/Polymarket. Under corrected fees (Kalshi parabolic 7¢×C×(1−C), Polymarket category-dependent 3-4%), 0 of 15 markets show takeable arb. Direction-enforced maker scenarios show 8 markets with provideable spread, but capturing it requires resting passive and waiting for incoming flow — an LP edge, not an arb edge. A counterfactual sweep finds that takeable arb would appear at ~0.30% taker / 0.20% maker rebate fees (8 markets, ~$73/snapshot), but neither venue offers this tier to any market participant as of 2026-05-28.



**2. Cross-venue prices converge observably without explicit arb.** The OKC market's paper discrepancy decayed from 1.00¢ → 0.50¢ → 0.00¢, then held at 0.00¢ across a second confirming snapshot, over ~22 hours total (see hero figure above). No executable arb fired during this period — paper edge never exceeded the fee threshold — yet the venues equilibrated to identical mids and stayed there. Market makers on at least one venue are paying attention to the other.

**3. Polymarket exhibits venue-specific responses to news shocks and resolution proximity.** The three NBA Finals championship-futures markets in the dataset displayed three different Polymarket states by 2026-05-26: OKC YES remains a fully active book with both sides priced near the midpoint (~0.45) — the Thunder are mid-series in the Western Conference Finals, with their path to the Finals genuinely uncertain. NYK YES has entered "lighthouse mode" — the book is structurally active (125+ bids, 90+ asks) but quotes have collapsed to the extremes (best_bid 0.001 / best_ask 0.999) following the Knicks' clinch of the Eastern Conference Finals earlier in the day; Polymarket market-makers appear to have temporarily withdrawn meaningful quotes during the rapid repricing of championship odds. NYK NO and CLE YES return 404 from the CLOB — fully delisted (the Cavaliers were eliminated by the Knicks in the ECF). The pattern reflects each market's current state: OKC's championship is undecided (active series), NYK's championship probability has just been freshly re-shocked by a major news event (post-clinch repricing), and CLE is post-elimination (resolution effectively known). Kalshi by contrast maintains active books with substantial boundary-stub liquidity on all three markets (NYK YES alone has 4.65M contracts bid at $0.01 and 8.15M NO bids at $0.01) and does not appear to delist outcomes structurally; the venues exhibit different conventions for how to quote during news-driven repricing and post-elimination intervals.

**4. Three distinct microstructure regimes in three markets of the same event series.** OKC presents as a clean cross-venue match — Western Conference Finals are mid-series (tied 2-2), both venues actively quoted at similar mids (~0.45), similar spreads. NYK presents as a post-clinch repricing case — the Knicks have just secured their Finals appearance (Game 6 of the ECF on 2026-05-26), and both venues are in temporary quote-collapse states as market-makers re-evaluate championship odds against TBD Finals opponents. Polymarket has parked quotes at boundary extremes (0.001/0.999); Kalshi maintains substantial boundary-stub liquidity at $0.01 on both sides, reflecting both venues' independent recognition that championship odds have shifted materially but are still uncertain. The simple midpoint computation reports both venues at $0.50 — degenerate by construction — but the structural finding is that both venues independently arrive at a similar quote-withdrawal response to news-driven repricing. CLE presents as a post-elimination tail-probability case — Polymarket has fully delisted YES (Cavaliers eliminated); Kalshi maintains a one-sided book with no YES bids at any price and a deep NO bid stack pricing the market at ~99.6% NO.

**5. The cross-venue universe is asymmetric beyond NBA Finals.** Discovery across four candidate categories (sports, macro/Fed, politics, crypto) surfaced bilateral high-volume markets in only one category. Kalshi has Fed/election/weather markets without Polymarket equivalents; Polymarket has tail-event cultural markets ("Trump out before GTA VI") without Kalshi equivalents. The asymmetry itself is a structural property of the current prediction-market landscape.

## Executable arb is zero

![Executable arb after fees](data/processed/fig_executable_zero.png)

For each of the three curated markets, both direct (YES vs YES) and synthetic (YES_Kalshi + NO_Polymarket) arb structures were computed by walking both venues' order books and applying conservative fees. Net profit was $0 across every market-structure combination — paper edge did not cross the spread + fee threshold at any observed snapshot.

This is not a negative result. The implication is that cross-venue value in prediction markets sits in observability, not arbitrage capture: the convergence in finding (2) and the lifecycle pattern in finding (3) are exactly the kinds of structural events a real-time cross-venue terminal exists to surface — and neither is recoverable from after-the-fact data analysis.

## Dataset

Three NBA Finals 2026 markets, cross-listed on Kalshi and Polymarket:

| Market | Kalshi ticker | Polymarket condition_id | Combined open interest |
|---|---|---|---|
| OKC wins | KXNBA-26-OKC | 0x22e7b5e3... | ~$32M |
| CLE wins | KXNBA-26-CLE | 0x6b44bd66... | ~$37M |
| NYK wins | KXNBA-26-NYK | 0x713641f7... | ~$41M |

Full mapping in `markets.yaml`. Curated 2026-05-25.

## Methodology

**Data sources.** Kalshi public market data (`/markets/{ticker}/orderbook`, no auth). Polymarket CLOB (`get_order_book`, no auth). Market discovery via Kalshi `/series` and Polymarket Gamma API.

**Snapshots.** Per-venue orderbook snapshots taken via `scripts/fetch_snapshot.py`; cross-venue arb computed via `scripts/compute_arb.py [--fresh]`. Each fresh run auto-appends a ledger entry to `data/processed/snapshot_ledger.yaml` for provenance.

**Normalization.** Kalshi's orderbook returns `yes_dollars` and `no_dollars` arrays (both bid-side). For comparability with Polymarket's two-token structure, both venues are normalized to a unified `NormalizedBook(bids, asks)` with asks reconstructed via complementarity (`ask_on_YES = 1 - bid_on_NO`). See `src/pm_micro/normalize.py`.

**Microstructure metrics.** Per book: best bid/ask, simple and size-weighted mids, absolute and relative spread, depth at top-of-book, depth within ±1¢ and ±5¢ of mid, populated price-level counts. See `src/pm_micro/microstructure.py`.

**Arb computation.** Three layers (paper mid-discrepancy, naive crossed-book, executable after fees) × two structures (direct, synthetic). Fee model uses live per-market API rates (Kalshi feeSchedule.rate, Polymarket feeType). Direction-enforced: maker fees only apply to add-side legs; cross-side legs pay taker regardless of execution mode. No maker rebate assumed by default (modeled as upside, off by default).

Fee model is calibrated to live API rates per market, both venues, both execution modes, with direction enforcement. Adverse-selection / queue-priority are NOT modeled — displayed depth is treated as exclusively fillable. This is the load-bearing remaining assumption on the LP-edge dollar figures.


See `src/pm_micro/arb.py`.

## Limitations

- **Snapshot sampling, not streaming.** Findings are based on a small number of timestamped fetches. Higher-frequency observation (sub-minute polling) would surface intraday patterns invisible to this study.
- **Single event series.** Three markets is enough for cross-venue comparison but not for venue-level generalization. The discovery work in finding (5) suggests the universe of cross-venue-eligible markets is small enough that scaling N would not change the headline conclusions, but this isn't tested.
- **Fee model is conservative, not calibrated.** No maker rebates, no volume tiers, no Kalshi market-maker programs. Real trader-realized fees may meaningfully change the executable-arb math.
- **No latency model.** Real cross-venue execution faces routing latency, partial-fill risk, and quote staleness. The book-walk computation assumes simultaneous fills at observed prices.

## Errata

This section documents a data-integrity bug discovered and corrected during pre-publication verification. It is preserved here because the discovery process is itself part of the research record.

During Phase 2 curation (2026-05-25), the NYK entry in `markets.yaml` was populated from a truncated terminal screenshot. The Polymarket `condition_id`, `yes_token_id`, and `no_token_id` were each stored as 14-character literals ending in `...` (e.g., `"20257190540..."` rather than the full 77-character `"20257190540739490630509657713144742134547949967093643458458133445357169845406"`). This was missed in the Phase 2 validation step, which only verified that `yaml.safe_load` parsed without error and that orderbook fetches returned *something*.

As a result, every NYK Polymarket query from Phase 3 onward returned a 404 from the CLOB (Polymarket silently 404s on malformed token IDs rather than raising a distinct error). The initial Phase 5 writeup interpreted those 404s as Polymarket withdrawing liquidity from the NYK market. The actual cause was a malformed query; the NYK YES book was queryable throughout under the correct token ID.

The bug was discovered on 2026-05-26 during a pre-email verification pass that re-fetched canonical token IDs via the Polymarket Gamma API and compared them against the stored values. `markets.yaml` was corrected (commit e8ff31c), `compute_arb.py --fresh` was re-run, and the figures were regenerated. Finding (3) was rewritten to reflect the actual Polymarket lifecycle pattern (active / lighthouse / delisted) rather than the artifact-driven "withdrew NYK liquidity" claim. Finding (4) was rewritten to characterize NYK as a post-elimination lighthouse case rather than a wide-spread asymmetry case. The OKC convergence finding (finding 2 and the hero figure) was unaffected.

The methodological takeaway: cross-venue analysis on platforms that 404 on malformed identifiers requires explicit token-ID length validation at curation time. A simple `assert len(token_id) == 77` in the curation step would have caught this in Phase 2.

A separate framing error in the original Phase 5 writeup characterized NYK's lighthouse-mode book as resulting from team elimination. This was corrected on 2026-05-26 after verification against the actual NBA playoff schedule: the Knicks were not eliminated — they had just clinched their NBA Finals appearance via a Game 6 ECF victory over the Cavaliers. The lighthouse-mode observation was real, but its cause was post-clinch news-shock repricing rather than post-elimination resolution-approach. Findings (3) and (4) were updated accordingly. The Cavaliers — eliminated by the Knicks — are the actual post-elimination market in the dataset, and the CLE finding (Polymarket fully delisted, Kalshi at tail probability) is correctly characterized.

## Repo structure

```
src/pm_micro/         analysis library (normalize, microstructure, arb)
  clients/            thin venue clients (kalshi, polymarket)
scripts/              fetch_snapshot.py, compute_arb.py
notebooks/            00 pipeline validation, 01 mapping, 02 microstructure,
                      03 cross-venue, 04 writeup figures
data/raw/             timestamped orderbook snapshots (gitignored)
data/processed/       CSVs, figures, snapshot ledger
tests/                normalize + arb unit tests (6 total)
markets.yaml          curated cross-venue mapping
docs/findings.md      prose narrative of the findings
```

## Setup

```bash
uv sync
uv run pytest tests/ -v
uv run python scripts/fetch_snapshot.py
uv run python scripts/compute_arb.py --fresh
uv run jupyter notebook notebooks/03_cross_venue.ipynb
```
