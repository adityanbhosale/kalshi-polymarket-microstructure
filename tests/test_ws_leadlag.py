"""Unit tests for scripts/ws_leadlag.py (EXP-4b dual-venue capture).

Tests the pure units only — parsing, timestamp conversion, backoff, and the
VenueStats downtime bookkeeping. Live connections are NOT exercised here;
the live smoke test and --test-reconnect cover the network path.
"""

import base64
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ws_leadlag", ROOT / "scripts" / "ws_leadlag.py"
)
ws = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve module annotations.
sys.modules["ws_leadlag"] = ws
_spec.loader.exec_module(ws)


# ---------------------------------------------------------------------------
# timestamp helpers
# ---------------------------------------------------------------------------

def test_utc_now_iso_is_tz_aware():
    s = ws.utc_now_iso()
    dt = datetime.fromisoformat(s)
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timezone.utc.utcoffset(None)


def test_exchange_ts_to_iso_valid_ms():
    # 1_700_000_000_000 ms = 2023-11-14T22:13:20Z
    out = ws.exchange_ts_to_iso("1700000000000")
    dt = datetime.fromisoformat(out)
    assert dt.tzinfo is not None
    assert dt.year == 2023 and dt.month == 11


def test_exchange_ts_to_iso_accepts_int():
    assert ws.exchange_ts_to_iso(1700000000000).startswith("2023-11-")


def test_exchange_ts_to_iso_nullable():
    assert ws.exchange_ts_to_iso(None) is None
    assert ws.exchange_ts_to_iso("") is None
    assert ws.exchange_ts_to_iso("not-a-number") is None
    assert ws.exchange_ts_to_iso(0) is None
    assert ws.exchange_ts_to_iso(-5) is None


# ---------------------------------------------------------------------------
# best_bid_ask
# ---------------------------------------------------------------------------

def test_best_bid_ask_unsorted():
    bids = [{"price": ".48", "size": "30"}, {"price": ".50", "size": "5"},
            {"price": ".49", "size": "20"}]
    asks = [{"price": ".54", "size": "10"}, {"price": ".52", "size": "25"}]
    bb, ba, mid = ws._best_bid_ask(bids, asks)
    assert bb == pytest.approx(0.50)
    assert ba == pytest.approx(0.52)
    assert mid == pytest.approx(0.51)


def test_best_bid_ask_empty_side():
    bb, ba, mid = ws._best_bid_ask([], [{"price": ".52", "size": "1"}])
    assert bb is None
    assert ba == pytest.approx(0.52)
    assert mid is None


# ---------------------------------------------------------------------------
# parse_pm_book
# ---------------------------------------------------------------------------

def _a2m():
    return {"TOK_YES": ("colombia_x", "yes"), "TOK_NO": ("colombia_x", "no")}


def test_parse_pm_book_book_event():
    msg = {
        "event_type": "book", "asset_id": "TOK_YES",
        "market": "0xabc",
        "bids": [{"price": ".40", "size": "100"}],
        "asks": [{"price": ".42", "size": "50"}],
        "timestamp": "1700000000000", "hash": "0xdead",
    }
    rec = ws.parse_pm_book(msg, _a2m())
    assert rec["venue"] == "polymarket"
    assert rec["market_id"] == "colombia_x"
    assert rec["side"] == "yes"
    assert rec["best_bid"] == pytest.approx(0.40)
    assert rec["best_ask"] == pytest.approx(0.42)
    assert rec["mid"] == pytest.approx(0.41)
    assert rec["exchange_ts"].startswith("2023-11-")
    assert rec["raw_seq"] == "0xdead"


def test_parse_pm_book_best_bid_ask_event():
    msg = {"event_type": "best_bid_ask", "asset_id": "TOK_YES",
           "best_bid": "0.33", "best_ask": "0.35", "timestamp": "1700000000000"}
    rec = ws.parse_pm_book(msg, _a2m())
    assert rec["event_type"] == "best_bid_ask"
    assert rec["mid"] == pytest.approx(0.34)


