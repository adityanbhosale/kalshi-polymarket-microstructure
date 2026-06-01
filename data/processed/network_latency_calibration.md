# Network-latency differential calibration (EXP-4b-symmetric)

Latest generated: 2026-06-01 (Run 2, post key rotation)

## Purpose
Quantify the network-path skew between this capture host and each venue's
edge, so that EXP-4 / F.2 can subtract it before attributing any sub-second
cross-venue lead to genuine information flow rather than transport latency.

**Use the RTT differential (Kalshi − Polymarket), not absolute RTTs alone.**
Absolute RTTs vary with network conditions; the differential tracks structural
path skew (London vs Ohio) and has reproduced across two independent runs.

## Method
- Persistent `httpx` client (TCP/TLS warmed once), then repeated lightweight
  public GETs every 1.0s for ~40s:
  - Kalshi:     `https://api.elections.kalshi.com/trade-api/v2/exchange/status`
  - Polymarket: `https://clob.polymarket.com/ok`
- Record wall-clock RTT per request. One-way latency is approximated as
  **RTT / 2**.

## Assumptions & caveats (read before trusting any lead-lag number)
- **Symmetric path**: one-way = RTT/2 assumes outbound and return paths have
  equal latency. Real internet paths are often asymmetric; treat the one-way
  figure as an estimate, not ground truth.
- **HTTPS edge ~= WS edge**: these REST endpoints terminate at the venue's CDN/
  edge, which may differ from the websocket ingress host. Order of magnitude is
  representative, exact host may differ.
- Server-side handling time is included in RTT and cannot be fully separated
  from pure network transit with this method.
- Measured from THIS host at THIS time; re-run near the live session for a
  contemporaneous figure (latency varies with route/load).
- **Absolute RTTs are condition-dependent snapshots; the differential is the
  stable quantity** (see both runs below).

## Results — Run 2 (latest)
Generated: 2026-06-01 (post key rotation)

- Kalshi RTT:     36.6 ms median / 45.0 ms p90 (n=35)
- Polymarket RTT: 106.7 ms median / 116.3 ms p90 (n=35)

**Median RTT differential (Kalshi - Polymarket): -70.1 ms  ->  implied one-way differential -35.0 ms (Kalshi edge is closer).**

## Results — Run 1 (2026-05-31 night, committed)
Generated: 2026-06-01T02:23:00+00:00

- Kalshi RTT:     19.7 ms median / 33.8 ms p90 (n=35)
- Polymarket RTT: 95.0 ms median / 109.9 ms p90 (n=35)

**Median RTT differential (Kalshi - Polymarket): -75.4 ms  ->  implied one-way differential -37.7 ms (Kalshi edge is closer).**

## Cross-run summary
| Quantity | Run 1 | Run 2 |
|---|---|---|
| Kalshi median RTT | 19.7 ms | 36.6 ms |
| Polymarket median RTT | 95.0 ms | 106.7 ms |
| RTT differential | -75.4 ms | -70.1 ms |
| One-way differential | ~37.7 ms | ~35.0 ms |

One-way differential stable at **~35–38 ms** across both runs despite Kalshi
median RTT nearly doubling (19.7 → 36.6 ms) between sessions.

## How EXP-4 should use this
When comparing a Kalshi event timestamp to a Polymarket event timestamp on the
LOCAL-RECEIVE clock, subtract the implied one-way differential (~35–38 ms,
Kalshi closer) from the observed lead before claiming venue A led venue B. Prefer
the differential from the calibration run closest in time to the capture session.
If an observed lead is smaller than this differential (plus its variability), it
is within network noise and NOT evidence of information lead.
