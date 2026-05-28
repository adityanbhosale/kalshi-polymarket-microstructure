# Event window analysis — `test_smoke`

- Catalyst (UTC): `2026-05-28T04:30:00+00:00`
- Pre-window:  2.0 h  →  `2026-05-28T02:30:00+00:00`
- Post-window: 1.0 h  →  `2026-05-28T05:30:00+00:00`
- Sources: dense `event_test_smoke_poll.csv` (216 rows) + 30 s baseline `timeofday_poll.csv` (2,944 rows)

Sign convention: `mid_disc_direct = poly_yes_mid − kalshi_yes_mid`, in cents. Positive ⇒ Polymarket pricing YES higher than Kalshi.

Lead-lag sign convention: `lag > 0` ⇒ Kalshi leads Polymarket; `lag < 0` ⇒ Polymarket leads Kalshi; lag = 0 ⇒ synchronous.

## Lead-lag (Kalshi YES vs Polymarket YES)

| market | best_lag (s) | best_corr | interp |
|---|---:|---:|---|
| `intl_president_co_aesp` | — | — | insufficient data |
| `intl_president_co_pval` | +0 | +0.821 | synchronous |
| `intl_president_r1_co_icas` | — | — | insufficient data |

## Discrepancy distribution: pre vs post catalyst

| market | n_pre | n_post | mean_pre (¢) | mean_post (¢) | std_pre (¢) | std_post (¢) | Δmean (¢) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `intl_president_co_aesp` | 51 | 13 | -3.000 | -3.000 | 0.000 | 0.000 | +0.000 |
| `intl_president_co_pval` | 51 | 13 | +0.374 | +0.415 | 0.242 | 0.138 | +0.042 |
| `intl_president_r1_co_icas` | 51 | 13 | +1.667 | +2.500 | 0.465 | 0.000 | +0.833 |

## Sample density inside the window

| market | event rows | baseline rows | combined snapshots |
|---|---:|---:|---:|
| `intl_president_co_aesp` | 72 | 184 | 64 |
| `intl_president_co_pval` | 72 | 184 | 64 |
| `intl_president_r1_co_icas` | 72 | 184 | 64 |