def test_parse_pm_book_unknown_asset_returns_none():
    msg = {"event_type": "book", "asset_id": "NOPE", "bids": [], "asks": []}
    assert ws.parse_pm_book(msg, _a2m()) is None


def test_parse_pm_book_ignored_event_type():
    msg = {"event_type": "tick_size_change", "asset_id": "TOK_YES"}
    assert ws.parse_pm_book(msg, _a2m()) is None


def test_parse_pm_book_missing_asset_id():
    assert ws.parse_pm_book({"event_type": "book"}, _a2m()) is None


# ---------------------------------------------------------------------------
# parse_kalshi_orderbook
# ---------------------------------------------------------------------------

def test_parse_kalshi_orderbook_both_sides():
    raw = {"orderbook_fp": {
        "yes_dollars": [["0.40", "100"], ["0.39", "50"]],
        "no_dollars": [["0.58", "200"], ["0.57", "10"]],
    }}
    rec = ws.parse_kalshi_orderbook(raw, "mkt")
    assert rec["venue"] == "kalshi"
    assert rec["side"] == "yes"
    assert rec["best_bid"] == pytest.approx(0.40)      # max yes bid
    assert rec["best_ask"] == pytest.approx(0.42)      # 1 - 0.58
    assert rec["mid"] == pytest.approx(0.41)
    assert rec["exchange_ts"] is None


def test_parse_kalshi_orderbook_empty_no_side():
    raw = {"orderbook_fp": {"yes_dollars": [["0.40", "100"]], "no_dollars": []}}
    rec = ws.parse_kalshi_orderbook(raw, "mkt")
    assert rec["best_bid"] == pytest.approx(0.40)
    assert rec["best_ask"] is None
    assert rec["mid"] is None


def test_parse_kalshi_orderbook_empty_book():
    rec = ws.parse_kalshi_orderbook({"orderbook_fp": {}}, "mkt")
    assert rec["best_bid"] is None and rec["best_ask"] is None and rec["mid"] is None


# ---------------------------------------------------------------------------
# backoff
# ---------------------------------------------------------------------------

def test_next_backoff_schedule_then_cap():
    assert ws.next_backoff(0) == 0.5
    assert ws.next_backoff(1) == 1.0
    assert ws.next_backoff(2) == 2.0
    assert ws.next_backoff(3) == 4.0
    assert ws.next_backoff(4) == 8.0
    assert ws.next_backoff(5) == 8.0      # capped
    assert ws.next_backoff(99) == 8.0     # still capped, never raises


# ---------------------------------------------------------------------------
# VenueStats downtime bookkeeping
# ---------------------------------------------------------------------------

def test_venuestats_down_up_accumulates_downtime(monkeypatch):
    s = ws.VenueStats("polymarket", "WEBSOCKET")
    clock = {"t": 1000.0}
    monkeypatch.setattr(ws.time, "monotonic", lambda: clock["t"])
    s.mark_down()
    clock["t"] = 1003.0
    s.mark_up()
    assert s.total_downtime_s == pytest.approx(3.0)
    assert s.state == "connected"


def test_venuestats_on_msg_counts_and_resets_window():
    s = ws.VenueStats("kalshi", "REST_POLL")
    for _ in range(5):
        s.on_msg()
    assert s.total_msgs == 5
    assert s.msgs_since_status == 5


def test_venuestats_mark_up_without_down_is_safe():
    s = ws.VenueStats("kalshi", "REST_POLL")
    s.mark_up()                       # never marked down
    assert s.total_downtime_s == 0.0
    assert s.state == "connected"


# ---------------------------------------------------------------------------
# Kalshi WS: local book state (snapshot + delta application)
# ---------------------------------------------------------------------------

