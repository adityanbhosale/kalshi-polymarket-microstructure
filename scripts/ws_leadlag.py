"""EXP-4b / EXP-4b-symmetric: dual-venue live capture for cross-venue lead-lag.

Streams live top-of-book from Polymarket (CLOB websocket, public) and Kalshi
(authenticated orderbook_delta websocket, with automatic degradation to a
1.5s REST poll if WS auth/connection is unavailable) for 6-8 catalyst/active
markets, logging every update with a LOCAL-RECEIVE timestamp (primary clock)
plus the venue-provided EXCHANGE timestamp (cross-check, nullable).

This client is EXPERIMENTAL and runs ALONGSIDE the F.1 REST capture, which
remains the capture of record. No lead-lag number is computed or trusted
here; capture only. The clock-sync cross-check (local-time lead vs exchange-
time lead agreement) plus the network-latency differential (see --calibrate)
run in EXP-4 analysis, NOT live.

Design priorities (in order): (1) never let one venue's failure kill the
other, (2) reconnect forever with exponential backoff and re-subscribe,
(3) crash-safe append-only logging with per-write flush, (4) heartbeat so we
can tell "quiet but alive" from "silently dead".

Venue modes:
  * polymarket -> WEBSOCKET  wss://ws-subscriptions-clob.polymarket.com/ws/market
  * kalshi     -> WEBSOCKET  authenticated orderbook_delta (RSA-PSS handshake),
                  auto-degrades to REST_POLL (GET /markets/{ticker}/orderbook)
                  if credentials/connection fail at startup or mid-run.

Kalshi WS book handling: Kalshi sends an orderbook_snapshot then bid-only
deltas (yes/no resting bids; an ask at price P is the complement of a contra
bid at 1-P). We maintain local book state per market and reconstruct
best_bid/best_ask by REUSING src/pm_micro/normalize.normalize_kalshi_orderbook
(the same complementarity logic the REST path uses). No edits to normalize.py.

Each venue logs its mode at startup and in every STATUS heartbeat, so the
capture file is self-documenting about which transport produced each row.

Credentials (only needed for the Kalshi WS path; REST fallback needs none):
    Read from .env / env, env-aware with generic fallback (values are never
    printed/logged):
      --kalshi-env prod -> KALSHI_PROD_ACCESS_KEY_ID, KALSHI_PROD_PRIVATE_KEY_PATH
      --kalshi-env demo -> KALSHI_DEMO_ACCESS_KEY_ID, KALSHI_DEMO_PRIVATE_KEY_PATH
      fallback (either)  -> KALSHI_ACCESS_KEY_ID, KALSHI_PRIVATE_KEY_PATH
    Without them the client runs Kalshi in REST_POLL mode automatically.

Usage:
    uv run python scripts/ws_leadlag.py --duration 180            # smoke
    uv run python scripts/ws_leadlag.py --test-reconnect          # PM gate
    uv run python scripts/ws_leadlag.py --test-reconnect --reconnect-venue kalshi
    uv run python scripts/ws_leadlag.py --calibrate               # latency diff
    uv run python scripts/ws_leadlag.py --kalshi-env demo --duration 180

Live session (see --print-launch):
    caffeinate -i uv run python scripts/ws_leadlag.py \\
        --out data/raw/ws_leadlag/colombia_r1
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
import signal
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pm_micro.normalize import normalize_kalshi_orderbook  # noqa: E402

MARKETS_YAML = ROOT / "markets.yaml"

PM_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
KALSHI_REST = "https://api.elections.kalshi.com/trade-api/v2"

# WS hosts. Demo is confirmed; prod host verified from the AsyncAPI spec at
# docs.kalshi.com/websockets/orderbook-updates (host: external-api-ws.kalshi.com,
# i.e. .com — NOT the .co the task brief tentatively listed).
KALSHI_WS_URLS = {
    "demo": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
    "prod": "wss://external-api-ws.kalshi.com/trade-api/ws/v2",
}
KALSHI_WS_PATH = "/trade-api/ws/v2"   # signed path component
KALSHI_REST_HOSTS = {
    "demo": "https://demo-api.kalshi.co/trade-api/v2",
    "prod": "https://api.elections.kalshi.com/trade-api/v2",
}

# Calibration endpoints (lightweight, public, no auth) used only by --calibrate.
KALSHI_PING_URL = "https://api.elections.kalshi.com/trade-api/v2/exchange/status"
PM_PING_URL = "https://clob.polymarket.com/ok"

DEFAULT_MARKETS = [
    "intl_president_co_aesp",
    "intl_president_co_pval",
    "intl_president_r1_co_icas",
    "nba_finals_okc",
    "nba_finals_sas",
    "intl_president_pe_rpal",
    "intl_mayor_kr_oseh",
    "us_mayor_la_kbas",
]

BACKOFF_SCHEDULE = [0.5, 1.0, 2.0, 4.0, 8.0]
BACKOFF_CAP = 8.0
HEARTBEAT_S = 30.0
PM_PING_S = 10.0
# Consecutive failed Kalshi WS (re)connections before degrading to REST_POLL.
KALSHI_WS_MAX_FAILS = 4


# =========================================================================
# Time + record helpers (pure, unit-tested)
# =========================================================================

def utc_now_iso() -> str:
    """tz-aware UTC ISO-8601 string for the current instant."""
    return datetime.now(timezone.utc).isoformat()


def exchange_ts_to_iso(raw_ts) -> str | None:
    """Convert a venue-provided millisecond epoch (str/int) to tz-aware ISO.

    Polymarket sends `timestamp` as a string of epoch milliseconds. Returns
    None for missing/unparseable values (the field is nullable by design).
    """
    if raw_ts is None:
        return None
    try:
        ms = float(raw_ts)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _best_bid_ask(bids, asks):
    """Return (best_bid, best_ask, mid) from Polymarket book level lists.

    PM book `bids`/`asks` are lists of {"price","size"} as strings; bids are
    NOT guaranteed sorted, so we take max(bid)/min(ask) defensively. Returns
    (None, None, None) components where a side is empty.
    """
    bb = ba = None
    if bids:
        bb = max(float(b["price"]) for b in bids if b.get("price") is not None)
    if asks:
        ba = min(float(a["price"]) for a in asks if a.get("price") is not None)
    mid = (bb + ba) / 2.0 if (bb is not None and ba is not None) else None
    return bb, ba, mid


def parse_pm_book(msg: dict, asset_to_market: dict) -> dict | None:
    """Parse a Polymarket `book` event into a normalized log record (no ts).

    Returns None if the event is not a book/price snapshot we track.
    """
    et = msg.get("event_type")
    asset_id = msg.get("asset_id")
    if asset_id is None or asset_id not in asset_to_market:
        return None
    market_id, side = asset_to_market[asset_id]
    if et == "book":
        bb, ba, mid = _best_bid_ask(msg.get("bids"), msg.get("asks"))
    elif et == "best_bid_ask":
        bb = float(msg["best_bid"]) if msg.get("best_bid") is not None else None
        ba = float(msg["best_ask"]) if msg.get("best_ask") is not None else None
        mid = (bb + ba) / 2.0 if (bb is not None and ba is not None) else None
    else:
        return None
    return {
        "venue": "polymarket",
        "market_id": market_id,
        "side": side,
        "event_type": et,
        "best_bid": bb,
        "best_ask": ba,
        "mid": mid,
        "exchange_ts": exchange_ts_to_iso(msg.get("timestamp")),
        "raw_seq": msg.get("hash"),
    }


def parse_kalshi_orderbook(raw: dict, market_id: str) -> dict:
    """Parse a Kalshi REST orderbook dict into a normalized log record (no ts).

    Kalshi returns orderbook_fp.{yes_dollars,no_dollars}, both BID arrays of
    [price, size]. YES best bid = max yes_dollars price; YES best ask =
    1 - max(no_dollars price). All nullable when a side is empty.
    """
    ob = raw.get("orderbook_fp") or raw.get("orderbook") or {}
    yes_bids = ob.get("yes_dollars") or []
    no_bids = ob.get("no_dollars") or []
    bb = max((float(p) for p, _ in yes_bids), default=None)
    best_no = max((float(p) for p, _ in no_bids), default=None)
    ba = round(1.0 - best_no, 4) if best_no is not None else None
    mid = (bb + ba) / 2.0 if (bb is not None and ba is not None) else None
    return {
        "venue": "kalshi",
        "market_id": market_id,
        "side": "yes",
        "event_type": "rest_poll",
        "best_bid": bb,
        "best_ask": ba,
        "mid": mid,
        "exchange_ts": None,   # REST orderbook carries no per-book exchange ts
        "raw_seq": None,
    }


def next_backoff(attempt: int) -> float:
    """Exponential backoff with cap. attempt is 0-indexed."""
    if attempt < len(BACKOFF_SCHEDULE):
        return BACKOFF_SCHEDULE[attempt]
    return BACKOFF_CAP


# =========================================================================
# Kalshi WS auth (RSA-PSS SHA256) — pure, unit-tested
# =========================================================================

def kalshi_sign_pss(private_key, ts_ms: str, method: str, path: str) -> str:
    """Sign `ts_ms + method + path` with RSA-PSS/SHA256, base64-encoded.

    Mirrors Kalshi's documented `sign_pss_text`. `private_key` is a
    cryptography RSAPrivateKey. Pure function (no I/O) for unit testing.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    message = (ts_ms + method + path).encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def kalshi_auth_headers(key_id: str, private_key, path: str = KALSHI_WS_PATH) -> dict:
    """Build fresh Kalshi handshake headers (timestamp regenerated each call).

    Headers MUST be regenerated per connection/reconnect because the signed
    timestamp must be recent. Never logs key material.
    """
    ts_ms = str(int(time.time() * 1000))
    sig = kalshi_sign_pss(private_key, ts_ms, "GET", path)
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
    }


