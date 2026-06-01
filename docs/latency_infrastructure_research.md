# Cross-Venue Latency Infrastructure — Research & Reference Catalog

**Compiled:** 2026-05-31  
**Scope:** Kalshi × Polymarket lead-lag and latency arbitrage, with adjacent precedents from crypto, FX, and HFT.  
**Status:** This document catalogs the **infrastructure landscape** and bounds the measurement problem from EXP-4b calibration. **Lead-lag findings** (whether Kalshi systematically leads Polymarket on live symmetric WS capture) are **provisional** and await Wednesday's NBA Finals G1 symmetric run.

Sources are cited inline after factual claims. Vendor marketing figures are included as evidence of market demand and stated latency tiers, not as independent benchmarks.

---

## 1. The measured starting point

EXP-4b-symmetric `--calibrate` (2026-06-01, capture host) measured persistent HTTP RTT to each venue's public edge:

| Venue | Median RTT | p90 RTT | n |
|---|---|---|---|
| Kalshi (`api.elections.kalshi.com/trade-api/v2/exchange/status`) | 19.7 ms | 33.8 ms | 35 |
| Polymarket (`clob.polymarket.com/ok`) | 95.0 ms | 109.9 ms | 35 |

Median RTT differential (Kalshi − Polymarket): **−75.4 ms**. Under symmetric-path assumption (one-way ≈ RTT/2), implied **one-way differential ≈ 37.7 ms** — Kalshi's edge is closer to this host than Polymarket's. ([`data/processed/network_latency_calibration.md`](../data/processed/network_latency_calibration.md))

### ~100 ms resolution floor for sub-second lead-lag claims

Any cross-venue lead observed on **local receive timestamps** must be debiased by this transport skew before attributing information flow. The practical resolution floor for sub-second lead-lag claims from this vantage is **~100 ms**, for three compounding reasons:

1. **Systematic offset (~38 ms one-way).** Even a perfectly synchronized clock pair would mis-attribute up to ~38 ms of "lead" to the closer venue. Observed leads smaller than this are within expected network bias, not evidence of information advantage.

2. **RTT jitter (~15 ms per venue at p90).** Kalshi p90−median spread is ~14 ms; Polymarket's is ~15 ms. Combined with asymmetric-path uncertainty (the calibration doc explicitly warns RTT/2 is an estimate, not ground truth), envelope uncertainty adds another ~20–40 ms.

3. **Software clock jitter (unquantified here, likely tens of ms without PTP).** Local `time.time()` / OS scheduler jitter on a laptop or home connection is not hardware-timestamped. Without exchange-timestamp arbitration or PTP, receive-time comparisons inherit this noise on top of network jitter.

**Rule of thumb:** an observed sub-second lead must exceed **~38 ms systematic offset + ~30–50 ms combined jitter envelope ≈ ~70–100 ms** before it clears network noise. Leads in the 10–50 ms range — the regime where HFT races live in equities — are **unresolvable** from this capture topology without infrastructure upgrades (Sections 3–4).

Caveats from the calibration itself: HTTPS edge may differ from WebSocket ingress; server handling time is embedded in RTT; measurements are host- and time-specific. Re-run `--calibrate` from the actual capture host immediately before live sessions. ([`data/processed/network_latency_calibration.md`](../data/processed/network_latency_calibration.md))

---

## 2. Structural cause — venue server geography

The ~38 ms one-way differential is not a bug in the capture script. It reflects **where the venues physically terminate traffic**.

| Venue | API / CLOB origin | AWS region | Metro |
|---|---|---|---|
| Polymarket CLOB | `clob.polymarket.com`, `wss://ws-subscriptions-clob.polymarket.com` | **eu-west-2** | London |
| Kalshi Trade API | `api.elections.kalshi.com/trade-api/v2` | **us-east-2** | Ohio |