def test_kalshi_book_apply_snapshot():
    b = ws.KalshiBook()
    b.apply_snapshot([["0.40", "100"], ["0.39", "50"]], [["0.58", "200"]])
    assert b.yes == {0.40: 100.0, 0.39: 50.0}
    assert b.no == {0.58: 200.0}


def test_kalshi_book_apply_delta_add_and_increment():
    b = ws.KalshiBook()
    b.apply_snapshot([["0.40", "100"]], [])
    b.apply_delta("yes", "0.40", "25")        # increment existing level
    assert b.yes[0.40] == pytest.approx(125.0)
    b.apply_delta("yes", "0.41", "10")        # new level
    assert b.yes[0.41] == pytest.approx(10.0)


def test_kalshi_book_apply_delta_removes_emptied_level():
    b = ws.KalshiBook()
    b.apply_snapshot([["0.40", "100"]], [])
    b.apply_delta("yes", "0.40", "-100")      # drains the level
    assert 0.40 not in b.yes
    # negative overshoot also removes, never goes negative
    b.apply_snapshot([["0.30", "5"]], [])
    b.apply_delta("yes", "0.30", "-9")
    assert 0.30 not in b.yes


def test_kalshi_book_snapshot_replaces_state():
    b = ws.KalshiBook()
    b.apply_snapshot([["0.40", "100"]], [["0.58", "200"]])
    b.apply_snapshot([["0.45", "10"]], [])    # fresh snapshot wipes prior
    assert b.yes == {0.45: 10.0}
    assert b.no == {}


def test_kalshi_book_to_orderbook_fp_roundtrips_to_normalize():
    b = ws.KalshiBook()
    b.apply_snapshot([["0.40", "100"]], [["0.58", "200"]])
    fp = b.to_orderbook_fp()
    assert set(fp["orderbook_fp"]) == {"yes_dollars", "no_dollars"}
    # prices rendered as 4dp strings, sizes preserved
    assert fp["orderbook_fp"]["yes_dollars"] == [["0.4000", 100.0]]


# ---------------------------------------------------------------------------
# Kalshi WS: top-of-book reconstruction via normalize.py complementarity
# ---------------------------------------------------------------------------

def test_reconstruct_kalshi_record_complementarity():
    # YES bids at 0.40/0.39; NO bid at 0.58 => YES ask = 1 - 0.58 = 0.42
    b = ws.KalshiBook()
    b.apply_snapshot([["0.40", "100"], ["0.39", "50"]], [["0.58", "200"]])
    rec = ws.reconstruct_kalshi_record(b, "mkt", "2026-05-31T00:00:00+00:00", 7)
    assert rec["venue"] == "kalshi"
    assert rec["event_type"] == "ws_orderbook"
    assert rec["best_bid"] == pytest.approx(0.40)
    assert rec["best_ask"] == pytest.approx(0.42)
    assert rec["mid"] == pytest.approx(0.41)
    assert rec["raw_seq"] == 7
    assert rec["exchange_ts"] == "2026-05-31T00:00:00+00:00"


def test_reconstruct_kalshi_record_one_sided_book():
    b = ws.KalshiBook()
    b.apply_snapshot([["0.40", "100"]], [])   # no NO bids => no YES ask
    rec = ws.reconstruct_kalshi_record(b, "mkt", None, 1)
    assert rec["best_bid"] == pytest.approx(0.40)
    assert rec["best_ask"] is None
    assert rec["mid"] is None


def test_reconstruct_after_delta_moves_top_of_book():
    b = ws.KalshiBook()
    b.apply_snapshot([["0.40", "100"]], [["0.58", "200"]])
    # a better YES bid arrives at 0.41
    b.apply_delta("yes", "0.41", "30")
    rec = ws.reconstruct_kalshi_record(b, "mkt", None, 2)
    assert rec["best_bid"] == pytest.approx(0.41)
    # NO bid improves to 0.59 => YES ask tightens to 0.41
    b.apply_delta("no", "0.59", "5")
    rec2 = ws.reconstruct_kalshi_record(b, "mkt", None, 3)
    assert rec2["best_ask"] == pytest.approx(0.41)