def load_dotenv_value(*keys: str) -> dict:
    """Read selected keys from .env (if present) then os.environ. No printing.

    Returns a dict of {key: value} for keys that resolve. Values are never
    logged by callers.
    """
    found: dict[str, str] = {}
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            found[k.strip()] = v.strip().strip('"').strip("'")
    for k in keys:
        if os.environ.get(k):
            found[k] = os.environ[k]
    return {k: found[k] for k in keys if k in found and found[k]}


def kalshi_credential_env_names(env: str = "prod") -> tuple[list[str], list[str]]:
    """Return (id_name_candidates, path_name_candidates) for the given env.

    Env-specific names take precedence (KALSHI_PROD_* / KALSHI_DEMO_*), with a
    fallback to the generic unprefixed names from the original brief.
    """
    prefix = "KALSHI_PROD_" if env == "prod" else "KALSHI_DEMO_"
    id_keys = [f"{prefix}ACCESS_KEY_ID", "KALSHI_ACCESS_KEY_ID"]
    path_keys = [f"{prefix}PRIVATE_KEY_PATH", "KALSHI_PRIVATE_KEY_PATH"]
    return id_keys, path_keys


def _load_rsa_private_key(value: str):
    """Load an RSA private key from a file PATH or inline key material.

    Accepts (in order): an existing file path; raw PEM text; or bare base64
    (PKCS#1/PKCS#8 DER with the armor/newlines stripped, as some .env setups
    store it). Returns the key object or None. Never logs key material.
    """
    import base64 as _b64
    import re

    from cryptography.hazmat.primitives import serialization

    # 1) filesystem path (guard against absurdly long "paths" that are keys)
    if len(value) < 4096:
        with contextlib.suppress(OSError):
            p = Path(value).expanduser()
            if not p.is_absolute():
                p = ROOT / p
            if p.exists():
                with contextlib.suppress(Exception):
                    return serialization.load_pem_private_key(p.read_bytes(),
                                                              password=None)
                with contextlib.suppress(Exception):
                    return serialization.load_der_private_key(p.read_bytes(),
                                                              password=None)

    # 2) inline material. Try as-is PEM, then compact-base64 -> DER, then
    #    re-armored PKCS#1 / PKCS#8 PEM.
    with contextlib.suppress(Exception):
        return serialization.load_pem_private_key(value.encode(), password=None)
    compact = re.sub(r"\s+", "", value)
    if re.fullmatch(r"[A-Za-z0-9+/=]+", compact or ""):
        with contextlib.suppress(Exception):
            return serialization.load_der_private_key(_b64.b64decode(compact),
                                                      password=None)
        wrapped = "\n".join(compact[i:i + 64] for i in range(0, len(compact), 64))
        for hdr in ("RSA PRIVATE KEY", "PRIVATE KEY"):
            pem = f"-----BEGIN {hdr}-----\n{wrapped}\n-----END {hdr}-----\n"
            with contextlib.suppress(Exception):
                return serialization.load_pem_private_key(pem.encode(),
                                                          password=None)
    return None


