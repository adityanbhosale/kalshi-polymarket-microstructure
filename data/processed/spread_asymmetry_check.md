# Spread-asymmetry diagnostic — Kalshi tick floor vs reconstruction vs genuine width

Generated: 2026-05-28T02:42:36.237293+00:00
Source: live Kalshi `/markets/{ticker}` + `/markets/{ticker}/orderbook` and Polymarket CLOB `get_orderbook(token_id)` for 5 picks.

Definitions:
- `mid` = (best_bid + best_ask) / 2 from the raw Kalshi orderbook
  (after the `ask = 1 − best_NO_bid` reconstruction in `normalize.py`).
- `kalshi_tick` = `step` of the `price_ranges` band that contains `mid`.
- `tick_floor_bps` = (kalshi_tick / mid) × 10000 — the bps spread you
  *must* observe even with one side resting at the next tick.
- `K_spread_bps` = (best_ask − best_bid) / mid × 10000 (from raw book).
- `excess_bps` = K_spread_bps − tick_floor_bps. 0 means the book is
  one tick wide (the floor); positive means there are missing levels
  between best bid and best ask (genuine width).
- `reconstruction_ok` = does `1 − max(no_dollars price)` equal
  `yes_ask_dollars` from the same `/markets/{ticker}` response, to within 0.0001? (Spot-checks the complementarity logic.)

## Summary

| market | mid | kalshi_tick | tick_floor_bps | K_spread_bps | excess_bps | reconstruction_ok |
|---|---:|---:|---:|---:|---:|:---:|
| `nba_finals_okc` | 0.5650 | $0.0100 | 177 | 177 | 0 | Y |
| `nba_finals_nyk` | 0.2950 | $0.0100 | 339 | 339 | 0 | Y |
| `nba_finals_sas` | 0.1450 | $0.0100 | 690 | 690 | 0 | Y |
| `sports_retirement_kelce` | 0.0450 | $0.0100 | 2222 | 6667 | 4444 | Y |
| `intl_president_pe_rpal` | 0.2850 | $0.0100 | 351 | 351 | 0 | Y |

**Conclusion**: **Mostly tick-mechanical, with one exception.** The asymmetry is dominated by Kalshi's coarser tick grid for `nba_finals_okc`, `nba_finals_nyk`, `nba_finals_sas`, `intl_president_pe_rpal` (excess_bps ≈ 0). However, `sports_retirement_kelce` carry genuine book width beyond the 1-tick floor (excess_bps = 4444), indicating real maker scarcity at low prices, not a reconstruction artifact.

Reconstruction (`ask = 1 − best_NO_bid`) matches the API's explicitly-reported best bid/ask within $0.0001 on every sampled book, so no part of the asymmetry is normalize.py's doing.

---

## Per-market detail

## `nba_finals_okc` (Kalshi `KXNBA-26-OKC`)

- price_level_structure: `linear_cent`  | price_ranges: `[{'end': '1.0000', 'start': '0.0000', 'step': '0.0100'}]`
- API top-level: yes_bid=0.5600 yes_ask=0.5700  no_bid=0.4300 no_ask=0.4400
- raw `yes_dollars` (top 5 BIDS, sorted asc by price): [['0.0100', '5417169.17'], ['0.0200', '6666.00'], ['0.0300', '6.86'], ['0.0400', '49.42'], ['0.0500', '5.00']]
- raw `no_dollars`  (top 5 BIDS, sorted asc by price): [['0.0100', '7020386.85'], ['0.0200', '205691.84'], ['0.0300', '400.64'], ['0.0400', '178.00'], ['0.0500', '615397.65']]

Reconstructed (matches `normalize_kalshi_orderbook`):  YES bid=0.5600 ask=0.5700 (=1−0.4300)  | NO bid=0.4300 ask=0.4400 (=1−0.5600)
- reconstruction `1 − best_NO_bid` = 0.5700 vs API `yes_ask_dollars` = 0.5700 → |Δ|=0.0000 → **Y**
- mid=0.5650  kalshi_tick=$0.0100  tick_floor_bps=177  K_spread_bps=177  excess_bps=0
- Polymarket YES raw: bid=0.5700 ask=0.5800 (spread_bps=174; tick floor at $0.001 ⇒ 17 bps)
- Polymarket NO  raw: bid=0.4200 ask=0.4300

## `nba_finals_nyk` (Kalshi `KXNBA-26-NYK`)

- price_level_structure: `linear_cent`  | price_ranges: `[{'end': '1.0000', 'start': '0.0000', 'step': '0.0100'}]`
- API top-level: yes_bid=0.2900 yes_ask=0.3000  no_bid=0.7000 no_ask=0.7100
- raw `yes_dollars` (top 5 BIDS, sorted asc by price): [['0.0100', '4658009.72'], ['0.0200', '13505.56'], ['0.0300', '27805.84'], ['0.0400', '50000.00'], ['0.0500', '319235.34']]
- raw `no_dollars`  (top 5 BIDS, sorted asc by price): [['0.0100', '8160071.38'], ['0.0200', '310550.82'], ['0.0300', '440.39'], ['0.0400', '16848.12'], ['0.0500', '1107541.57']]

