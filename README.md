# kalshi-polymarket-microstructure

Cross-venue microstructure analysis of Kalshi and Polymarket prediction markets.

**Status:** Phase 1 (pipeline validation). Not yet ready for use.

## Setup

```bash
uv sync
uv run jupyter notebook notebooks/00_pipeline_validation.ipynb
```

## Structure

- `src/pm_micro/clients/` — thin venue clients (Kalshi, Polymarket)
- `notebooks/` — analysis notebooks
- `markets.yaml` — cross-venue market mapping (Phase 2)
- `data/` — raw and processed snapshots

## Phase plan

1. ✅ Pipeline validation — one orderbook from each venue
2. ⬜ Market mapping (curated set of cross-listed binary markets)
3. ⬜ Per-venue microstructure (spread, depth, mid)
4. ⬜ Cross-venue discrepancy + executable arb
5. ⬜ Writeup
