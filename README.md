# kalshi-polymarket-microstructure

Empirical cross-venue microstructure analysis of prediction markets on Kalshi and Polymarket. Curated dataset of 3 NBA Finals 2026 markets ($110M combined open interest). Four timestamped snapshots demonstrate cross-venue price convergence; conservative fee modeling shows zero executable arb survives realistic transaction costs.

![OKC cross-venue discrepancy decay](data/processed/fig_okc_convergence.png)

## Headline findings

**1. Paper discrepancies are real but small.** Across the three curated NBA Finals markets, observed cross-venue mid-price discrepancies ranged from 0.0¢ to 1.0¢. These exist at the level of fair-value disagreement between venues but are well below the conservative fee threshold (~3¢ all-in for a 50¢ contract: $0.02/contract Kalshi execution + 2% Polymarket taker).

**2. Cross-venue prices converge observably without explicit arb.** The OKC market's paper discrepancy decayed from 1.00¢ → 0.50¢ → 0.00¢, then held at 0.00¢ across a second confirming snapshot, over ~22 hours total (see hero figure above). No executable arb fired during this period — paper edge never exceeded the fee threshold — yet the venues equilibrated to identical mids and stayed there. Market makers on at least one venue are paying attention to the other.

**3. Liquidity provision is venue-specific and time-varying.** The NYK (New York Knicks) market exhibited active Polymarket books on the initial snapshot (132 bid levels, 97 ask levels, $16M open interest) but returned 404 from Polymarket's CLOB ~24 hours later. The CLE (Cleveland Cavaliers) Polymarket book followed the same trajectory: active during the Phase 3 snapshot (138 levels deep on both sides at ~0.4% pricing), then 404 by the final fresh fetch. Kalshi maintained active books on all three markets throughout. The NYK NO token was 404 across all snapshots — Polymarket appears to de-list books during the resolution approach, and that de-listing is asymmetric across venues.

**4. Three distinct microstructure regimes in three markets of the same event series.** OKC presents as a clean cross-venue match (similar mids, similar spreads). NYK presents as a wide-spread, asymmetric-liquidity case (Kalshi spread 769 bps vs Polymarket 39 bps; ~20× venue disparity). CLE presents as a tail-probability one-sided book (Kalshi YES has zero bids at any price; Polymarket priced CLE at ~0.4% probability while its book was still listed).

**5. The cross-venue universe is asymmetric beyond NBA Finals.** Discovery across four candidate categories (sports, macro/Fed, politics, crypto) surfaced bilateral high-volume markets in only one category. Kalshi has Fed/election/weather markets without Polymarket equivalents; Polymarket has tail-event cultural markets ("Trump out before GTA VI") without Kalshi equivalents. The asymmetry itself is a structural property of the current prediction-market landscape.

## Executable arb is zero

![Executable arb after fees](data/processed/fig_executable_zero.png)

For each of the three curated markets, both direct (YES vs YES) and synthetic (YES_Kalshi + NO_Polymarket) arb structures were computed by walking both venues' order books and applying conservative fees. Net profit was $0 across every market-structure combination — paper edge did not cross the spread + fee threshold at any observed snapshot.

This is not a negative result. The implication is that cross-venue value in prediction markets sits in observability, not arbitrage capture: the convergence in finding (2) and the liquidity withdrawal in finding (3) are exactly the kinds of structural events a real-time cross-venue terminal exists to surface — and neither is recoverable from after-the-fact data analysis.

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