# ---------------------------------------------------------------------------
# Kalshi WS: RSA-PSS signing + auth headers (uses a throwaway test key)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rsa_key():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def test_kalshi_sign_pss_verifies(rsa_key):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    ts, method, path = "1700000000000", "GET", "/trade-api/ws/v2"
    sig_b64 = ws.kalshi_sign_pss(rsa_key, ts, method, path)
    sig = base64.b64decode(sig_b64)
    # Should verify against the public key for the exact signed string.
    rsa_key.public_key().verify(
        sig, (ts + method + path).encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_kalshi_sign_pss_is_nondeterministic_but_valid(rsa_key):
    # PSS uses random salt, so two signatures differ but both verify.
    s1 = ws.kalshi_sign_pss(rsa_key, "1", "GET", "/p")
    s2 = ws.kalshi_sign_pss(rsa_key, "1", "GET", "/p")
    assert s1 != s2


def test_kalshi_auth_headers_shape_and_fresh_ts(rsa_key):
    h1 = ws.kalshi_auth_headers("keyid-123", rsa_key)
    assert h1["KALSHI-ACCESS-KEY"] == "keyid-123"
    assert h1["KALSHI-ACCESS-SIGNATURE"]
    assert h1["KALSHI-ACCESS-TIMESTAMP"].isdigit()
    import time as _t
    _t.sleep(0.002)
    h2 = ws.kalshi_auth_headers("keyid-123", rsa_key)
    # timestamp must regenerate (monotonic, non-decreasing)
    assert int(h2["KALSHI-ACCESS-TIMESTAMP"]) >= int(h1["KALSHI-ACCESS-TIMESTAMP"])


def test_kalshi_auth_headers_never_contains_private_key(rsa_key):
    h = ws.kalshi_auth_headers("keyid-123", rsa_key)
    blob = json.dumps(h)
    assert "PRIVATE KEY" not in blob
    assert "BEGIN" not in blob


# ---------------------------------------------------------------------------
# Auth-rejection detection (drives REST degradation)
# ---------------------------------------------------------------------------

def test_is_auth_rejection_on_401_text():
    assert ws._is_auth_rejection(Exception("server rejected WebSocket connection: HTTP 401"))
    assert ws._is_auth_rejection(Exception("403 Forbidden"))
    assert ws._is_auth_rejection(Exception("unauthorized"))


def test_is_auth_rejection_false_on_network_error():
    assert not ws._is_auth_rejection(Exception("Connection reset by peer"))
    assert not ws._is_auth_rejection(TimeoutError("timed out"))


# ---------------------------------------------------------------------------
# Credential loading degrades cleanly when absent
# ---------------------------------------------------------------------------

def test_load_kalshi_credentials_absent(monkeypatch, tmp_path):
    # Point ROOT at an empty dir (no .env) and clear env vars.
    monkeypatch.setattr(ws, "ROOT", tmp_path)
    monkeypatch.delenv("KALSHI_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
    assert ws.load_kalshi_credentials() is None


def test_load_kalshi_credentials_missing_keyfile(monkeypatch, tmp_path):
    monkeypatch.setattr(ws, "ROOT", tmp_path)
    monkeypatch.setenv("KALSHI_ACCESS_KEY_ID", "kid")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(tmp_path / "nope.pem"))
    assert ws.load_kalshi_credentials() is None


def test_load_kalshi_credentials_valid(monkeypatch, tmp_path, rsa_key):
    from cryptography.hazmat.primitives import serialization
    pem = rsa_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    kf = tmp_path / "key.pem"
    kf.write_bytes(pem)
    monkeypatch.setattr(ws, "ROOT", tmp_path)
    monkeypatch.setenv("KALSHI_ACCESS_KEY_ID", "kid")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(kf))
    creds = ws.load_kalshi_credentials()
    assert creds is not None
    assert creds[0] == "kid"
