"""Freeze the replay set for the batch-auction counterfactual study.

Decision #1 (DATA_AUDIT.md): pin the analysis dataset at a fixed cutoff so the
still-running E.1 daemon can keep appending without moving the study's inputs.

Freeze rule
-----------
Include every record/file whose capture timestamp is STRICTLY BEFORE the cutoff
    cutoff = 2026-06-06T04:00:00Z  ==  2026-06-05 23:59:59.999 ET (EDT, UTC-4)
For append-only CSVs the cutoff is applied row-wise (utc_ts / fetched_at); the
recorded SHA256 is over the *through-cutoff slice's original bytes*, so it is
stable and verifiable even after the live file grows. For the raw gz trees the
cutoff is applied to each file's embedded timestamp; an index hash over
(relpath, size) pins the tree without reading 250k gz payloads (per-episode
ladder extraction will content-hash the specific files it pulls — decision #5).

This tool is READ-ONLY over the data. It writes only its own manifest JSON.
No data is copied, moved, or deleted; no auction/fee/arm logic here.

Output: batch_counterfactual/FROZEN_MANIFEST.json

Run:
    uv run python batch_counterfactual/freeze_manifest.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = Path(__file__).resolve().parent / "FROZEN_MANIFEST.json"

CUTOFF = datetime(2026, 6, 6, 4, 0, 0, tzinfo=timezone.utc)
CUTOFF_LABEL = "2026-06-05 23:59:59.999 ET (EDT, UTC-4) == 2026-06-06T04:00:00Z (exclusive)"


def _parse(ts: str):
    try:
        d = datetime.fromisoformat(ts.strip())
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def freeze_csv(path: Path, ts_field: str | None) -> dict:
    """Logical-row count + SHA256 of a canonical re-serialization of the
    header + through-cutoff rows.

    Uses the csv module so quoted multi-line fields (e.g. Kalshi 503 error
    strings carry embedded newlines) are parsed as single logical rows. The
    hash is over csv.writer's canonical re-emission of the included rows, so it
    is reproducible regardless of later live appends or original quoting.
    """
    import csv
    import io
    if not path.exists():
        return {"path": str(path.relative_to(ROOT)), "exists": False}
    total = incl = after = bad = 0
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    with path.open("r", newline="") as f:
        r = csv.reader(f)
        header = next(r)
        w.writerow(header)
        ts_idx = header.index(ts_field) if (ts_field and ts_field in header) else None
        for row in r:
            total += 1
            if ts_idx is None:
                w.writerow(row); incl += 1
                continue
            d = _parse(row[ts_idx]) if ts_idx < len(row) else None
            if d is None:
                bad += 1
                continue
            if d < CUTOFF:
                w.writerow(row); incl += 1
            else:
                after += 1
    h = hashlib.sha256(buf.getvalue().encode())
    return {
        "path": str(path.relative_to(ROOT)),
        "exists": True,
        "ts_field": ts_field if ts_idx is not None else None,
        "rows_total_now": total,
        "rows_through_cutoff": incl,
        "rows_after_cutoff": after,
        "rows_unparseable_ts": bad,
        "sha256_through_cutoff_canonical": h.hexdigest(),
    }


def freeze_jsonl(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path.relative_to(ROOT)), "exists": False}
    h = hashlib.sha256()
    total = incl = 0
    maxts = None
    with path.open("rb") as f:
        for line in f:
            if not line.strip():
                continue
            total += 1
            try:
                rec = json.loads(line)
                ts = rec.get("local_recv_utc")
                d = _parse(ts) if ts else None
            except Exception:
                d = None
            if d is not None:
                maxts = d if maxts is None or d > maxts else maxts
            if d is None or d < CUTOFF:
                h.update(line); incl += 1
    return {
        "path": str(path.relative_to(ROOT)),
        "exists": True,
        "records_total": total,
        "records_through_cutoff": incl,
        "max_local_recv_utc": maxts.isoformat() if maxts else None,
        "sha256_through_cutoff": h.hexdigest(),
    }


def _fname_ts(name: str):
    # e.g. 2026-06-06T000017.463350+0000_intl_mayor_kr_oseh.json.gz
    stamp = name.split("+0000_")[0]
    for fmt in ("%Y-%m-%dT%H%M%S.%f", "%Y-%m-%dT%H%M%S"):
        try:
            return datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def freeze_raw_tree(base: Path) -> dict:
    """Per-day file count + bytes through cutoff; index hash over (relpath,size)."""
    if not base.exists():
        return {"path": str(base.relative_to(ROOT)), "exists": False}
    idx = hashlib.sha256()
    per_day: dict[str, dict] = {}
    n_incl = n_excl = bytes_incl = 0
    for p in sorted(base.rglob("*.json.gz")):
        d = _fname_ts(p.name)
        if d is not None and d >= CUTOFF:
            n_excl += 1
            continue
        sz = p.stat().st_size
        rel = str(p.relative_to(ROOT))
        idx.update(f"{rel}\t{sz}\n".encode())
        n_incl += 1
        bytes_incl += sz
        day = p.parent.name
        dd = per_day.setdefault(day, {"files": 0, "bytes": 0})
        dd["files"] += 1
        dd["bytes"] += sz
    return {
        "path": str(base.relative_to(ROOT)),
        "exists": True,
        "files_through_cutoff": n_incl,
        "files_after_cutoff_excluded": n_excl,
        "bytes_through_cutoff": bytes_incl,
        "per_day": per_day,
        "index_sha256": idx.hexdigest(),
    }


def freeze_static_dir(base: Path, pattern: str) -> dict:
    if not base.exists():
        return {"path": str(base.relative_to(ROOT)), "exists": False}
    idx = hashlib.sha256()
    n = bytes_ = 0
    for p in sorted(base.rglob(pattern)):
        sz = p.stat().st_size
        idx.update(f"{str(p.relative_to(ROOT))}\t{sz}\n".encode())
        n += 1
        bytes_ += sz
    return {"path": str(base.relative_to(ROOT)), "exists": True,
            "files": n, "bytes": bytes_, "index_sha256": idx.hexdigest()}


def market_inclusion() -> dict:
    """Decision #4 exclusion rule: include a market only if it shows two-sided
    YES books on BOTH venues in >=80% of the daemon's frozen cycles.

    Denominator = every cycle the daemon ran in the frozen window (the daemon
    writes a row for all 16 markets every cycle, so an all-null/error cycle
    still counts against the market). This penalizes structural gaps (a market
    that quotes well *when present* but is absent/empty much of the time, e.g.
    okc) rather than crediting only its good cycles.
    """
    import pandas as pd
    df = pd.read_csv(ROOT / "data/processed/timeofday_poll.csv")
    df["ts"] = pd.to_datetime(df["utc_ts"], utc=True, errors="coerce")
    df = df[df["ts"] < CUTOFF]
    all_cycles = df["ts"].nunique()  # global frozen-cycle count (denominator base)
    out = {}
    for mid, g in df.groupby("market_id"):
        ky = g[g.venue == "kalshi_yes"].set_index("ts")
        py = g[g.venue == "polymarket_yes"].set_index("ts")
        has_k = (ky["best_bid"].notna() & ky["best_ask"].notna())
        has_p = (py["best_bid"].notna() & py["best_ask"].notna())
        cycles = g["ts"].nunique()
        denom = cycles if cycles else 1
        ky_rate = float(has_k.sum()) / denom
        py_rate = float(has_p.sum()) / denom
        joined = pd.concat([has_k.rename("k"), has_p.rename("p")], axis=1).fillna(False)
        both_rate = float((joined["k"] & joined["p"]).sum()) / denom
        out[mid] = {
            "daemon_cycles_present": int(cycles),
            "frozen_cycles_total": int(all_cycles),
            "kalshi_yes_two_sided_pct": round(ky_rate * 100, 1),
            "pm_yes_two_sided_pct": round(py_rate * 100, 1),
            "both_venues_two_sided_pct": round(both_rate * 100, 1),
            "included": bool(both_rate >= 0.80),
        }
    return out


def main() -> int:
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "cutoff_utc": CUTOFF.isoformat(),
        "cutoff_label": CUTOFF_LABEL,
        "freeze_rule": "include records/files with capture timestamp < cutoff_utc",
        "primary_processed": {
            "timeofday_poll": freeze_csv(ROOT / "data/processed/timeofday_poll.csv", "utc_ts"),
            "event_colombia_r1_poll": freeze_csv(ROOT / "data/processed/event_colombia_r1_poll.csv", "utc_ts"),
            "event_test_smoke_poll": freeze_csv(ROOT / "data/processed/event_test_smoke_poll.csv", "utc_ts"),
            "microstructure_snapshot": freeze_csv(ROOT / "data/processed/microstructure_snapshot.csv", "fetched_at"),
        },
        "ws_subsecond": {
            "colombia_r1_2026_05_31": freeze_jsonl(ROOT / "data/raw/ws_leadlag/colombia_r1/2026-05-31.jsonl"),
        },
        "raw_trees": {
            "timeofday": freeze_raw_tree(ROOT / "data/raw/timeofday"),
            "event": freeze_raw_tree(ROOT / "data/raw/event"),
        },
        "snapshot_dirs": {
            "snapshot_20260525T220956Z": freeze_static_dir(ROOT / "data/raw/snapshot_20260525T220956Z", "*.json"),
            "snapshot_20260528T022943Z": freeze_static_dir(ROOT / "data/raw/snapshot_20260528T022943Z", "*.json"),
        },
        "market_inclusion": market_inclusion(),
        "note_derived_excluded": (
            "Derived analysis outputs (exp3c_persistence, exp12a_*, arb_results*, "
            "discovery_*, *.md, figures) are NOT part of the frozen capture set; "
            "they are regenerable from the frozen primaries above."
        ),
    }
    OUT_JSON.write_text(json.dumps(manifest, indent=2))

    print("=" * 70)
    print("FROZEN MANIFEST")
    print("=" * 70)
    print("cutoff:", CUTOFF_LABEL)
    td = manifest["primary_processed"]["timeofday_poll"]
    print(f"timeofday_poll.csv: {td['rows_through_cutoff']} rows through cutoff "
          f"({td['rows_after_cutoff']} after, {td['rows_unparseable_ts']} unparseable-ts), "
          f"sha256 {td['sha256_through_cutoff_canonical'][:16]}...")
    rt = manifest["raw_trees"]["timeofday"]
    print(f"raw timeofday gz: {rt['files_through_cutoff']} files / "
          f"{rt['bytes_through_cutoff']/1e9:.2f} GB through cutoff "
          f"({rt['files_after_cutoff_excluded']} excluded after)")
    ws = manifest["ws_subsecond"]["colombia_r1_2026_05_31"]
    print(f"ws jsonl: {ws['records_through_cutoff']} records, max_recv {ws['max_local_recv_utc']}")
    inc = manifest["market_inclusion"]
    keep = [m for m, v in inc.items() if v["included"]]
    drop = [m for m, v in inc.items() if not v["included"]]
    print(f"markets INCLUDED ({len(keep)}): {sorted(keep)}")
    print(f"markets EXCLUDED ({len(drop)}): {sorted(drop)}")
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