Reconstructed (matches `normalize_kalshi_orderbook`):  YES bid=0.2900 ask=0.3000 (=1−0.7000)  | NO bid=0.7000 ask=0.7100 (=1−0.2900)
- reconstruction `1 − best_NO_bid` = 0.3000 vs API `yes_ask_dollars` = 0.3000 → |Δ|=0.0000 → **Y**
- mid=0.2950  kalshi_tick=$0.0100  tick_floor_bps=339  K_spread_bps=339  excess_bps=0
- Polymarket YES raw: bid=0.2850 ask=0.2860 (spread_bps=35; tick floor at $0.001 ⇒ 35 bps)
- Polymarket NO  raw: status=404_delisted (skipped)

## `nba_finals_sas` (Kalshi `KXNBA-26-SAS`)

- price_level_structure: `linear_cent`  | price_ranges: `[{'end': '1.0000', 'start': '0.0000', 'step': '0.0100'}]`
- API top-level: yes_bid=0.1400 yes_ask=0.1500  no_bid=0.8500 no_ask=0.8600
- raw `yes_dollars` (top 5 BIDS, sorted asc by price): [['0.0100', '3648824.26'], ['0.0200', '11482.00'], ['0.0300', '252386.00'], ['0.0400', '43945.00'], ['0.0500', '144298.90']]
- raw `no_dollars`  (top 5 BIDS, sorted asc by price): [['0.0100', '11258514.27'], ['0.0200', '2400.98'], ['0.0300', '20791.88'], ['0.0400', '288.58'], ['0.0500', '861.49']]

Reconstructed (matches `normalize_kalshi_orderbook`):  YES bid=0.1400 ask=0.1500 (=1−0.8500)  | NO bid=0.8500 ask=0.8600 (=1−0.1400)
- reconstruction `1 − best_NO_bid` = 0.1500 vs API `yes_ask_dollars` = 0.1500 → |Δ|=0.0000 → **Y**
- mid=0.1450  kalshi_tick=$0.0100  tick_floor_bps=690  K_spread_bps=690  excess_bps=0
- Polymarket YES raw: bid=0.1450 ask=0.1470 (spread_bps=137; tick floor at $0.001 ⇒ 68 bps)
- Polymarket NO  raw: bid=0.8530 ask=0.8550

## `sports_retirement_kelce` (Kalshi `KXKELCERETIRE-26`)

- price_level_structure: `linear_cent`  | price_ranges: `[{'end': '1.0000', 'start': '0.0000', 'step': '0.0100'}]`
- API top-level: yes_bid=0.0300 yes_ask=0.0600  no_bid=0.9400 no_ask=0.9700
- raw `yes_dollars` (top 5 BIDS, sorted asc by price): [['0.0100', '13219.00'], ['0.0300', '250.00']]
- raw `no_dollars`  (top 5 BIDS, sorted asc by price): [['0.0100', '1211.00'], ['0.0200', '60.00'], ['0.3100', '74.09'], ['0.3900', '1605.00'], ['0.7600', '1.00']]

Reconstructed (matches `normalize_kalshi_orderbook`):  YES bid=0.0300 ask=0.0600 (=1−0.9400)  | NO bid=0.9400 ask=0.9700 (=1−0.0300)
- reconstruction `1 − best_NO_bid` = 0.0600 vs API `yes_ask_dollars` = 0.0600 → |Δ|=0.0000 → **Y**
- mid=0.0450  kalshi_tick=$0.0100  tick_floor_bps=2222  K_spread_bps=6667  excess_bps=4444
- Polymarket YES raw: bid=0.0260 ask=0.0270 (spread_bps=377; tick floor at $0.001 ⇒ 377 bps)
- Polymarket NO  raw: bid=0.9730 ask=0.9740

## `intl_president_pe_rpal` (Kalshi `KXPERUPRES-26-RPAL`)

- price_level_structure: `tapered_deci_cent`  | price_ranges: `[{'end': '0.1000', 'start': '0.0000', 'step': '0.0010'}, {'end': '0.9000', 'start': '0.1000', 'step': '0.0100'}, {'end': '1.0000', 'start': '0.9000', 'step': '0.0010'}]`
- API top-level: yes_bid=0.2800 yes_ask=0.2900  no_bid=0.7100 no_ask=0.7200
- raw `yes_dollars` (top 5 BIDS, sorted asc by price): [['0.0010', '250000.00'], ['0.0020', '125.00'], ['0.0100', '602.00'], ['0.0130', '600.00'], ['0.0140', '170.00']]
- raw `no_dollars`  (top 5 BIDS, sorted asc by price): [['0.0010', '564064.06'], ['0.0100', '250.00'], ['0.0370', '1750.00'], ['0.0440', '7000.00'], ['0.0450', '400.00']]

Reconstructed (matches `normalize_kalshi_orderbook`):  YES bid=0.2800 ask=0.2900 (=1−0.7100)  | NO bid=0.7100 ask=0.7200 (=1−0.2800)
- reconstruction `1 − best_NO_bid` = 0.2900 vs API `yes_ask_dollars` = 0.2900 → |Δ|=0.0000 → **Y**
- mid=0.2850  kalshi_tick=$0.0100  tick_floor_bps=351  K_spread_bps=351  excess_bps=0
- Polymarket YES raw: bid=0.2700 ask=0.2710 (spread_bps=37; tick floor at $0.001 ⇒ 37 bps)
- Polymarket NO  raw: bid=0.7290 ask=0.7300