def load_kalshi_credentials(env: str = "prod"):
    """Return (key_id, private_key) or None if unavailable. Never prints key.

    Reads env-specific names first (KALSHI_PROD_* / KALSHI_DEMO_*), then the
    generic names. The key value may be a file PATH or inline key material.
    Any failure returns None so the caller degrades to REST cleanly.
    """
    id_keys, path_keys = kalshi_credential_env_names(env)
    creds = load_dotenv_value(*id_keys, *path_keys)
    key_id = next((creds[k] for k in id_keys if creds.get(k)), None)
    key_val = next((creds[k] for k in path_keys if creds.get(k)), None)
    if not key_id or not key_val:
        return None
    private_key = _load_rsa_private_key(key_val)
    if private_key is None:
        return None
    return key_id, private_key


# =========================================================================
# Kalshi WS local orderbook state (snapshot + deltas) — pure, unit-tested
# =========================================================================

class KalshiBook:
    """Local orderbook state for one Kalshi market, fed by snapshot + deltas.

    State is held as {side: {price_float: size_float}} for the resting BID
    side of each outcome (yes/no), exactly as Kalshi streams it. Best bid/ask
    reconstruction (via complementarity) is delegated to normalize.py.
    """

    def __init__(self) -> None:
        self.yes: dict[float, float] = {}
        self.no: dict[float, float] = {}

    @staticmethod
    def _key(price) -> float:
        return round(float(price), 4)

    def apply_snapshot(self, yes_levels, no_levels) -> None:
        """Replace state from snapshot arrays of [price_dollars, size_fp]."""
        self.yes = {self._key(p): float(s) for p, s in (yes_levels or [])}
        self.no = {self._key(p): float(s) for p, s in (no_levels or [])}

    def apply_delta(self, side: str, price, delta) -> None:
        """Apply a signed size delta at a price level; drop levels that hit <=0."""
        book = self.yes if side == "yes" else self.no
        k = self._key(price)
        new_size = book.get(k, 0.0) + float(delta)
        if new_size > 1e-9:
            book[k] = new_size
        else:
            book.pop(k, None)

    def to_orderbook_fp(self) -> dict:
        """Render to the REST-shaped dict normalize_kalshi_orderbook consumes."""
        return {
            "orderbook_fp": {
                "yes_dollars": [[f"{p:.4f}", s] for p, s in self.yes.items()],
                "no_dollars": [[f"{p:.4f}", s] for p, s in self.no.items()],
            }
        }


def reconstruct_kalshi_record(book: KalshiBook, market_id: str,
                              exchange_ts_iso: str | None, seq) -> dict:
    """Reconstruct a top-of-book log record from local Kalshi book state.

    Reuses normalize_kalshi_orderbook for the bid-only -> both-sides
    complementarity (YES ask = 1 - best NO bid). Returns the SAME row schema
    as the Polymarket WS path.
    """
    yes_book, _no_book = normalize_kalshi_orderbook(
        book.to_orderbook_fp(), market_id, fetched_at=""
    )
    bb = yes_book.bids[0].price if yes_book.bids else None
    ba = yes_book.asks[0].price if yes_book.asks else None
    mid = (bb + ba) / 2.0 if (bb is not None and ba is not None) else None
    return {
        "venue": "kalshi",
        "market_id": market_id,
        "side": "yes",
        "event_type": "ws_orderbook",
        "best_bid": bb,
        "best_ask": ba,
        "mid": mid,
        "exchange_ts": exchange_ts_iso,
        "raw_seq": seq,
    }


# =========================================================================
# Append-only crash-safe writer + per-venue stats
# =========================================================================

