# DATA AUDIT — batch-auction counterfactual study

Read-only inventory of the repo's market-data store, compiled 2026-06-05. No
data was modified, migrated, or deleted. Evidence (query or file inspected) is
shown under each answer. Findings are provisional snapshots: **the E.1 daemon
is still running and appending live** (see Red Flags R1), so exact row counts
drift between queries — counts below are accurate as of this audit pass.

> **DECISIONS LOCKED (2026-06-05).** The seven open questions below were resolved
> by the human; see [RESOLVED DECISIONS](#resolved-decisions-2026-06-05). The
> replay set is now **frozen** at a fixed cutoff — counts/hashes in
> [FROZEN SNAPSHOT MANIFEST](#frozen-snapshot-manifest-replay-freeze), market
> inclusion/exclusion in [APPENDIX A](#appendix-a--market-inclusion--exclusion).
> All counterfactual analysis runs on the frozen set; the daemon keeps appending
> for future work.

Source-of-truth for schema is the **writing code**, read first:
`scripts/poll_timeofday.py` (E.1 30s panel), `scripts/poll_event_window.py`
(F.1 dense event overlay), `scripts/ws_leadlag.py` (sub-second WS), with
compute in `src/pm_micro/{normalize,microstructure,arb}.py` and HTTP clients
in `src/pm_micro/clients/{kalshi,polymarket}.py`.

---

## 1. STORAGE

**Format: plain files on disk — no database.** Three capture paths, each with a
processed long-format CSV and a gzipped/JSONL raw mirror.

| Path | Processed (committed) | Raw (gitignored) | Writer |
|---|---|---|---|
| E.1 30s panel | `data/processed/timeofday_poll.csv` (172 MB) | `data/raw/timeofday/<UTC-date>/<ts>_<market>.json.gz` (1.0 GB) | `poll_timeofday.py` |
| F.1 dense event | `data/processed/event_<label>_poll.csv` | `data/raw/event/<label>/<UTC-date>/<ts>_<market>.json.gz` (17 MB) | `poll_event_window.py` |
| WS sub-second | — | `data/raw/ws_leadlag/<label>/<UTC-date>.jsonl` (11 MB) | `ws_leadlag.py` |
| One-off snapshot | `data/processed/microstructure_snapshot.csv` | `data/raw/snapshot_<ts>/<market>_<venue>.json` | `fetch_snapshot.py` |

Layout details (from writer code):
- E.1 CSV is **long format**: one row per `(utc_ts, market_id, venue)` with
  `venue in {kalshi_yes, kalshi_no, polymarket_yes, polymarket_no}`
  (`poll_timeofday.py` lines 86-109). 4 venue-rows per market per cycle.
- Raw gz bundles one Kalshi + PM-YES + PM-NO orderbook per `(cycle, market)`
  (lines 368-381).

**Row counts (E.1 panel, `timeofday_poll.csv`):**
- Total rows: **1,059,136** (and rising — live daemon).
- Per venue (each exactly 1/4 of total): kalshi_yes 264,736 / kalshi_no
  264,736 / polymarket_yes 264,736 / polymarket_no 264,736.
- = 16,547 cycles x 16 markets x 4 venues.

> Evidence: `wc -l` on the CSVs; `du -sh data/raw/*`; pandas
> `df['venue'].value_counts()`. The prompt's "~500K rows" matches the
> `(cycle, market)` count (~265K) or a single-venue slice; the file holds
> ~1.06M venue-rows.

Other stores: `data/raw/kalshi_series.json` (15 MB) is series-discovery
metadata, not orderbook capture. `snapshot_2026*` dirs are two one-off
`fetch_snapshot.py` pulls (45 standalone orderbook JSONs in the larger one),
not a time series. `exp3c_persistence.csv`, `exp12a_*` etc. are **derived
analysis outputs**, not primary capture.

---

## 2. COVERAGE

**Per venue x market x day:** the daemon writes all 16 markets x 4 venues
*every* cycle (errors still emit 4 null rows — `poll_one_cycle` lines 392-439),
so the row count per (venue, market, day) is **identical across all venues and
all markets** for a given day, equal to that day's cycle count. The meaningful
variation is *data completeness* (non-null best_bid), shown further down.

**Cycles per UTC day** (each cycle = 64 rows):

| Day | Cycles | vs ~2,880 ideal (24h @ 30s) |
|---|---:|---|
| 2026-05-28 | 2,075 | partial (starts 04:01) |
| 2026-05-29 | 2,371 | 82% — gaps |
| 2026-05-30 | 2,010 | 70% — large gaps |
| 2026-05-31 | 1,059 | 37% — heavy downtime |
| 2026-06-01 | 1,350 | 47% |
| 2026-06-02 | 1,506 | 52% (incl. a 10.1h hole) |
| 2026-06-03 | 2,242 | 78% |
| 2026-06-04 | 2,656 | 92% |
| 2026-06-05 | 936 | partial / downtime |
| 2026-06-06 | 349 | partial (audit day, live) |

> Evidence: pandas `groupby(day)['ts'].nunique()`. Per-market check: for every
> day, min == max cycle count across all 16 markets (16/16 markets share the
> max), confirming uniform per-cycle writes.

**First/last row per market vs resolution date** — all 16 markets share the
same first cycle (2026-05-28 04:01:57Z) and last (live, ~2026-06-06 03:08Z)
because they are polled together. Several markets were **polled long past their
resolution date** (settled markets still queried):

| Market | Resolution | Note |
|---|---|---|
| nba_finals_cle | 2026-05-26 | resolved *before* capture began — 0% book data (delisted, all rows null/404) |
| intl_president_pe_kfuj / pe_rpal | 2026-04-12 | resolved ~6 weeks before capture; rows still ~99% populated (market still quoted) |
| intl_president_co_aesp / co_pval / r1_co_icas | 2026-05-31 | resolve mid-capture (Colombia 1st round) |
| us_mayor_la_kbas / rhua | 2026-06-02 | resolve mid-capture |
| intl_mayor_kr_oseh | 2026-06-03 | resolves mid-capture |
| nba_finals_okc / nyk / sas | 2026-06-30 | open through capture |

**Intra-day holes > 5 min (E.1 cycle stream): 209 gaps.** Median cadence 30.1s
(nominal), p99 477s. Largest holes:

| Gap ends (UTC) | Duration |
|---|---|
| 2026-06-02 14:01:37 | **608 min (10.1 h)** |
| 2026-05-30 14:22:40 | 82 min |
| 2026-06-01 11:36:56 | 79 min |
| 2026-05-30 18:01:38 | 77 min |
| 2026-06-01 13:47:30 | 75 min |
| 2026-05-30 19:15:13 | 74 min |
| 2026-05-28 20:28:11 | 73 min |

> Evidence: distinct sorted cycle timestamps, `.diff()`, filter > 300s. The
> daemon is a single laptop process (`caffeinate`); gaps line up with sleep /
> network-loss / key-rotation windows. **Coverage is dense but not gapless** —
> any auction sweep must treat each contiguous run separately, not assume a
> uniform 30s grid.

**Data completeness — non-null best_bid fraction per (market, venue), %:**

```
venue                      kalshi_no  kalshi_yes  pm_no  pm_yes
intl_mayor_kr_oseh                87          87     78      80
intl_president_co_aesp            99          99     99      99
intl_president_co_pval            49          44     99      45
intl_president_pe_kfuj            99          99     99      99
intl_president_pe_rpal            99          99     99      99
intl_president_r1_co_icas         49          49     99      95
ma_acquisition_wb_psky            99          99     99      99
nba_finals_cle                     0           0      0       0   <- delisted
nba_finals_nyk                    99          99      0      99   <- PM NO 404
nba_finals_okc                    39          39     39      39   <- thin/late
nba_finals_sas                    99          99     99      99
sports_retirement_arod            99          99     99      99
sports_retirement_kelce           99          99     99      99
us_mayor_la_kbas                  99          99     99      99
us_mayor_la_rhua                  99           0     99      21   <- one-sided
us_senate_ak_mpel                 99          99     99      99
```

> Evidence: `df.assign(has=best_bid.notna()).groupby([market,venue]).mean()`.
> `nba_finals_cle` is fully empty (resolved pre-capture). `nyk` PM-NO is 0%
> (token `404_delisted` in markets.yaml). `okc` drops to 39% (book thins as the
> Finals progress). These are the markets to exclude or special-case.

---

## 3. SCHEMA

**E.1 / F.1 CSV columns** (15; F.1 adds `event_label`). Meaning per column:

| Column | Meaning |
|---|---|
| `utc_ts` | tz-aware UTC ISO-8601 cycle timestamp = **local receipt time** at cycle start (one stamp shared by all 4 venue-rows of a market that cycle) |
| `market_id` | markets.yaml id (the cross-venue pairing key) |
| `category` | market category (e.g. sports_nba_finals); 9 distinct |
| `prob_bucket` | curation bucket {central, mid_low, mid_high, tail_low} |
| `is_degenerate` | bool: thin/delisted-expected market flag |
| `venue` | one of {kalshi_yes, kalshi_no, polymarket_yes, polymarket_no} |
| `best_bid` | top-of-book bid, dollars 0-1 (None if empty/error) |
| `best_ask` | top-of-book ask, dollars 0-1 |
| `mid` | (best_bid+best_ask)/2 |
| `spread_bps` | 10000 * (ask-bid) / mid |
| `depth_within_1c` | total size (both sides) within $0.01 of mid, in contracts |
| `mid_disc_direct` | cross-venue direct mid discrepancy (cents), denormalized onto all 4 rows of the market-cycle |
| `mid_disc_synth` | cross-venue synthetic (via complement) mid discrepancy (cents) |
| `schema_version` | constant `1` |
| `error` | error string or None; `expected_404` = documented delisting |
| `event_label` | (F.1 only) event tag, e.g. `colombia_r1` |

Column semantics traced to `compute_microstructure` (microstructure.py 37-93)
and `compute_mid_discrepancy` (arb.py). Note the CSV stores **top-of-book +
two depth scalars only** — the full ladder lives in the raw gz (see Q5).

**Sample Kalshi row** (`kalshi_yes`, nba_finals_okc, first cycle):
```
utc_ts=2026-05-28T04:01:57.339434+00:00  market_id=nba_finals_okc
venue=kalshi_yes  best_bid=0.56  best_ask=0.57  mid=0.565
spread_bps=176.99  depth_within_1c=533670.32  mid_disc_direct=1.0
mid_disc_synth=1.0  schema_version=1  error=NaN
```
**Sample Polymarket row** (`polymarket_yes`, same market/cycle):
```
utc_ts=2026-05-28T04:01:57.339434+00:00  market_id=nba_finals_okc
venue=polymarket_yes  best_bid=0.57  best_ask=0.58  mid=0.575
spread_bps=173.91  depth_within_1c=40049.66  mid_disc_direct=1.0
mid_disc_synth=1.0  schema_version=1  error=NaN
```

**Null / constant flags (whole E.1 file):**
- `schema_version` — **constant = 1** (no schema drift across the capture).
- `best_bid` non-null 843,309 / 1.06M (~80%); `best_ask` ~80%; `mid`/`spread_bps`
  ~76%; `mid_disc_synth` ~69% (needs both venues + complement).
- `error` non-null on ~85,700 rows (8%); 29 distinct strings.
- No column is all-null or unexpectedly constant besides `schema_version`.

> Evidence: per-column `notna().sum()` and `nunique()`; two sample rows pulled
> with pandas `.iloc[0]` on non-null slices.

---

## 4. TIMESTAMPS

| Path | Venue | Exchange event time | API response time | Local receipt time | Stored as PRIMARY |
|---|---|---|---|---|---|
| E.1 REST panel | Kalshi | no | no | yes (`utc_ts`) | local receipt |
| E.1 REST panel | Polymarket | no | no | yes (`utc_ts`) | local receipt |
| F.1 REST dense | both | no | no | yes (`utc_ts`) | local receipt |
| WS | Polymarket | **yes** (`exchange_ts`, from msg `timestamp` ms) | no | yes (`local_recv_utc`) | local receipt |
| WS | Kalshi (WS path) | yes (`ts_ms`) when true WS | no | yes (`local_recv_utc`) | local receipt |
| WS | Kalshi (REST fallback) | no (`exchange_ts=None`) | no | yes (`local_recv_utc`) | local receipt |

- **Primary clock everywhere is local-receipt UTC** (`datetime.now(timezone.utc)`
  taken when the response/message lands). The REST pollers store a single
  `utc_ts` taken at *cycle start* (poll_timeofday.py 394-395) — i.e. it is the
  cycle clock, not even per-call receipt; all 4 venue-rows of a market share it,
  and so do all 16 markets in a cycle (calls are ~75ms apart but stamped once).
- **Exchange timestamps exist only in the WS path, and in practice only for
  Polymarket** (Kalshi ran as REST fallback in the one window — see Q7).

**Exchange-vs-receipt difference (WS, Polymarket, the only place both exist):**
`local_recv_utc - exchange_ts`, n=5,587 PM messages:
- median **+22 ms**, p10 -21 ms, p90 +61 ms, min -35 ms, max +83,344 ms.
- The median ~22ms is consistent with the calibrated PM one-way network
  differential (~35ms RTT/2 region). The 83s max and negative tails come from
  stale/late frames and local-vs-exchange clock skew — treat per-message, not
  aggregate.

> Evidence: parsed `ws_leadlag/colombia_r1/2026-05-31.jsonl`; computed
> `(Timestamp(local_recv_utc) - Timestamp(exchange_ts))` per data message.
> Important for lead-lag: the REST panel has **no exchange time at all**, so any
> cross-venue timing on the 30s/5s panel is receipt-clock only.

---

## 5. DEPTH

| Path | Kalshi | Polymarket |
|---|---|---|
| **Raw gz / WS** | **FULL ladder** | **FULL ladder** |
| Processed CSV | top-of-book + `depth_within_1c` + `depth_within_5c`(*) | same |

(*) `depth_within_5c` is computed by `compute_microstructure` but not written to
the E.1 CSV (only `depth_within_1c` is in `CSV_FIELDS`).

The raw gz bundles preserve the **entire book** both sides. Example payload
(NYK, 2026-05-28 04:01:57Z bundle):
- **Kalshi** `orderbook_fp`: `yes_dollars` 30 levels, `no_dollars` 69 levels,
  on a **1-cent grid**. First few yes levels:
  `[["0.0100","4658055.67"],["0.0200","13505.56"],["0.0300","27805.84"],...]`
  (both arrays are *bids*; YES asks are reconstructed as 1 - NO-bid via
  `normalize_kalshi_orderbook`).
- **Polymarket** YES token: **130 bids, 82 asks**, on a **0.1-cent grid**.
  bids `[{"price":"0.001","size":"928770"},{"price":"0.002","size":"1305005"},...]`
  asks `[{"price":"0.999","size":"11003310"},...,{"price":"0.99","size":"4128.46"}]`.

> Evidence: `gzip` + `json.load` of
> `data/raw/timeofday/2026-05-28/2026-05-28T040157.339434+0000_nba_finals_nyk.json.gz`.
> **Implication: snapshot-level depth-walk clearance (Arm A) is feasible — but
> only from the raw gz, not the processed CSV**, which would need a (cheap)
> extraction pass to rebuild ladders per cycle.

---

## 6. TRADES

**Quotes / orderbooks only. No trade prints or tick data are captured anywhere,
on either venue, on any path.**
- REST pollers call `/markets/{ticker}/orderbook` (Kalshi) and
  `get_order_book(token)` (Polymarket) — order books, no trades endpoint.
- WS subscribes Polymarket `market` channel (`book` / `best_bid_ask` events) and
  Kalshi `orderbook_delta` — both are book channels. WS data `event_type` values
  observed: `rest_poll`, `best_bid_ask`, `book` only (no `trade`/`last_trade`).

> Evidence: client code (`clients/kalshi.py`, `clients/polymarket.py`),
> `ws_leadlag.py` subscription messages, and `Counter(event_type)` over the WS
> jsonl. **Blocker for any realized-fill / true-markout work**: markout in this
> repo is a *mid-move proxy*, never an executed-trade tape.

---

## 7. WS WINDOWS (sub-second capture inventory)

**Exactly ONE sub-second window exists.** This is the hard boundary of every
sub-second claim.

| File | Venue | Markets | Start (UTC) | End (UTC) | Dur | Data msgs | Msg kind |
|---|---|---|---|---|---|---:|---|
| `ws_leadlag/colombia_r1/2026-05-31.jsonl` | Polymarket | 8 (YES only) | 2026-05-31 21:12:48 | 23:19:51 | 127 min | 5,587 | full book states (`book` 1,672 + `best_bid_ask` 3,915) |
| same file | Kalshi | 8 (YES only) | 2026-05-31 21:12:48 | 23:19:51 | 127 min | 39,517 | **REST poll @ ~1.5s** (`rest_poll`) — NOT sub-second, NOT deltas |

Markets in window: intl_president_co_aesp, co_pval, r1_co_icas,
intl_president_pe_rpal, intl_mayor_kr_oseh, us_mayor_la_kbas, nba_finals_okc,
nba_finals_sas.

- **Polymarket is genuinely sub-second**: inter-message median **82 ms** (p10
  ~0 ms, p90 3.5 s). Messages are full book snapshots (`book`) plus
  top-of-book updates (`best_bid_ask`).
- **Kalshi is NOT sub-second in this window**: the authenticated WS degraded to
  the 1.5s REST fallback (39,517 msgs / 8 markets / 127 min approx 1.54s
  cadence; all `event_type=rest_poll`, all `exchange_ts=None`). The Kalshi-WS
  delta path (`orderbook_delta`, true book deltas) exists in code but produced
  **no captured data** here.
- Control records in the file: 1 SESSION_START, 508 STATUS, 315 ERROR, 2
  RECONNECT (self-healed).

> Evidence: `find data/raw/ws_leadlag -name '*.jsonl'` (one file);
> `Counter(record_type)`, `Counter(event_type)`, inter-message `.diff()` on
> `local_recv_utc`. **Critical**: there is no symmetric sub-second cross-venue
> data — only PM is fast; Kalshi in the same window is 1.5s. The F.1
> `event_*_poll.csv` files are **5-second REST**, not sub-second (median cadence
> 5.0s), and cover only the 3 Colombia markets.

---

## 8. UNITS & CONVENTIONS

**Price units:**
- **Kalshi**: dollars in [0, 1] (e.g. `0.56`), from `orderbook_fp.yes_dollars` /
  `no_dollars` arrays of `[price_str, size_str]`. Tick size **$0.01 (1 cent)**.
- **Polymarket**: probability/USDC price in [0, 1] (e.g. `0.57`), `bids`/`asks`
  with string `price`/`size`. Tick size **$0.001 (0.1 cent)** — 10x finer than
  Kalshi.
- Both are normalized to the same [0,1] dollar scale by `normalize.py`; this
  repo expresses spreads/edges in **cents = price * 100**. Sizes are in
  **contracts/shares** (Kalshi contracts; PM shares ~ USDC notional at price).

**YES/NO conventions:**
- Kalshi returns BOTH sides as resting **bids** (`yes_dollars`, `no_dollars`).
  An ask on YES at price p is reconstructed as the complement of a NO bid at
  (1 - p): `YES_ask = 1 - best(NO_bid)` (`normalize_kalshi_orderbook` 55-62).
- Polymarket: separate YES and NO **token** order books, each with native
  bids/asks; YES and NO are distinct ERC1155 tokens (`yes_token_id`,
  `no_token_id`). NO complementarity: `NO_price = 1 - YES_price`.
- The panel keeps all four legs (`kalshi_yes, kalshi_no, polymarket_yes,
  polymarket_no`) so both venues' both sides are available.

**Market pairing mapping:** defined in **`markets.yaml`** (16 entries). Each
entry's `id` is the join key; `kalshi.ticker` pairs to
`polymarket.{condition_id, yes_token_id, no_token_id}`. Per-entry
`prob_bucket`, `resolution_date`, and `*_token_orderbook_status: 404_delisted`
markers drive degeneracy/expected-404 handling. `validate_markets_yaml.py`
checks it; `expand_markets_yaml.py` generated the D.2 expansion (3 -> 16).

> Evidence: `clients/kalshi.py` docstring + `normalize.py`; raw payload grids
> in Q5 (Kalshi 0.01 spacing, PM 0.001 spacing); `markets.yaml` parsed for the
> pairing fields.

---

## 9. KNICKS WINDOW (end-to-end integrity, both venues)

Target: NYK (`nba_finals_nyk`, Kalshi `KXNBA-26-NYK`) over the ~14.8h crossed
window from 2026-05-28, daemon window 04:01-18:51 UTC. Pulled from
`timeofday_poll.csv` for `04:01:00Z <= ts <= 18:52:00Z`.

| Metric | kalshi_yes | polymarket_yes |
|---|---:|---:|
| rows (snapshots) | **1,749** | **1,749** |
| best_bid nulls | 0 | 0 |
| best_ask nulls | 0 | 0 |
| max inter-snapshot gap | 424 s (~7.1 min) | 424 s |
| median gap | 30 s | 30 s |

- Paired snapshots (inner join on `ts`, all 4 top-of-book non-null): **1,749 /
  1,749** — perfect alignment, no nulls through the window.
- (PM-NO is `404_delisted` for NYK and is irrelevant to the YES-vs-YES cross.)

**Integrity: CLEAN on both venues** — full row count, no nulls in best bid/ask,
single ~7-min gap (the 04:10 hole), otherwise 30s cadence.

**Crossing (raw, pre-fee), cross_c = max(kalshi_bid - pm_ask, pm_bid -
kalshi_ask) in cents:**
- fraction crossed (cross > 0): **100.0%**
- median cross (all snaps = when-crossed): **0.5 c**
- max cross: **1.5 c**

**Agreement with the published finding: YES, it agrees.** Published claim was
"crossed in ~100% of snapshots, median cross ~0.5c" — reproduced exactly
(100.0%, 0.5c). No discrepancy to flag. (Note: the separate hero-figure "$165
median" was takeable-$ at displayed depth, a different metric; the per-contract
cross is 0.5c median, consistent.)

> Evidence: pandas filter on market/venue/time; null counts; `ts`-merge of the
> two YES legs; cross computed both directions. Frozen-book caveat below.

---

## 10. RED FLAGS

- **R1 — LIVE APPEND DURING AUDIT (handling caveat, not corruption).** Total
  E.1 rows grew 1,058,944 -> 1,059,136 between two queries minutes apart; the
  daemon is still polling (raw dir `2026-06-06/` mtime is current). *Any
  counterfactual replay must pin a frozen copy / max-timestamp cutoff* or row
  counts and the "last row" move under you.
- **R2 — FROZEN BOOKS (material for replay).** Across the NYK window,
  consecutive snapshots have **identical (best_bid, best_ask)** 97.1% of the
  time on Kalshi and **99.9%** on Polymarket. The 30s panel is effectively a
  step function with very few changes; this is *why* the cross persists (nobody
  lifts it) but it also means **sub-30s dynamics are invisible** and naive
  per-snapshot independence overstates the number of distinct book states.
- **R3 — LARGE COVERAGE GAPS.** 209 holes > 5 min including a **10.1h** outage
  (2026-06-02) and several 60-82 min holes (05-30, 06-01). Not gapless; do not
  assume a uniform 30s grid.
- **R4 — ASYMMETRIC SUB-SECOND DATA.** The only WS window has true sub-second
  Polymarket but **1.5s REST Kalshi** (WS degraded). No symmetric sub-second
  cross-venue book exists (see Q7).
- **R5 — NO EXCHANGE TIMESTAMPS ON THE PANEL.** REST 30s/5s rows carry only a
  cycle-level local-receipt stamp shared across 16 markets x 4 venues; not
  usable for sub-cycle cross-venue timing.
- **R6 — DEAD / DEGENERATE MARKETS.** `nba_finals_cle` 0% data (resolved
  pre-capture); `nyk` PM-NO 0% (404 delisted); `okc` 39%; `us_mayor_la_rhua`
  one-sided (kalshi_yes 0%). Exclude or special-case.
- **R7 — STALE-BUT-QUOTED SETTLED MARKETS.** Peru markets resolved 2026-04-12
  yet are ~99% populated through capture — quotes may be non-economic
  residue; verify before trusting their crosses.
- **R8 — HIGH ERROR VOLUME (handled, but noted).** ~85.7k rows carry an error;
  49.3k `expected_404` (documented delistings), 26.4k bare `404`, plus PM API
  exceptions (~3.9k), DNS/`nodename` connect errors (~2.0k, laptop offline),
  Kalshi 503s, SSL resets. Error rows still occupy a row with null metrics.
- **R9 — MULTI-LINE CSV ROWS.** Some `timeofday_poll.csv` rows embed Kalshi 503
  error strings containing newlines, so a logical row spans several physical
  lines. `wc -l`-style counting over-reports rows; always parse with a real CSV
  reader. (Surfaced during the freeze — see the manifest note.)

**Cleared (checked, NOT problems):**
- Duplicate rows: **0** exact dupes, **0** rows sharing
  `(utc_ts, market_id, venue)`.
- Non-monotonic timestamps: **0** rows where `utc_ts` < previous row (pure
  append order).
- Schema drift: `schema_version` constant = 1 across the whole panel; F.1 adds
  only the documented `event_label` column.

> Evidence: `df.duplicated()` / `duplicated(subset=key)`; row-order `.diff()`;
> consecutive-identical (bid,ask) fraction over the NYK window;
> `schema_version.unique()`.

---

## TIER MAP — planned experiment arms vs supporting data

Tiers: **T1** = E.1 30s panel (+F.1 5s overlay), full ladders in raw gz, 16
markets, ~9 days. **T2** = WS sub-second, *Polymarket only*, 8 markets, single
127-min window (2026-05-31). **T3** = symmetric sub-second both venues — **does
not exist**.

_Updated post-decisions: Arm C reframed as a single-venue case study (D6→#7),
Arm D demoted to the 30s tier (#3). See [RESOLVED DECISIONS](#resolved-decisions-2026-06-05)._

| Arm | Description | Tier | Supported? | Blockers / notes |
|---|---|---|---|---|
| **A** | Snapshot-level clearance | T1 | **YES** | Full ladders in raw gz (Q5); ladders extracted per-episode (decision #5), not for all 1.06M rows. Collapse identical-state runs to **episodes** (decision #2); report time-in-state as duration. Exclude the 10.1h outage from denominators (R3, decision #4). Restrict to the 10 included markets (Appendix A). |
| **B** | Markout decomposition | T1 | **PARTIAL** | Mid-markout **(proxy)** only — no trade prints (Q6, decision #6); horizons 1/5/15 min with staleness sensitivity; **no realized-PnL language**. Frozen books (R2) bias short-horizon markout toward 0. |
| **C** | Sub-second interval sweep | T2 | **SINGLE-VENUE CASE STUDY** | Reframed (decision #7) as one **illustrative Polymarket** window (2026-05-31, 127 min, 8 markets); explicitly bounded in the writeup. Not a cross-venue or generalizable result. |
| **D** | Joint cross-venue auction | T1 (30s) | **YES at 30s; sub-second BLOCKED** | Demoted (decision #3): joint cross-venue auction runs on the **30s REST panel** (shares Arm A's episode set). The **sub-second** joint version stays **BLOCKED** — no symmetric sub-second data (Kalshi WS degraded to 1.5s REST, R4); noted in writeup, pending future symmetric WS capture. |

---

## RESOLVED DECISIONS (2026-06-05)

The seven open questions from the audit are now resolved. Each decision and its
concrete effect on the build:

1. **Replay cutoff — PIN NOW.** Freeze the analysis set at
   **2026-06-05 23:59:59.999 ET (= 2026-06-06T04:00:00Z, exclusive)**. Row
   counts + content hashes recorded in
   [FROZEN SNAPSHOT MANIFEST](#frozen-snapshot-manifest-replay-freeze). All
   analysis runs on the frozen set (`utc_ts < cutoff`); the daemon keeps
   appending for future work. Resolves R1.
2. **Frozen-book semantics — COLLAPSE to state-episodes.** Unit of analysis =
   a crossed/dislocated **episode** (a contiguous run of identical-or-crossed
   states), with **one** counterfactual first-clearance per episode. Time-in-state
   is reported as **duration**, never snapshot counts as opportunity counts.
   Kills the ~30-100x overcounting from R2.
3. **Arm D — demote to 30s tier.** Joint cross-venue auction runs on the 30s
   REST panel (T1). The **sub-second** joint version is **BLOCKED** and noted in
   the writeup, pending a future symmetric WS capture. (TIER MAP updated.)
4. **Stale/settled markets — exclusion rule.** Drop `cle` and any market-venue
   leg with structural gaps (e.g. `nyk` PM-NO). Include only markets with
   two-sided books on **both** venues in **>=80%** of covered snapshots. All
   exclusions listed in [APPENDIX A](#appendix-a--market-inclusion--exclusion).
   The **10.1h outage** (2026-06-02) is excluded from all time-in-state
   denominators. Resolves R6/R7.
5. **Ladders — per-episode extraction.** Extract ladders from the raw gz into a
   queryable per-level table **for included markets only**, scoped to the
   episode windows identified in Arm A's first pass — not a blanket rebuild of
   all 1.06M rows. (The freeze leaves raw gz in place; extraction content-hashes
   the specific files it pulls.)
6. **Markout truth — mid-markout (proxy).** All markout metrics are labeled
   **"mid-markout (proxy)"**; horizons **1 / 5 / 15 min** with staleness
   sensitivity; **no realized-PnL language** anywhere. Resolves Q6.
7. **WS window — single-venue case study.** Arm C is reframed as an
   **illustrative Polymarket-only** case study (127-min, 2026-05-31), clearly
   bounded in the writeup. No cross-venue or generalization claims.

---

## FROZEN SNAPSHOT MANIFEST (replay freeze)

**Cutoff:** `2026-06-06T04:00:00Z` (exclusive) = **2026-06-05 23:59:59.999 ET**
(EDT, UTC-4). **Freeze rule:** include every record/file whose capture
timestamp is strictly before the cutoff. Generated 2026-06-06T03:58Z by
`batch_counterfactual/freeze_manifest.py` (read-only over data; writes only
`batch_counterfactual/FROZEN_MANIFEST.json`). No data was copied/moved/deleted —
the freeze is defined by the cutoff rule plus the hashes below, so the live
daemon may keep appending without disturbing the frozen set.

For append-only CSVs the SHA256 is over a **canonical csv re-serialization of
the through-cutoff rows** (the csv module rejoins quoted multi-line fields — see
note below), so it is reproducible regardless of later appends. As of the freeze
there are **0** rows after the cutoff (real time was ~03:58Z, just inside it).

**Primary processed CSVs (analysis inputs):**

| File | Rows ≤ cutoff | SHA256 (canonical, through-cutoff) |
|---|---:|---|
| `data/processed/timeofday_poll.csv` | 1,065,536 | `cc1752b42258d3813419aa573e8321a136e30bbd7a819e3b5b4c8c3a43c3a007` |
| `data/processed/event_colombia_r1_poll.csv` | 17,688 | `2025bbe6a8a773233ad0a368e1ce27f309c62c8edd4c49f3caaecf33ab17e8c1` |
| `data/processed/event_test_smoke_poll.csv` | 216 | `483649d73bd203b7a41e5cd06e5d85ec33c0eaf3a3bdaf383baf0c51f6da7fbf` |
| `data/processed/microstructure_snapshot.csv` | 61 | `8b10cf1c247598ed0441d7ba2ed78011df194c0ef7907a91e2c54b3bd2f18911` |

**Sub-second WS:** `data/raw/ws_leadlag/colombia_r1/2026-05-31.jsonl` —
**45,930** records (all pre-cutoff, max recv 2026-05-31T23:19:51Z),
sha256 `69f65bf31deafc719e268b718989e0e8…` (full in JSON).

**Raw gz trees** (index hash over sorted `(relpath, size)`; per-episode payloads
content-hashed later at extraction time, decision #5):

| Tree | Files ≤ cutoff | Content bytes | Index SHA256 |
|---|---:|---:|---|
| `data/raw/timeofday/` | 266,392 | 356.5 MB | `674c423437a1c9d3b626435a1920fcd2…` |
| `data/raw/event/` | 4,475 | 6.1 MB | `02635754ac0c510f5afc7d4889f52baf…` |
| `data/raw/snapshot_20260525T220956Z/` | 8 | 53.5 KB | `3b216dd4942940ebe1be473559ee6dfd…` |
| `data/raw/snapshot_20260528T022943Z/` | 45 | 204.2 KB | `c34022c512d2b1fa5413b7dfe33211e9…` |

_Content bytes are the sum of file sizes; on-disk `du` for the timeofday tree is
~1.0 GB because each ~1.3 KB gz occupies a full filesystem block._

**Raw `timeofday/` files per UTC day (≤ cutoff):**

| UTC day | Files | Bytes |
|---|---:|---:|
| 2026-05-28 | 33,200 | 46.9 MB |
| 2026-05-29 | 37,936 | 55.4 MB |
| 2026-05-30 | 32,160 | 47.4 MB |
| 2026-05-31 | 16,949 | 23.1 MB |
| 2026-06-01 | 21,600 | 28.8 MB |
| 2026-06-02 | 24,101 | 31.3 MB |
| 2026-06-03 | 35,872 | 45.5 MB |
| 2026-06-04 | 42,496 | 51.6 MB |
| 2026-06-05 | 14,974 | 17.9 MB |
| 2026-06-06 | 7,104 | 8.5 MB (00:00–03:59Z, pre-cutoff) |

_Derived outputs (`exp3c_persistence`, `exp12a_*`, `arb_results*`,
`discovery_*`, `*.md`, figures) are **not** part of the frozen capture set —
they are regenerable from the frozen primaries above._

> **CSV multi-line note (also a minor red flag, R9).** Some `timeofday_poll.csv`
> rows carry Kalshi 503 error strings with **embedded newlines**, so one logical
> CSV row spans several physical lines. A naive line-count over-reports rows
> (an early freeze pass mis-flagged 1,668 "post-cutoff" rows that were really
> error-string continuation lines). Always parse this file with a real CSV
> reader (pandas / `csv`), never `wc -l`.

---

## APPENDIX A — MARKET INCLUSION / EXCLUSION

Decision #4 rule applied over the frozen set. **Denominator = all 16,649 frozen
daemon cycles** (the daemon writes a row for every market each cycle, so an
absent/empty cycle counts against the market). "Two-sided" = best bid **and**
best ask present on the YES leg of **both** venues. Include iff two-sided on both
in **>=80%** of cycles.

**Included (10):**

| Market | Two-sided (both venues) |
|---|---:|
| `intl_president_pe_rpal` | 98.9% |
| `sports_retirement_kelce` | 98.9% |
| `us_mayor_la_kbas` | 98.9% |
| `intl_president_co_aesp` | 98.8% |
| `intl_president_pe_kfuj` | 98.8% |
| `ma_acquisition_wb_psky` | 98.8% |
| `nba_finals_nyk` | 98.8% |
| `nba_finals_sas` | 98.8% |
| `sports_retirement_arod` | 98.8% |
| `us_senate_ak_mpel` | 98.8% |

**Excluded (6):**

| Market | Two-sided | Reason |
|---|---:|---|
| `intl_mayor_kr_oseh` | 77.2% | Below 80%; resolves 2026-06-03 mid-capture, two-sidedness decays after resolution. |
| `intl_president_r1_co_icas` | 48.3% | Colombia round-1 resolved 2026-05-31; Kalshi leg sparse (PM 94% but Kalshi 48%). |
| `intl_president_co_pval` | 43.7% | Resolved 2026-05-31; both legs sparse afterward. |
| `nba_finals_okc` | 38.6% | Structural intermittency — present every cycle but two-sided only 38.6% (book frequently one-sided/empty). |
| `nba_finals_cle` | 0.0% | Resolved pre-capture; no data (R6). |
| `us_mayor_la_rhua` | 0.0% | Kalshi YES never two-sided (one-sided leg, R6). |

**Leg-level exclusion (market kept):** `nba_finals_nyk` **PM-NO** leg is
`404_delisted` — dropped; the market is included on the YES-vs-YES cross only.

> **Interpretation flag.** The >=80% test uses **all frozen cycles** as the
> denominator (a market absent/empty for many cycles is penalized). Under the
> looser reading "% of the cycles where the market quoted at all," `okc` (99.6%
> when present) and `kr_oseh` (~89%) would flip to **included**. I chose the
> stricter all-cycles denominator because it matches decision #4's
> "structural gaps" intent; say the word if you meant the conditional reading
> and I'll re-run the split.

> Evidence: `batch_counterfactual/freeze_manifest.py` →
> `FROZEN_MANIFEST.json` (`market_inclusion`).

