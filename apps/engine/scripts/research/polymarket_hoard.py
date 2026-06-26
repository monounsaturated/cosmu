# intent: HOARD free, FORWARD-ONLY Polymarket data to Cloudflare R2 — the data we can NEVER backfill later.
# The operator rule: hoard non-backfillable data NOW (price/odds/book/trades), test paid sources JIT.
#
# Three keyless, free Polymarket endpoints (all confirmed reachable by the #400/#405 maker-feasibility study):
#   - Gamma   gamma-api.polymarket.com/markets  — market metadata + clobTokenIds + bestBid/bestAsk (live snapshot)
#   - CLOB    clob.polymarket.com/prices-history — windowed hourly/daily YES-odds history per market (backfillable
#             only as far as the venue keeps it; we snapshot the full `interval=max` series each run and UNION-MERGE)
#   - CLOB    clob.polymarket.com/book?token_id= — the full L2 depth ladder RIGHT NOW (NOT backfillable — a book
#             snapshot exists only at the instant it is taken; nobody serves historical books)
#   - data    data-api.polymarket.com/trades?market= — real BUY/SELL trade prints (newest-first; the public log
#             only goes back a bounded window, so the historical flow is lost if not captured forward)
#
# Storage (distinct R2 prefixes, all under the same never-shrink discipline as cosmu.data.bar_archive):
#   pm_odds/<conditionId>_<fidelity>.json   — UNION-MERGED {t,p} odds series (grows; the deep odds archive)
#   pm_book/<date>/<conditionId>.json       — per-day APPEND of point-in-time L2 book snapshots (each run adds one)
#   pm_trades/<conditionId>.json            — UNION-MERGED real trade prints deduped on (ts, side, price, size)
#   pm_markets/<date>.json                  — the day's discovered open-market metadata snapshot (one object/day)
#
# invariants: R2 creds ABSENT → loud no-op (never crashes). Idempotent: re-running merges, never shrinks. A fetch
# error for one market is logged + skipped, NEVER aborts the loop. BOUNDED by --max-markets so one run stays cheap
# and resumable. ZERO production impact: read-only fetches, NO DB writes, NO Gate constant, NO runtime-path code.
#
# Run:  python3 scripts/research/polymarket_hoard.py --max-markets 300 --book-sample 150 --trades-sample 150
from __future__ import annotations

import argparse
import json
import logging
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("polymarket_hoard")

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = _ssl_context()


