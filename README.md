# kalshi-polymarket-microstructure

Empirical cross-venue microstructure analysis of prediction markets on Kalshi and Polymarket. Curated dataset of 3 NBA Finals 2026 markets ($110M combined open interest). Four timestamped snapshots demonstrate cross-venue price convergence; conservative fee modeling shows zero executable arb survives realistic transaction costs.

![OKC cross-venue discrepancy decay](data/processed/fig_okc_convergence.png)

## Headline findings

**1. Paper discrepancies are real but small.** Across the three curated NBA Finals markets, observed cross-venue mid-price discrepancies ranged from 0.0¢ to 1.0¢. These exist at the level of fair-value disagreement between venues but are well below the conservative fee threshold (~3¢ all-in for a 50¢ contract: $0.02/contract Kalshi execution + 2% Polymarket taker).

**2. Cross-venue prices converge observably without explicit arb.** The OKC market's paper discrepancy decayed from 1.00¢ → 0.50¢ → 0.00¢, then held at 0.00¢ across a second confirming snapshot, over ~22 hours total (see hero figure above). No executable arb fired during this period — paper edge never exceeded the fee threshold — yet the venues equilibrated to identical mids and stayed there. Market makers on at least one venue are paying attention to the other.

**3. Polymarket exhibits a three-stage market lifecycle as resolution approaches.** All three NBA Finals markets in the dataset displayed different Polymarket states by 2026-05-26: OKC YES remains a fully active book with both sides priced near the midpoint (~0.45). NYK YES has entered "lighthouse mode" — the book is structurally active (125+ bids, 90+ asks) but quotes have collapsed to the extremes (best_bid 0.001 / best_ask 0.999), preserving boundary liquidity without meaningful pricing. NYK NO and CLE YES return 404 from the CLOB — fully delisted. The pattern tracks each market's distance to resolution: OKC's championship is undecided, NYK is effectively eliminated but not yet settled, CLE was always a tail-probability outcome. Kalshi by contrast maintains active books with substantial boundary-stub liquidity on all three markets (NYK YES alone has 4.65M contracts bid at $0.01 and 8.15M NO bids at $0.01) and does not appear to delist outcomes structurally; the venues exhibit different conventions for what to do with effectively-resolved-but-not-yet-settled markets.

**4. Three distinct microstructure regimes in three markets of the same event series.** OKC presents as a clean cross-venue match (similar mids, similar spreads, both venues actively quoted). NYK presents as a post-elimination lighthouse case: both venues have collapsed to boundary liquidity at the extremes (Polymarket 0.001/0.999, Kalshi YES bids at $0.01 with multi-million-contract sizes). The simple midpoint computation reports both venues at $0.50 — degenerate by construction — but the structural finding is that both venues independently arrive at the same response to a resolved-but-unsettled market. CLE presents as a tail-probability case: Polymarket has fully delisted YES; Kalshi maintains a one-sided book with no YES bids at any price and a deep NO bid stack pricing the market at ~99.6% NO.

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

**Arb computation.** Three layers (paper mid-discrepancy, naive crossed-book, executable after fees) × two structures (direct, synthetic). Fee model is intentionally conservative: 2% Polymarket taker fee (rebates ignored), $0.02/contract Kalshi all-in (CFTC + execution). Real fees may be lower with maker rebates or volume tiers. See `src/pm_micro/arb.py`.

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