Polymarket documents primary matching-engine servers in **eu-west-2**, with **eu-west-1 (Dublin)** as the closest non-georestricted region for co-location after KYC/KYB. ([Polymarket trading overview](https://docs.polymarket.com/trading/overview))

Glassnode's **HyperLatency** monitor — a live cross-venue RTT probe network built explicitly for co-location decisions — lists prediction markets alongside CEX feeds, validator nodes, and oracle gateways. It reports Polymarket REST RTT to `clob.polymarket.com` (origin **AWS eu-west-2, London**) and Kalshi REST RTT to `api.elections.kalshi.com` (origin **AWS us-east-2, Ohio**). Probes run worldwide on Fly.io and AWS bare-metal across Asia, Europe, and the Americas. ([Glassnode HyperLatency — Prediction Markets](https://hyperlatency.glassnode.com/prediction-markets))

### Implication: no equidistant vantage for this pair

London and Ohio sit on **different continents**. Transatlantic fiber RTT alone is typically **~60–80 ms** one-way depending on route — consistent with the measured ~38 ms *differential* when the capture host sits closer to one coast than the other.

There is **no single VPS location** that minimizes RTT to both venues simultaneously:

- Co-locate near Polymarket (Dublin/London corridor) → Kalshi RTT worsens by ~60+ ms.
- Co-locate near Kalshi (US East / Ohio corridor) → Polymarket RTT worsens by ~60+ ms.

Proximity to one venue is purchased at the expense of the other. The differential is **irreducible for this pair**; infrastructure tiers can only **relocate** which venue you are closer to, not eliminate continental separation.

---

## 3. Tier 3 — shrinking the physical path (co-location / VPS)

**Tier 3** in the latency hierarchy (after regional placement, before kernel/clock tuning) is **physical path minimization**: VPS, co-lo, or cross-connect in the same metro or facility as the venue's matching engine.

### Concrete RTT numbers (Polymarket CLOB, vendor-sourced)

TradoxVPS documents round-trip latency from common vantage points to Polymarket's **eu-west-2 (London)** CLOB:

| Vantage | RTT to Polymarket CLOB |
|---|---|
| US East Coast | **~130 ms** |
| Dublin | **< 5 ms** |
| Amsterdam | **~10 ms** |

([TradoxVPS — How to Set Up a Polymarket Bot on a VPS](https://tradoxvps.com/how-to-set-up-a-polymarket-bot-on-a-vps/))

QuantVPS and NewYorkCityServers corroborate the Dublin/London corridor logic: Dublin (AWS eu-west-1) sits ~450 km from London (eu-west-2) with inter-region fiber latency **under 2 ms**, and community benchmarks report **0–1 ms** datacenter-to-datacenter ping to Polymarket's backend from Dublin. US East (New York) is **~70–80 ms** minimum to London. ([QuantVPS — Best Trading VPS Providers in Dublin](https://www.quantvps.com/blog/best-trading-vps-providers-dublin); [NewYorkCityServers — Polymarket Server Location Guide](https://www.newyorkcityservers.com/blog/polymarket-server-location-latency-guide))

TradoxVPS's 2026 location guide lists Dublin at **0.5 ms** and Amsterdam at **8.2 ms** to the London matching engine (Amsterdam additionally geo-blocked for the international CLOB). ([TradoxVPS — Best VPS Location for Polymarket 2026](https://tradoxvps.com/best-vps-location-for-polymarket-trading-in-2026/))

### Co-lo tier benchmarks (general HFT, QuantVPS-sourced)

QuantVPS cites industry co-location latency tiers:

| Deployment | Typical RTT |
|---|---|
| Same-facility co-lo (cross-connect) | **1–5 ms** |
| Wrong-region VPS | **20–50 ms** |
| Home internet | **150 ms+** |
| Equinix LD4 (London) | **~0.56 ms** |
| Equinix NY4 (New York) | **~0.36 ms** |

([QuantVPS — How Latency Impacts Polymarket Bot Performance](https://www.quantvps.com/blog/how-latency-impacts-polymarket-trading-performance))

These Equinix figures are general financial-hub benchmarks (FX/equities), not Polymarket-specific measurements, but they establish the floor that prediction-market VPS vendors market toward.

### Vendor ecosystem (evidence of demand)

A dedicated **prediction-market VPS** segment has emerged, selling Dublin/London/Amsterdam vantage explicitly for Polymarket latency and (where applicable) geo-block bypass:

| Vendor | Positioning | Notable claim |
|---|---|---|
| [QuantVPS](https://www.quantvps.com) | Chicago (CME/Kalshi corridor), New York, **Dublin** datacenters | Sub-0.52 ms to major exchanges; Dublin Polymarket VPS ~0.52–1 ms ([Dublin providers roundup](https://www.quantvps.com/blog/best-trading-vps-providers-dublin)) |
| [TradoxVPS](https://tradoxvps.com/polymarket-vps) | **Dublin** Polymarket VPS (Ryzen 9950X) | < 1 ms average to Polymarket endpoints; 0.5 ms marketed ([Polymarket VPS](https://tradoxvps.com/polymarket-vps)) |
| [TradingVPS](https://tradingvps.io/polymarket-vps-hosting/) | Dublin primary, Amsterdam secondary | Ultra-low-latency routing to London CLOB; geo-unrestricted EU access |
| [NewYorkCityServers](https://www.newyorkcityservers.com/blog/polymarket-server-location-latency-guide) | **Dublin** launch for Polymarket | Sub-1 ms to eu-west-2; solves US geo-block + latency jointly |

The existence of this product category — not available for most retail SaaS — is itself evidence that **latency-sensitive prediction-market strategies are economically viable** at infrastructure tiers retail traders do not occupy.

### The Kalshi × Polymarket catch

QuantVPS markets **Chicago** for Kalshi-adjacent US futures/crypto latency and **Dublin** for Polymarket. ([QuantVPS low-latency trading blog](https://www.quantvps.com/blog/low-latency-trading))

For **cross-venue** Kalshi-vs-Polymarket work, co-lo near London helps Polymarket but **hurts Kalshi** (Ohio); co-lo near Ohio helps Kalshi but **hurts Polymarket** (London). You choose which leg to optimize, **know the differential**, and accept that the other leg pays the transatlantic penalty. Split capture (probe in each metro) or exchange-timestamp arbitration is required for unbiased lead-lag measurement — a single-VPS "fix" cannot solve both.

---

## 4. Tier 4 — clock sync & kernel bypass (now commodity-accessible)

**Tier 4** addresses microsecond-scale jitter inside the capture host — orthogonal to the ~60 ms transatlantic component but decisive for **attribution** (did venue A's event precede venue B's, or did our clock lie?).

### AWS tick-to-trade stack (Parts 1–2)

AWS's Web3 tick-to-trade series documents the modern commodity stack for digital-asset exchange and market-maker infrastructure:

**Precision time & hardware timestamping (Part 1 + Part 2):**

- **PTP Hardware Clock (PHC)** on supported EC2 instances tightens clock error to **typically < 40 μs**. ([AWS tick-to-trade Part 2](https://aws.amazon.com/blogs/web3/optimize-tick-to-trade-latency-for-digital-assets-exchanges-and-trading-platforms-on-aws-part-2/))
- Amazon Time Sync Service with PTP achieves **sub-100 μs, often sub-50 μs** accuracy on expanding instance ranges. ([AWS tick-to-trade Part 1](https://aws.amazon.com/blogs/web3/optimize-tick-to-trade-latency-for-digital-assets-exchanges-and-trading-platforms-on-aws/))
- **Nitro NIC hardware packet timestamping** (June 2025): 64-bit nanosecond-precision timestamp on every inbound packet at the NIC, bypassing software stack delay. ([AWS tick-to-trade Part 1](https://aws.amazon.com/blogs/web3/optimize-tick-to-trade-latency-for-digital-assets-exchanges-and-trading-platforms-on-aws/))

**Kernel bypass & network-optimized instances (Part 2):**

- HFT workloads favor **DPDK**, **AF_XDP zero-copy**, and **SR-IOV** over ENA Express when p50 consistency matters — SRD adds CPU overhead per packet. ([AWS tick-to-trade Part 2](https://aws.amazon.com/blogs/web3/optimize-tick-to-trade-latency-for-digital-assets-exchanges-and-trading-platforms-on-aws-part-2/))
- Network-optimized instances (**c6in**, **m6in**, **m8azn**) can reduce **p99.9 tail latency by up to 85%** vs. non-optimized counterparts; ENA driver version and config materially affect packet processing. ([AWS tick-to-trade Part 2](https://aws.amazon.com/blogs/web3/optimize-tick-to-trade-latency-for-digital-assets-exchanges-and-trading-platforms-on-aws-part-2/))
- Open-source reference: [twu-AWS/trading-latency-benchmark](https://github.com/twu-AWS/trading-latency-benchmark) (DPDK, AF_XDP, hardware timestamping samples).

QuantVPS's general HFT blog cites kernel bypass (DPDK / OpenOnload) cutting network stack latency from **20–50 μs to 1–5 μs**. ([QuantVPS — Low Latency Trading](https://www.quantvps.com/blog/low-latency-trading))

### For *this project's* purpose (measurement, not racing)

We are **not** racing to fill orders. We are asking: *did Kalshi's book move before Polymarket's on the same information shock?*

The highest-leverage Tier-4 upgrade for measurement is **PTP + hardware packet timestamping**:

- Kills the **software-clock jitter** component of the ~100 ms floor → uncertainty drops to **tens of microseconds** on the capture host.
- Does **not** remove the **~60–80 ms transatlantic** network component between Ohio and London.
- Enables triangulation: hardware timestamp (NIC arrival) vs. kernel timestamp vs. application timestamp vs. exchange-provided `exchange_ts` — gaps localize bottlenecks. ([AWS tick-to-trade Part 1](https://aws.amazon.com/blogs/web3/optimize-tick-to-trade-latency-for-digital-assets-exchanges-and-trading-platforms-on-aws/))

### PTP caveat — documented attack surface

Even hardware clock sync has failure modes. Recent work on **PTP/IEEE-1588 in Linux** documents kernel-level attack surfaces: privileged adversaries can hook `clock_adjtime` / PHC ioctl paths used by `ptp4l` and `phc2sys`, injecting constant offsets, slow skew, or instability that defeats servo convergence. Documented vulnerability classes include CVE-2025-21814 (PTP sysfs NULL deref), CVE-2018-11508 (`adjtimex` info leak), and broader timing-subsystem bugs. ([arXiv:2510.06421 — PTP kernel attack surface](https://arxiv.org/abs/2510.06421))

**Practical implication:** PTP is worth deploying for measurement, but clock integrity should be validated (external NTP/PTP cross-check, monitor offset variance) — not assumed.

---

## 5. Academic foundation (adjacent domains)

Prediction-market lead-lag is novel; the **mechanism** — continuous CLOB + speed rents — is well studied in equities and FX.

### Budish, Cramton & Shim (QJE 2015) — "The HFT Arms Race"

**Core claim:** Continuous limit-order-book markets create **mechanical latency-arbitrage rents** available to the fastest participant. Competition raises the speed bar; it does **not** shrink the opportunity — it reallocates who captures it. **Frequent batch auctions (FBA)** are proposed as the market-design fix: discretize trading into batch intervals so speed within an interval is worthless.

- Published: *Quarterly Journal of Economics*, 130(4), 1547–1621, November 2015. ([Eric Budish publication page](https://ericbudish.org/publication/the-hft-arms-race-coordinated-strategic-and-the-case-for-frequent-batch-auctions/); [SSRN 2388265](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2388265))

**Relevance here:** Cross-venue prediction-market arb is the same rent structure — whoever sees the repricing first on the slower venue captures spread. Fee walls (Section 6) are the venue-side analog of FBA.

### Aquilina, Budish & O'Neill (2020) — "Quantifying the HFT Arms Race"

Empirical quantification on **FTSE 100** stocks (2015–2016, ~2.2B messages):

| Metric | Value |
|---|---|
| Race frequency | **~1 race per minute per symbol** |
| Modal race duration | **5–10 μs** |
| Median race duration | **46 μs** |
| Share of volume in races | **~20%** |
| Top 6 firms' race win share | **~80%** (top 3: ~54%) |

([SSRN 3636323](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3636323))

**Scale contrast:** Equities HFT races at **microseconds**; our measured Kalshi–Polymarket network differential is **~38 ms one-way** — four orders of magnitude slower. Sub-second prediction-market lead-lag is a **coarse** phenomenon by HFT standards, but still invisible behind ~100 ms measurement noise from a non-co-located host.

### Spread Networks — canonical "shrink the path" anecdote

Spread Networks spent **~$300M** (2010) on an 827-mile fiber line from **Chicago (CME)** to **Carteret, NJ (Nasdaq)**, optimizing route straightness to cut round-trip latency from **~16 ms to ~13 ms** — saving **~3 ms**. ([Wikipedia — Spread Networks](https://en.wikipedia.org/wiki/Spread_Networks); [Stansberry Research — How Three Milliseconds Helped Investors Gain an Edge](https://stansberryresearch.com/dailywealth/how-three-milliseconds-helped-investors-gain-an-edge))

Within two years, **microwave radio** links (speed-of-light through air vs. glass) obsoleted the fiber advantage — the arms race moved to a faster medium. Spread Networks was acquired by Zayo for **$127M** in 2017, less than half construction cost. ([Wikipedia — Spread Networks](https://en.wikipedia.org/wiki/Spread_Networks))

**Lesson:** Path optimization buys temporary edge; competitors and venues respond. Polymarket's dynamic taker fees (Section 6) are the fee-side response.

### Novel research bridge (unexplored)

Polymarket's **5-minute and 15-minute crypto binaries** discretize time into short windows — a crude, venue-imposed **batch interval**. Under Budish's framing, these markets partially implement FBA-like time discretization, but **within** each window the CLOB is still continuous and latency-arbable (until fees intervene). Whether short-duration prediction markets converge toward true batch auctions — or permanently coexist with intra-window speed races — is an open design question with no published cross-venue study we are aware of.

---

## 6. Real-world market-design countermeasure

### Polymarket dynamic taker fees on 15-minute crypto markets

Polymarket's **zero-fee** structure on early 15-minute crypto markets created a repeatable latency-arb: bots monitored delays between Polymarket's internal pricing and **Binance/Coinbase spot**, entering near **50/50 odds** and exiting as prices converged. On-chain data cited in trade press: at least one wallet executed **thousands of trades per month** with an **extremely high hit rate**, capturing small consistent gains without directional risk. ([MEXC News — Polymarket Dynamic Fees](https://www.mexc.com/news/426113))

**Early 2026 response:** Polymarket enabled **dynamic taker fees** on 15-minute crypto markets specifically to fund its **Maker Rebates Program**. Fees are **highest near 50/50** — precisely where latency strategies operated — reaching approximately **3.15% on 50-cent contracts** at the midpoint, exceeding typical arb margin. Rebates redistribute fees daily to liquidity providers. ([MEXC News](https://www.mexc.com/news/426113); [NewYorkCityServers — dynamic fees FAQ](https://www.newyorkcityservers.com/blog/polymarket-server-location-latency-guide))

### Frame: speed race → fee wall (Budish prediction confirmed)

This is the venue converting a **speed race into a fee wall**:

1. An edge existed that was **real** but reachable only at infrastructure tiers retail cannot access (Dublin VPS, sub-5 ms CLOB RTT, spot-feed co-location).
2. The venue **neutralized** it via **fee design**, not infrastructure changes — exactly the market-structure response Budish et al. predict when continuous CLOB rents become socially costly.
3. Same phenomenon as this project's **EXP-3 fee frontier**: cross-venue *taking* arb is closed at retail fee tiers; latency arb on short crypto windows is closed at the **dynamic-fee tier** Polymarket now charges.

Longer-dated markets (politics, sports, economics) remain largely fee-free; speed still matters there, but the **15-minute crypto** segment — the closest analog to cross-venue Kalshi×Polymarket short binaries — has been explicitly targeted.

---

## 7. Open-source prior art

### Binance → Polymarket latency-arb bots

The ecosystem documents **2–10+ second** lag between Binance spot and Polymarket 5-minute BTC Up/Down books as exploitable by automated strategies. DEV Community writeups describe bots that are "not smarter — just faster at reacting to reality while the order book is still catching up," with explicit guidance to avoid home internet and run from datacenter VPS. ([DEV — How Real 5-Minute BTC Scalpers Work](https://dev.to/nevosaynevo/how-real-5-minute-btc-scalpers-work-on-polymarket-stale-order-book-sniping-4727))

The repo **`github.com/learningworship/polymarket-latency-bot`** is widely cited in this niche for Binance→Polymarket lag exploitation with Dublin/London VPS deployment advice; it returned **404** at catalog compile time (2026-05-31). Closest substantiated open-source analog: [`lingreerjr-eng/latency-bot`](https://github.com/lingreerjr-eng/latency-bot) (Polymarket latency-bot ecosystem; verify README for current lag claims and deployment notes before use).

TradoxVPS and QuantVPS setup guides encode the same deployment pattern: **Dublin VPS**, WebSocket to `wss://ws-subscriptions-clob.polymarket.com/ws/market`, IOC orders at best ask. ([TradoxVPS setup guide](https://tradoxvps.com/how-to-set-up-a-polymarket-bot-on-a-vps/))

### Polymarket × Kalshi systematic arb

A DEV Community writeup formalizes cross-exchange binary arb: enter when `P_poly_YES + P_kalshi_NO < 1`, with execution risk, slippage, fee adjustment, and resolution-mismatch tail risk. It frames profitability as an **engineering problem** (latency, fill reliability) not a pricing puzzle. ([DEV — Polymarket × Kalshi Arbitrage](https://dev.to/benjamin_martin_749c1d57f/polymarket-x-kalshi-arbitrage-27di))

### Bot dominance on Polymarket leaderboards

Trade press and wallet forensics report **14 of the top 20** most profitable Polymarket wallets are **bots** (hedge-fund and crypto-firm trading systems, not hobby scripts). Over **100,000 wallets** lost ≥ $1,000 each since January 2025; losses flowed to a small pro/bot cohort. Top 1% capture ~**76%** of profits. ([Briefs.co — Most Polymarket Traders Are Losing Money](https://www.briefs.co/news/most-polymarket-traders-are-losing-money-bots-are-cleaning-up/))

Leo Labs' reverse-engineering of top-20 crypto leaderboard wallets notes **>70% of crypto arb profits** go to bots with **<100 ms latency**; second-scale bots "provide liquidity for the fast players." ([Leo Labs — 20 Polymarket Strategy Patterns](https://leolabs.me/blog/pm-top20-strategy-patterns/en/))

**Context for this project:** The leaderboard is dominated by infrastructure-tier participants. Retail-capture lead-lag measurement from a laptop cannot compete with — but can still **characterize** — the regime they occupy.

---

## 8. Implications for this project

### The ~100 ms floor is explained and bounded

| Component | Magnitude | Removable? |
|---|---|---|
| Transatlantic path (Ohio ↔ London) | ~60–80 ms one-way | **No** — continental separation |
| Systematic RTT/2 offset (this host) | ~38 ms one-way | Partially — move host, not eliminate |
| RTT jitter (p90 − median) | ~15 ms per venue | Partially — better routing, co-lo |
| Software clock jitter | tens of ms (estimated) | **Yes** — PTP + HW timestamping → μs |

**PTP kills jitter; continental separation is irreducible.** Any claim that Kalshi "led" Polymarket by < 100 ms from a non-co-located asymmetric host is indistinguishable from network noise until debiased.

### Practical upgrade path (budget-scaled)

Each step is justified **only if the prior step's data shows signal near the floor**:

| Tier | Action | Cost | What it buys |
|---|---|---|---|
| **(a)** | Software continuous-probe + **exchange-timestamp arbiter** (`exchange_ts` on Kalshi WS deltas vs. Polymarket events; `--calibrate` debias) | **Free** | Removes gross RTT skew; uses venue clocks where available |
| **(b)** | Cloud VM at **known vantage** (Dublin for PM leg, US-East for Kalshi leg, or split probes) | **~$50–100/mo** | Relocate ~130 ms → <5 ms on optimized leg; know which leg you sacrificed |
| **(c)** | **PTP-enabled EC2** (PHC + Nitro hardware timestamping) on capture host | **Same tier as (b)** on supported instances | Software clock jitter → **<40 μs**; enables NIC-level arrival attribution |

Do **not** skip to (c) without (a) showing ambiguous lead-lag near the floor. Do **not** skip to (b) without (a) showing signal that survives `--calibrate` debias.

### Tie to Stage-1 thesis

Stage 1 closed **fee-based cross-venue taking arb** — no takeable edge at any accessible fee tier (EXP-3). Thesis B (lead-lag) survives because it requires **information positioning**, not fee advantage.

This catalog establishes that **cross-venue edge sits at infrastructure tiers retail cannot reach**:

- **Geography:** Dublin vs. Ohio — pick one.
- **Clock:** PTP vs. laptop `time.time()`.
- **Venue response:** Polymarket already converted 15-min crypto latency arb into dynamic fees — the Budish fee-wall outcome.

Wednesday's **symmetric WS capture** (Kalshi authenticated WS + Polymarket WS, same JSONL schema, `--calibrate` contemporaneous) is the first test of whether **Thesis B** produces signal above the ~100 ms floor on **sports/politics** markets where dynamic crypto fees do not apply. Until that run completes, all lead-lag claims from this repo remain **infrastructure-bounded**, not **information-validated**.

---

## Source index (quick reference)

| Topic | URL |
|---|---|
| EXP-4b calibration (in-repo) | [`data/processed/network_latency_calibration.md`](../data/processed/network_latency_calibration.md) |
| Glassnode HyperLatency | https://hyperlatency.glassnode.com/prediction-markets |
| Polymarket server regions | https://docs.polymarket.com/trading/overview |
| TradoxVPS RTT table | https://tradoxvps.com/how-to-set-up-a-polymarket-bot-on-a-vps/ |
| QuantVPS co-lo benchmarks | https://www.quantvps.com/blog/how-latency-impacts-polymarket-trading-performance |
| AWS tick-to-trade Part 1 | https://aws.amazon.com/blogs/web3/optimize-tick-to-trade-latency-for-digital-assets-exchanges-and-trading-platforms-on-aws/ |
| AWS tick-to-trade Part 2 | https://aws.amazon.com/blogs/web3/optimize-tick-to-trade-latency-for-digital-assets-exchanges-and-trading-platforms-on-aws-part-2/ |
| PTP attack surface | https://arxiv.org/abs/2510.06421 |
| Budish QJE 2015 | https://ericbudish.org/publication/the-hft-arms-race-coordinated-strategic-and-the-case-for-frequent-batch-auctions/ |
| Aquilina et al. 2020 | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3636323 |
| Spread Networks | https://en.wikipedia.org/wiki/Spread_Networks |
| Polymarket dynamic fees | https://www.mexc.com/news/426113 |
| Kalshi × PM arb writeup | https://dev.to/benjamin_martin_749c1d57f/polymarket-x-kalshi-arbitrage-27di |
| Top-20 bot dominance | https://www.briefs.co/news/most-polymarket-traders-are-losing-money-bots-are-cleaning-up/ |