def _fetch(url: str, *, retries: int = 3) -> Any:
    """GET + JSON-decode with bounded retries. 400/401/404 raise immediately (no point retrying); transient
    errors back off. Mirrors the maker-feasibility harness fetcher contract exactly."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
            with urllib.request.urlopen(req, timeout=30, context=_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 404):
                raise
            last = e
        except Exception as e:  # noqa: BLE001 — transient; back off and retry
            last = e
        time.sleep(0.4 * (attempt + 1))
    if last:
        raise last
    return None


# ----------------------------------------------------------------------------------------------------------
# R2 — reuse the EXACT client construction + creds-present gate as cosmu.data.bar_archive / pg_backup.
# ----------------------------------------------------------------------------------------------------------
def _r2(settings: Any):  # noqa: ANN202
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def _r2_ready(settings: Any) -> bool:
    return all(
        (settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key, settings.r2_bucket)
    )


def _read_json(s3: Any, bucket: str, key: str) -> Any:
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — NoSuchKey on a first write / transient read → treat as absent
        return None


def _write_json(s3: Any, bucket: str, key: str, obj: Any) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(obj, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )


# ----------------------------------------------------------------------------------------------------------
# DISCOVERY — the most-liquid OPEN binary markets (the universe worth hoarding). Gamma /markets paginated.
# ----------------------------------------------------------------------------------------------------------
def discover_open_markets(max_markets: int) -> list[dict]:
    """Open, order-book-enabled binary markets, liquidity-ranked. Each carries conditionId, the YES clobTokenId,
    and the live bestBid/bestAsk snapshot. Paginates Gamma /markets until `max_markets` are collected."""
    out: list[dict] = []
    seen: set[str] = set()
    offset = 0
    page = 100
    while len(out) < max_markets:
        url = f"{GAMMA}/markets?closed=false&active=true&limit={page}&offset={offset}&order=liquidity&ascending=false"
        try:
            rows = _fetch(url)
        except Exception:  # noqa: BLE001
            break
        if not isinstance(rows, list) or not rows:
            break
        for m in rows:
            if not isinstance(m, dict) or not m.get("enableOrderBook"):
                continue
            cid = str(m.get("conditionId") or "")
            tids = m.get("clobTokenIds") or "[]"
            if isinstance(tids, str):
                try:
                    tids = json.loads(tids)
                except (json.JSONDecodeError, TypeError):
                    tids = []
            if not cid or cid in seen or not tids:
                continue
            seen.add(cid)
            out.append({
                "conditionId": cid,
                "yes_token": str(tids[0]),
                "question": m.get("question", ""),
                "liquidity": float(m.get("liquidity") or m.get("liquidityClob") or 0),
                "bestBid": m.get("bestBid"),
                "bestAsk": m.get("bestAsk"),
                "endDate": m.get("endDate"),
            })
            if len(out) >= max_markets:
                break
        offset += page
        time.sleep(0.1)
    out.sort(key=lambda h: h["liquidity"], reverse=True)
    return out[:max_markets]


# ----------------------------------------------------------------------------------------------------------
# 1) ODDS — full `interval=max` YES-odds series per market, UNION-MERGED into the deep R2 archive (never shrinks).
# ----------------------------------------------------------------------------------------------------------
def hoard_odds(s3: Any, bucket: str, markets: list[dict], *, fidelity: int) -> dict:
    archived = skipped = total_rows = 0
    for m in markets:
        token = m["yes_token"]
        q = urllib.parse.urlencode({"market": token, "fidelity": int(fidelity), "interval": "max"})
        try:
            payload = _fetch(f"{CLOB}/prices-history?{q}")
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        rows = payload.get("history", []) if isinstance(payload, dict) else []
        fresh = {int(r["t"]): float(r["p"]) for r in rows if "t" in r and "p" in r}
        if not fresh:
            skipped += 1
            continue
        key = f"pm_odds/{m['conditionId']}_{fidelity}.json"
        existing = _read_json(s3, bucket, key) or {}
        merged = {**{int(k): float(v) for k, v in existing.items()}, **fresh}  # never shrinks; fresh repairs ties
        if len(merged) != len(existing) or any(existing.get(str(k)) != v for k, v in fresh.items()):
            _write_json(s3, bucket, key, {str(k): merged[k] for k in sorted(merged)})
        archived += 1
        total_rows += len(merged)
    return {"series": archived, "skipped": skipped, "rows": total_rows}


# ----------------------------------------------------------------------------------------------------------
# 2) BOOK — the live L2 depth ladder snapshot (NOT backfillable). One object per (date, conditionId) appended.
# ----------------------------------------------------------------------------------------------------------
def hoard_books(s3: Any, bucket: str, markets: list[dict], *, sample: int) -> dict:
    captured = skipped = 0
    day = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    stamp = datetime.now(tz=UTC).isoformat()
    for m in markets[:sample]:
        try:
            b = _fetch(f"{CLOB}/book?token_id={m['yes_token']}")
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        bids = b.get("bids") if isinstance(b, dict) else None
        asks = b.get("asks") if isinstance(b, dict) else None
        if not bids and not asks:
            skipped += 1
            continue
        key = f"pm_book/{day}/{m['conditionId']}.json"
        snaps = _read_json(s3, bucket, key) or []
        snaps.append({"ts": stamp, "bids": bids, "asks": asks, "liquidity": m["liquidity"]})
        _write_json(s3, bucket, key, snaps)
        captured += 1
    return {"snapshots": captured, "skipped": skipped, "day": day}


# ----------------------------------------------------------------------------------------------------------
# 3) TRADES — real BUY/SELL prints, UNION-MERGED deduped on (ts, side, price, size). The flow log is bounded
#    by the public window, so capturing forward is the only way to keep the deep print history.
# ----------------------------------------------------------------------------------------------------------
def _trade_key(t: dict) -> tuple:
    return (int(t.get("timestamp", 0)), t.get("side"), t.get("price"), t.get("size"))


def hoard_trades(s3: Any, bucket: str, markets: list[dict], *, sample: int, limit: int) -> dict:
    captured = skipped = total_prints = 0
    for m in markets[:sample]:
        try:
            tr = _fetch(f"{DATA}/trades?market={m['conditionId']}&limit={limit}")
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        if not isinstance(tr, list) or not tr:
            skipped += 1
            continue
        key = f"pm_trades/{m['conditionId']}.json"
        existing = _read_json(s3, bucket, key) or []
        seen = {_trade_key(t) for t in existing}
        added = [t for t in tr if _trade_key(t) not in seen]
        if added:
            merged = existing + added
            merged.sort(key=lambda t: int(t.get("timestamp", 0)))
            _write_json(s3, bucket, key, merged)
            captured += 1
            total_prints += len(merged)
        else:
            total_prints += len(existing)
    return {"markets": captured, "skipped": skipped, "prints": total_prints}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Hoard free forward-only Polymarket data to R2.")
    ap.add_argument("--max-markets", type=int, default=300)
    ap.add_argument("--book-sample", type=int, default=150)
    ap.add_argument("--trades-sample", type=int, default=150)
    ap.add_argument("--fidelity", type=int, default=60, help="odds bucket minutes (60=hourly, 1440=daily)")
    ap.add_argument("--trades-limit", type=int, default=500)
    args = ap.parse_args(argv)

    from cosmu.config.settings import get_settings

    settings = get_settings()
    if not _r2_ready(settings):
        print("polymarket_hoard: R2 creds absent — no-op.")
        return 0
    s3 = _r2(settings)
    bucket = settings.r2_bucket

    t0 = time.time()
    markets = discover_open_markets(args.max_markets)
    print(f"discovered {len(markets)} open order-book markets ({time.time() - t0:.0f}s)", flush=True)

    # snapshot the day's discovered metadata (one object/day) — cheap, makes the hoard self-describing
    day = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    _write_json(s3, bucket, f"pm_markets/{day}.json", markets)

    odds = hoard_odds(s3, bucket, markets, fidelity=args.fidelity)
    print(f"odds: {odds} ({time.time() - t0:.0f}s)", flush=True)
    books = hoard_books(s3, bucket, markets, sample=args.book_sample)
    print(f"books: {books} ({time.time() - t0:.0f}s)", flush=True)
    trades = hoard_trades(s3, bucket, markets, sample=args.trades_sample, limit=args.trades_limit)
    print(f"trades: {trades} ({time.time() - t0:.0f}s)", flush=True)

    print("POLYMARKET_HOARD_SUMMARY " + json.dumps({
        "markets": len(markets), "odds": odds, "books": books, "trades": trades,
        "elapsed_s": round(time.time() - t0, 1),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