class JsonlWriter:
    """Append-only JSONL writer that flushes + fsyncs per record."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", buffering=1)  # line-buffered

    def write(self, record: dict) -> None:
        self._fh.write(json.dumps(record) + "\n")
        self._fh.flush()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._fh.flush()
            self._fh.close()


@dataclass
class VenueStats:
    venue: str
    mode: str
    state: str = "init"
    total_msgs: int = 0
    msgs_since_status: int = 0
    reconnects: int = 0
    last_msg_monotonic: float = field(default_factory=time.monotonic)
    total_downtime_s: float = 0.0
    _down_since: float | None = None

    def on_msg(self) -> None:
        self.total_msgs += 1
        self.msgs_since_status += 1
        self.last_msg_monotonic = time.monotonic()

    def mark_down(self) -> None:
        if self._down_since is None:
            self._down_since = time.monotonic()
        self.state = "reconnecting"

    def mark_up(self) -> None:
        if self._down_since is not None:
            self.total_downtime_s += time.monotonic() - self._down_since
            self._down_since = None
        self.state = "connected"

    def secs_since_last_msg(self) -> float:
        return time.monotonic() - self.last_msg_monotonic


# =========================================================================
# Market config loading
# =========================================================================

def load_market_config(market_ids: list[str], include_no: bool):
    """Return (kalshi_tickers: dict[mid->ticker], asset_to_market: dict[token->(mid,side)])."""
    with open(MARKETS_YAML) as f:
        entries = {e["id"]: e for e in yaml.safe_load(f)}
    kalshi_tickers: dict[str, str] = {}
    asset_to_market: dict[str, tuple[str, str]] = {}
    for mid in market_ids:
        e = entries.get(mid)
        if not e:
            print(f"  WARN: {mid} not in markets.yaml; skipping", file=sys.stderr)
            continue
        kalshi_tickers[mid] = e["kalshi"]["ticker"]
        poly = e["polymarket"]
        yes_tok = poly.get("yes_token_id")
        if yes_tok:
            asset_to_market[yes_tok] = (mid, "yes")
        if include_no and poly.get("no_token_id"):
            asset_to_market[poly["no_token_id"]] = (mid, "no")
    return kalshi_tickers, asset_to_market


# =========================================================================
# Polymarket websocket task
# =========================================================================

async def polymarket_task(
    asset_to_market: dict,
    writer: JsonlWriter,
    stats: VenueStats,
    stop: asyncio.Event,
    inject_drop_after: int | None = None,
):
    """Stream PM market channel; reconnect forever; re-subscribe on connect.

    `inject_drop_after`: if set, force-close the socket after that many
    messages (used by --test-reconnect to prove self-healing).
    """
    import websockets

    asset_ids = list(asset_to_market.keys())
    attempt = 0
    dropped_once = False
    while not stop.is_set():
        try:
            async with websockets.connect(
                PM_WS_URL, ping_interval=None, open_timeout=15, close_timeout=5
            ) as ws:
                sub = {"assets_ids": asset_ids, "type": "market",
                       "custom_feature_enabled": True}
                await ws.send(json.dumps(sub))
                if stats.reconnects > 0 or attempt > 0:
                    _log_reconnect(writer, stats)
                stats.mark_up()
                attempt = 0
                ping_task = asyncio.create_task(_pm_ping(ws, stop))
                try:
                    async for raw in ws:
                        if stop.is_set():
                            break
                        local_recv = utc_now_iso()
                        if raw == "PONG" or raw == "PING":
                            continue
                        _handle_pm_payload(raw, local_recv, asset_to_market,
                                           writer, stats)
                        # Reconnection self-test hook: drop mid-stream once.
                        if (inject_drop_after is not None and not dropped_once
                                and stats.total_msgs >= inject_drop_after):
                            dropped_once = True
                            await ws.close(code=1011, reason="test-injected drop")
                            break
                finally:
                    ping_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await ping_task
        except asyncio.CancelledError:
            raise
        except Exception as e:
            stats.mark_down()
            _log_event(writer, "ERROR", "polymarket", stats, detail=repr(e)[:200])
        if stop.is_set():
            break
        stats.mark_down()
        delay = next_backoff(attempt)
        attempt += 1
        stats.reconnects += 1
        await _sleep_or_stop(delay, stop)
    stats.state = "stopped"


def _handle_pm_payload(raw, local_recv, asset_to_market, writer, stats):
    """A PM frame may be a single dict or a list of event dicts."""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return
    events = payload if isinstance(payload, list) else [payload]
    for ev in events:
        if not isinstance(ev, dict):
            continue
        rec = parse_pm_book(ev, asset_to_market)
        if rec is None:
            continue
        rec["local_recv_utc"] = local_recv
        writer.write(rec)
        stats.on_msg()


async def _pm_ping(ws, stop: asyncio.Event):
    """Send a literal PING text frame every PM_PING_S (PM keepalive protocol)."""
    try:
        while not stop.is_set():
            await asyncio.sleep(PM_PING_S)
            with contextlib.suppress(Exception):
                await ws.send("PING")
    except asyncio.CancelledError:
        return


# =========================================================================
# Kalshi REST poll task
# =========================================================================

async def kalshi_task(
    kalshi_tickers: dict,
    writer: JsonlWriter,
    stats: VenueStats,
    stop: asyncio.Event,
    poll_s: float,
    rest_host: str = KALSHI_REST,
):
    """Poll each Kalshi market's orderbook every poll_s; reconnect forever.

    Uses httpx.AsyncClient. A failure on one cycle backs off but never kills
    the task or the other venue.
    """
    import httpx

    stats.mode = "REST_POLL"
    attempt = 0
    while not stop.is_set():
        try:
            async with httpx.AsyncClient(base_url=rest_host, timeout=8.0) as client:
                if stats.reconnects > 0 or attempt > 0:
                    _log_reconnect(writer, stats)
                stats.mark_up()
                attempt = 0
                while not stop.is_set():
                    cycle_start = time.monotonic()
                    for mid, ticker in kalshi_tickers.items():
                        if stop.is_set():
                            break
                        try:
                            r = await client.get(f"/markets/{ticker}/orderbook")
                            r.raise_for_status()
                            rec = parse_kalshi_orderbook(r.json(), mid)
                            rec["local_recv_utc"] = utc_now_iso()
                            writer.write(rec)
                            stats.on_msg()
                        except Exception as e:
                            _log_event(writer, "ERROR", "kalshi", stats,
                                       detail=f"{ticker}: {repr(e)[:160]}")
                    elapsed = time.monotonic() - cycle_start
                    await _sleep_or_stop(max(0.0, poll_s - elapsed), stop)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            stats.mark_down()
            _log_event(writer, "ERROR", "kalshi", stats, detail=repr(e)[:200])
        if stop.is_set():
            break
        stats.mark_down()
        delay = next_backoff(attempt)
        attempt += 1
        stats.reconnects += 1
        await _sleep_or_stop(delay, stop)
    stats.state = "stopped"


# =========================================================================
# Kalshi authenticated WEBSOCKET task (orderbook_delta) + selection
# =========================================================================

class _AuthFailure(Exception):
    """Raised when the Kalshi WS handshake is rejected (bad/again-rejected auth)."""


async def kalshi_ws_task(
    kalshi_tickers: dict,
    writer: JsonlWriter,
    stats: VenueStats,
    stop: asyncio.Event,
    creds,
    ws_url: str,
    inject_drop_after: int | None = None,
) -> bool:
    """Stream Kalshi orderbook_delta over an authenticated WS; reconnect forever.

    Returns True if it exited because `stop` was set (clean), or False to
    signal the caller to DEGRADE to the REST poll (auth rejected at startup,
    or KALSHI_WS_MAX_FAILS consecutive (re)connect failures mid-run).

    Auth headers are regenerated on EVERY connection attempt (the signed
    timestamp must be fresh). Local book state is rebuilt from the snapshot on
    each (re)connect, so a reconnect self-heals the book.
    """
    import websockets

    key_id, private_key = creds
    tickers = list(kalshi_tickers.values())
    ticker_to_mid = {t: m for m, t in kalshi_tickers.items()}
    books: dict[str, KalshiBook] = {t: KalshiBook() for t in tickers}
    last_seq: dict[int, int] = {}
    attempt = 0
    consecutive_fails = 0
    dropped_once = False

    while not stop.is_set():
        try:
            headers = kalshi_auth_headers(key_id, private_key)  # fresh per connect
            async with websockets.connect(
                ws_url, additional_headers=headers, ping_interval=10,
                ping_timeout=10, open_timeout=15, close_timeout=5,
            ) as ws:
                sub = {"id": 1, "cmd": "subscribe",
                       "params": {"channels": ["orderbook_delta"],
                                  "market_tickers": tickers}}
                await ws.send(json.dumps(sub))
                for b in books.values():        # reset book state on (re)connect
                    b.yes.clear(); b.no.clear()
                last_seq.clear()
                if stats.reconnects > 0 or attempt > 0:
                    _log_reconnect(writer, stats)
                stats.mark_up()
                attempt = 0
                consecutive_fails = 0
                async for raw in ws:
                    if stop.is_set():
                        break
                    local_recv = utc_now_iso()
                    _handle_kalshi_ws_msg(raw, local_recv, books, ticker_to_mid,
                                          last_seq, writer, stats)
                    if (inject_drop_after is not None and not dropped_once
                            and stats.total_msgs >= inject_drop_after):
                        dropped_once = True
                        await ws.close(code=1011, reason="test-injected drop")
                        break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Distinguish auth rejection (don't waste retries on a bad key) from
            # transient network failures (retry with backoff).
            is_auth = _is_auth_rejection(e)
            stats.mark_down()
            _log_event(writer, "ERROR", "kalshi", stats,
                       detail=("AUTH_REJECTED " if is_auth else "") + repr(e)[:180])
            if is_auth and stats.total_msgs == 0:
                # Never authenticated -> WS is not usable; degrade now.
                _log_event(writer, "MODE_DEGRADE", "kalshi", stats,
                           detail="WS auth rejected at startup; degrading to REST_POLL")
                return False
        if stop.is_set():
            break
        consecutive_fails += 1
        if consecutive_fails >= KALSHI_WS_MAX_FAILS:
            _log_event(writer, "MODE_DEGRADE", "kalshi", stats,
                       detail=f"{consecutive_fails} consecutive WS failures; "
                              f"degrading to REST_POLL")
            return False
        stats.mark_down()
        delay = next_backoff(attempt)
        attempt += 1
        stats.reconnects += 1
        await _sleep_or_stop(delay, stop)
    stats.state = "stopped"
    return True


def _is_auth_rejection(exc: Exception) -> bool:
    """Best-effort detection of a handshake auth rejection (HTTP 401/403)."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return True
    text = repr(exc).lower()
    return "401" in text or "403" in text or "unauthor" in text


def _handle_kalshi_ws_msg(raw, local_recv, books, ticker_to_mid, last_seq,
                          writer, stats):
    """Apply one Kalshi WS frame to local book state and log a row if relevant."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return
    mtype = data.get("type")
    msg = data.get("msg") or {}
    ticker = msg.get("market_ticker")
    if mtype not in ("orderbook_snapshot", "orderbook_delta"):
        return
    if ticker not in ticker_to_mid:
        return
    book = books[ticker]
    sid = data.get("sid")
    seq = data.get("seq")
    # Sequence-gap detection: deltas must increment by 1 within a sid. A gap
    # means we missed a message and local state is stale -> log and resnapshot
    # via reconnect (raising forces the connection loop to re-subscribe).
    if mtype == "orderbook_delta" and sid is not None and seq is not None:
        prev = last_seq.get(sid)
        if prev is not None and seq != prev + 1:
            _log_event(writer, "SEQ_GAP", "kalshi", stats,
                       detail=f"sid={sid} expected {prev + 1} got {seq}")
            raise _SeqGap()
    if seq is not None and sid is not None:
        last_seq[sid] = seq

    exch_ts = exchange_ts_to_iso(msg.get("ts_ms"))
    if mtype == "orderbook_snapshot":
        book.apply_snapshot(msg.get("yes_dollars_fp"), msg.get("no_dollars_fp"))
    else:
        book.apply_delta(msg.get("side"), msg.get("price_dollars"),
                         msg.get("delta_fp"))
    rec = reconstruct_kalshi_record(book, ticker_to_mid[ticker], exch_ts, seq)
    rec["local_recv_utc"] = local_recv
    writer.write(rec)
    stats.on_msg()


class _SeqGap(Exception):
    """Internal: raised on a detected orderbook sequence gap to force resnapshot."""


async def kalshi_capture_task(
    kalshi_tickers: dict,
    writer: JsonlWriter,
    stats: VenueStats,
    stop: asyncio.Event,
    poll_s: float,
    creds,
    ws_url: str,
    rest_host: str,
    force_rest: bool = False,
    inject_drop_after: int | None = None,
):
    """Kalshi capture dispatcher: WS-first, automatic REST_POLL degradation.

    Tries the authenticated WS path when credentials are present; on auth/
    connection failure (startup or mid-run) it degrades to the REST poll and
    never loses Kalshi capture. With no creds (or --force-rest) it goes
    straight to REST. `stats.mode` reflects the live transport for STATUS.
    """
    if creds is not None and not force_rest:
        stats.mode = "WEBSOCKET"
        _log_event(writer, "MODE", "kalshi", stats,
                   detail=f"Kalshi WS attempt ({ws_url})")
        try:
            clean = await kalshi_ws_task(kalshi_tickers, writer, stats, stop,
                                         creds, ws_url, inject_drop_after)
        except asyncio.CancelledError:
            raise
        if clean or stop.is_set():
            return
        # Degraded: fall through to REST for the remainder of the session.
    stats.mode = "REST_POLL"
    stats.state = "init"
    _log_event(writer, "MODE", "kalshi", stats, detail="Kalshi REST_POLL active")
    await kalshi_task(kalshi_tickers, writer, stats, stop, poll_s, rest_host)


# =========================================================================
# Event logging + heartbeat
# =========================================================================

def _log_event(writer, kind, venue, stats, detail=""):
    writer.write({
        "local_recv_utc": utc_now_iso(),
        "record_type": kind,
        "venue": venue,
        "state": stats.state,
        "total_msgs": stats.total_msgs,
        "reconnects": stats.reconnects,
        "detail": detail,
    })


def _log_reconnect(writer, stats):
    gap = 0.0
    if stats._down_since is not None:
        gap = time.monotonic() - stats._down_since
    writer.write({
        "local_recv_utc": utc_now_iso(),
        "record_type": "RECONNECT",
        "venue": stats.venue,
        "reconnects": stats.reconnects,
        "gap_seconds": round(gap, 3),
        "total_msgs": stats.total_msgs,
    })


async def heartbeat_task(writer, all_stats, stop: asyncio.Event):
    while not stop.is_set():
        await _sleep_or_stop(HEARTBEAT_S, stop)
        if stop.is_set():
            break
        for stats in all_stats:
            line = {
                "local_recv_utc": utc_now_iso(),
                "record_type": "STATUS",
                "venue": stats.venue,
                "mode": stats.mode,
                "state": stats.state,
                "msgs_since_last_status": stats.msgs_since_status,
                "total_msgs": stats.total_msgs,
                "secs_since_last_msg": round(stats.secs_since_last_msg(), 1),
                "reconnects": stats.reconnects,
            }
            writer.write(line)
            print(f"STATUS {stats.venue:11s} mode={stats.mode} state={stats.state} "
                  f"+{stats.msgs_since_status} (total {stats.total_msgs}) "
                  f"last_msg {line['secs_since_last_msg']}s ago "
                  f"reconnects={stats.reconnects}")
            stats.msgs_since_status = 0


# =========================================================================
# Coordination helpers
# =========================================================================

async def _sleep_or_stop(delay: float, stop: asyncio.Event) -> None:
    """Sleep up to `delay`, waking early if stop is set."""
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=delay)


# =========================================================================
# Runners
# =========================================================================

async def run_capture(market_ids, out_dir, duration, include_no, kalshi_poll_s,
                      kalshi_env="prod", force_rest=False,
                      inject_drop_after=None, inject_drop_venue="polymarket"):
    kalshi_tickers, asset_to_market = load_market_config(market_ids, include_no)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = Path(out_dir) / f"{date}.jsonl"
    writer = JsonlWriter(out_path)

    ws_url = KALSHI_WS_URLS[kalshi_env]
    rest_host = KALSHI_REST_HOSTS[kalshi_env]
    creds = None if force_rest else load_kalshi_credentials(kalshi_env)
    kalshi_mode = "WEBSOCKET" if (creds is not None and not force_rest) else "REST_POLL"

    pm_stats = VenueStats("polymarket", "WEBSOCKET")
    k_stats = VenueStats("kalshi", kalshi_mode)
    all_stats = [pm_stats, k_stats]

    _log_event(writer, "SESSION_START", "client", pm_stats,
               detail=(f"markets={len(market_ids)} pm_assets={len(asset_to_market)} "
                       f"kalshi_tickers={len(kalshi_tickers)} pm=WEBSOCKET "
                       f"kalshi={kalshi_mode} kalshi_env={kalshi_env} "
                       f"creds={'present' if creds else 'absent'}"))
    print(f"Logging to {out_path}")
    print(f"  polymarket: WEBSOCKET  ({len(asset_to_market)} tokens)")
    if kalshi_mode == "WEBSOCKET":
        print(f"  kalshi:     WEBSOCKET ({kalshi_env}) auth=present "
              f"-> auto-degrades to REST_POLL@{kalshi_poll_s}s on failure "
              f"({len(kalshi_tickers)} tickers)")
    else:
        print(f"  kalshi:     REST_POLL @ {kalshi_poll_s}s ({kalshi_env}) "
              f"creds={'forced-off' if force_rest else 'absent'} "
              f"({len(kalshi_tickers)} tickers)")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    pm_drop = inject_drop_after if inject_drop_venue == "polymarket" else None
    k_drop = inject_drop_after if inject_drop_venue == "kalshi" else None
    tasks = [
        asyncio.create_task(polymarket_task(asset_to_market, writer, pm_stats,
                                            stop, pm_drop)),
        asyncio.create_task(kalshi_capture_task(
            kalshi_tickers, writer, k_stats, stop, kalshi_poll_s, creds,
            ws_url, rest_host, force_rest, k_drop)),
        asyncio.create_task(heartbeat_task(writer, all_stats, stop)),
    ]

    if duration is not None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=duration)
        stop.set()
    else:
        await stop.wait()

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    summary = {
        "local_recv_utc": utc_now_iso(),
        "record_type": "SESSION_SUMMARY",
        "polymarket": _stats_dict(pm_stats),
        "kalshi": _stats_dict(k_stats),
    }
    writer.write(summary)
    writer.close()
    print("\n=== SESSION SUMMARY ===")
    for s in all_stats:
        print(f"  {s.venue:11s} mode={s.mode} total_msgs={s.total_msgs} "
              f"reconnects={s.reconnects} downtime={s.total_downtime_s:.1f}s")
    return summary


def _stats_dict(s: VenueStats) -> dict:
    return {"mode": s.mode, "total_msgs": s.total_msgs, "reconnects": s.reconnects,
            "total_downtime_s": round(s.total_downtime_s, 2), "final_state": s.state}


async def run_reconnect_test(market_ids, kalshi_poll_s, venue="polymarket",
                             kalshi_env="demo"):
    """Force a socket drop mid-stream on `venue`; confirm self-heal.

    Verifies: reconnect + re-subscribe + resume + RECONNECT row on the target
    venue, AND that the OTHER venue is unaffected (one drop never kills the
    other). For kalshi this exercises the authenticated WS path (re-auth with
    a fresh timestamp on reconnect); it requires credentials.
    """
    import tempfile

    if venue == "kalshi" and load_kalshi_credentials(kalshi_env) is None:
        print("\n=== RECONNECT TEST RESULT (kalshi) ===")
        print("  BLOCKED: no Kalshi credentials present (.env missing "
              "KALSHI_ACCESS_KEY_ID / KALSHI_PRIVATE_KEY_PATH).")
        print("  Cannot exercise the authenticated WS reconnect path. "
              "Provide demo creds and re-run.")
        return None

    tmp = Path(tempfile.mkdtemp(prefix="ws_reconnect_test_"))
    out_dir = tmp / "rc"
    other = "kalshi" if venue == "polymarket" else "polymarket"
    print(f"[reconnect-test:{venue}] capturing to {out_dir}; injecting a drop "
          f"after 3 {venue} messages, then verifying self-heal "
          f"(and that {other} is unaffected)...")

    summary = await run_capture(
        market_ids, out_dir, duration=50, include_no=False,
        kalshi_poll_s=kalshi_poll_s, kalshi_env=kalshi_env,
        inject_drop_after=3, inject_drop_venue=venue,
    )

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = out_dir / f"{date}.jsonl"
    rows = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    reconnects = [r for r in rows if r.get("record_type") == "RECONNECT"
                  and r.get("venue") == venue]
    data_msgs = [r for r in rows if r.get("venue") == venue
                 and r.get("record_type") is None]
    after = [r for r in data_msgs
             if reconnects and r["local_recv_utc"] > reconnects[0]["local_recv_utc"]]
    other_msgs = [r for r in rows if r.get("venue") == other
                  and r.get("record_type") is None]

    print(f"\n=== RECONNECT TEST RESULT ({venue}) ===")
    print(f"  {venue} reconnect events logged: {len(reconnects)}")
    if reconnects:
        print(f"  first RECONNECT gap_seconds: {reconnects[0].get('gap_seconds')}")
    print(f"  {venue} data msgs total: {len(data_msgs)}; after reconnect: {len(after)}")
    print(f"  {other} data msgs (should be >0, proving independence): {len(other_msgs)}")
    passed = (summary[venue]["reconnects"] >= 1
              and len(reconnects) >= 1
              and len(after) >= 1
              and len(other_msgs) >= 1)
    print(f"\n  RECONNECT TEST ({venue}): {'PASS' if passed else 'FAIL'}")
    if not passed:
        print("  -> did NOT prove self-heal; NOT trusted for live use.")
    return passed


# =========================================================================
# Network-latency differential calibration (--calibrate)
# =========================================================================

async def run_calibrate(duration=60.0, interval=1.0):
    """Estimate one-way network latency to each venue and write a report.

    Method: repeated lightweight HTTPS GETs to a public endpoint on each
    venue's edge; record wall-clock RTT (DNS+TCP+TLS reused via a persistent
    client, so steady-state ~= TCP round trip + server handling). One-way is
    approximated as RTT/2 under a symmetric-path assumption. This is what
    EXP-4 (F.2) subtracts before claiming any sub-second cross-venue lead.
    """
    import httpx

    samples = {"kalshi": [], "polymarket": []}
    endpoints = {"kalshi": KALSHI_PING_URL, "polymarket": PM_PING_URL}
    print(f"[calibrate] sampling RTT to each venue for ~{duration:.0f}s "
          f"every {interval:.1f}s...")
    deadline = time.monotonic() + duration
    async with httpx.AsyncClient(timeout=8.0) as client:
        # one warm-up per host (establish TCP/TLS so we measure steady state)
        for url in endpoints.values():
            with contextlib.suppress(Exception):
                await client.get(url)
        while time.monotonic() < deadline:
            for venue, url in endpoints.items():
                t0 = time.perf_counter()
                try:
                    await client.get(url)
                    samples[venue].append((time.perf_counter() - t0) * 1000.0)
                except Exception:
                    pass  # transient failure; just skip this sample
            await asyncio.sleep(interval)

    def stats(xs):
        if not xs:
            return None
        xs = sorted(xs)
        p90 = xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]
        return {"n": len(xs), "median": statistics.median(xs), "p90": p90}

    k, p = stats(samples["kalshi"]), stats(samples["polymarket"])
    out = ROOT / "data/processed/network_latency_calibration.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    now = utc_now_iso()

    def fmt(s):
        return ("n/a (no successful samples)" if not s
                else f"{s['median']:.1f} ms median / {s['p90']:.1f} ms p90 (n={s['n']})")

    diff_line = "n/a (insufficient samples)"
    if k and p:
        diff_rtt = k["median"] - p["median"]
        diff_oneway = diff_rtt / 2.0
        faster = "Polymarket" if diff_rtt > 0 else "Kalshi"
        diff_line = (f"Median RTT differential (Kalshi - Polymarket): "
                     f"{diff_rtt:+.1f} ms  ->  implied one-way differential "
                     f"{diff_oneway:+.1f} ms ({faster} edge is closer).")

    md = f"""# Network-latency differential calibration (EXP-4b-symmetric)

Generated: {now}

## Purpose
Quantify the network-path skew between this capture host and each venue's
edge, so that EXP-4 / F.2 can subtract it before attributing any sub-second
cross-venue lead to genuine information flow rather than transport latency.

## Method
- Persistent `httpx` client (TCP/TLS warmed once), then repeated lightweight
  public GETs every {interval:.1f}s for ~{duration:.0f}s:
  - Kalshi:     `{KALSHI_PING_URL}`
  - Polymarket: `{PM_PING_URL}`
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

## Results
- Kalshi RTT:     {fmt(k)}
- Polymarket RTT: {fmt(p)}

**{diff_line}**

## How EXP-4 should use this
When comparing a Kalshi event timestamp to a Polymarket event timestamp on the
LOCAL-RECEIVE clock, subtract the implied one-way differential above from the
observed lead before claiming venue A led venue B. If an observed lead is
smaller than this differential (plus its variability), it is within network
noise and NOT evidence of information lead.
"""
    out.write_text(md)
    print("\n=== CALIBRATION RESULT ===")
    print(f"  Kalshi RTT:     {fmt(k)}")
    print(f"  Polymarket RTT: {fmt(p)}")
    print(f"  {diff_line}")
    print(f"  -> wrote {out}")
    return out


# =========================================================================
# CLI
# =========================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--markets", nargs="*", default=DEFAULT_MARKETS,
                   help="market ids from markets.yaml")
    p.add_argument("--out", default=str(ROOT / "data/raw/ws_leadlag/colombia_r1"),
                   help="output directory for <date>.jsonl")
    p.add_argument("--duration", type=float, default=None,
                   help="seconds to run then exit (default: until SIGINT)")
    p.add_argument("--kalshi-poll-s", type=float, default=1.5,
                   help="Kalshi REST poll interval (default 1.5s)")
    p.add_argument("--include-no", action="store_true",
                   help="also subscribe PM NO tokens (default YES only)")
    p.add_argument("--kalshi-env", choices=["demo", "prod"], default="prod",
                   help="Kalshi WS/REST environment (default prod)")
    p.add_argument("--force-rest", action="store_true",
                   help="skip the Kalshi WS path; use REST_POLL only")
    p.add_argument("--test-reconnect", action="store_true",
                   help="run the reconnection self-test and exit PASS/FAIL")
    p.add_argument("--reconnect-venue", choices=["polymarket", "kalshi"],
                   default="polymarket",
                   help="which venue to drop in --test-reconnect (default polymarket)")
    p.add_argument("--calibrate", action="store_true",
                   help="measure network-latency differential and write report")
    p.add_argument("--calibrate-duration", type=float, default=60.0,
                   help="seconds to sample in --calibrate (default 60)")
    p.add_argument("--print-launch", action="store_true",
                   help="print the caffeinate live-launch command and exit")
    return p


def print_launch(args):
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = args.out
    print("# Live launch — NBA Finals Game 1, Wed Jun 3 (PROD, symmetric WS):")
    print(f"caffeinate -i uv run python scripts/ws_leadlag.py "
          f"--kalshi-env prod --out {out}")
    print()
    print("# (Kalshi auto-degrades to REST_POLL if WS auth/connection fails;")
    print("#  confirm mode in the STATUS lines below.)")
    print()
    print("# Confirm it's alive + which transport each venue is on:")
    print(f"tail -f {out}/{date}.jsonl | grep --line-buffered STATUS")
    print()
    print("# Count msgs/venue so far:")
    print(f"grep -c '\"venue\": \"polymarket\"' {out}/{date}.jsonl; "
          f"grep -c '\"venue\": \"kalshi\"' {out}/{date}.jsonl")


def main() -> int:
    args = build_parser().parse_args()
    if args.print_launch:
        print_launch(args)
        return 0
    if args.calibrate:
        asyncio.run(run_calibrate(args.calibrate_duration))
        return 0
    if args.test_reconnect:
        ok = asyncio.run(run_reconnect_test(
            args.markets, args.kalshi_poll_s, args.reconnect_venue, args.kalshi_env))
        return 1 if ok is False else 0  # True=pass / None=blocked -> 0; False=fail -> 1
    asyncio.run(run_capture(args.markets, args.out, args.duration,
                            args.include_no, args.kalshi_poll_s,
                            args.kalshi_env, args.force_rest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
