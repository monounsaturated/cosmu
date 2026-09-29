# intent: the INTRADAY BAR STORE (realtime-data-lane epic P3) — durable, deduped persistence for the closed
# 1m candles the realtime worker records live, plus the retention math that keeps the table bounded: 1m rows
# older than the retention window are ROLLED UP into 5m candles (first open / max high / min low / last close /
# summed volume) and only then deleted. inputs: closed Bars from the WS consumer + the knowledge Store;
# outputs: bars_intraday rows + Bar reads. invariants: CLOSED bars only (the caller guarantees it; this store
# never judges candle state), idempotent writes (UNIQUE(venue,symbol,timeframe,ts) + a pre-filter so
# reconnect/replay double-feeds write 0), retention NEVER deletes a 1m row whose 5m rollup has not been
# written (no data loss window), `ingested_at` = receipt time (the PIT seam), offline-testable (sqlite Store).

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from cosmu.data.market import Bar
from cosmu.knowledge.store import Store, utcnow

VENUE = "binance"
RETENTION_DAYS = 90  # epic §6: keep 1m for 90 days, 5m rollups beyond


class IntradayBarsStore:
    """bars_intraday access for one venue. Plain SQL over the knowledge Store (sqlite + Postgres)."""

    def __init__(self, store: Store, *, venue: str = VENUE) -> None:
        self.store = store
        self.venue = venue

    def insert_closed_bars(self, symbol: str, timeframe: str, bars: list[Bar]) -> int:
        """Insert NEW closed bars (deduped on ts against the table AND within the batch). Returns rows written
        — a reconnect replay of already-stored candles writes 0."""
        if not bars:
            return 0
        keys = sorted({b.ts.isoformat() for b in bars})
        placeholders = ",".join("?" for _ in keys)
        existing = {
            r["ts"]
            for r in self.store.rows(
                f"SELECT ts FROM bars_intraday WHERE venue = ? AND symbol = ? AND timeframe = ? AND ts IN ({placeholders})",
                (self.venue, symbol, timeframe, *keys),
            )
        }
        now = utcnow()
        rows: list[tuple[Any, ...]] = []
        seen = set(existing)
        for b in sorted(bars, key=lambda b: b.ts):
            ts = b.ts.isoformat()
            if ts in seen:
                continue
            seen.add(ts)
            rows.append((self.venue, symbol, timeframe, ts,
                         str(b.open), str(b.high), str(b.low), str(b.close), str(b.volume), now))
        if rows:
            with self.store.batch() as writer:
                writer.insert_many(
                    "bars_intraday",
                    ["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume", "ingested_at"],
                    rows,
                )
        return len(rows)

    def read_bars(self, symbol: str, timeframe: str, *, since: datetime | None = None, limit: int = 0) -> list[Bar]:
        sql = "SELECT ts, open, high, low, close, volume FROM bars_intraday WHERE venue = ? AND symbol = ? AND timeframe = ?"
        args: list[Any] = [self.venue, symbol, timeframe]
        if since is not None:
            sql += " AND ts >= ?"
            args.append(since.isoformat())
        sql += " ORDER BY ts"
        rows = self.store.rows(sql, tuple(args))
        bars = [
            Bar(ts=_ts(r["ts"]), open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
                low=Decimal(str(r["low"])), close=Decimal(str(r["close"])), volume=Decimal(str(r["volume"])))
            for r in rows
        ]
        return bars[-limit:] if limit > 0 else bars

    def latest_ts(self, symbol: str, timeframe: str) -> datetime | None:
        """The newest stored bar's open time — the WS consumer's resume point and the staleness gauge."""
        row = self.store.row(
            "SELECT MAX(ts) AS ts FROM bars_intraday WHERE venue = ? AND symbol = ? AND timeframe = ?",
            (self.venue, symbol, timeframe),
        )
        return _ts(row["ts"]) if row and row.get("ts") else None

    # ------------------------------------------------------------------ retention: rollup 1m → 5m, then delete

    def run_retention(self, *, now: datetime | None = None, retention_days: int = RETENTION_DAYS) -> dict[str, int]:
        """Bound the 1m table: for every symbol, roll 1m rows older than the window up into 5m candles, then
        delete ONLY the 1m rows that are covered by a written 5m rollup. Idempotent (rollups dedupe like any
        bar write); a partial failure leaves 1m data intact — never a loss window."""
        now = now or datetime.now(tz=UTC)
        cutoff = (now - timedelta(days=retention_days)).isoformat()
        symbols = [
            r["symbol"]
            for r in self.store.rows(
                "SELECT DISTINCT symbol FROM bars_intraday WHERE venue = ? AND timeframe = '1m' AND ts < ?",
                (self.venue, cutoff),
            )
        ]
        rolled = deleted = 0
        for symbol in symbols:
            old = self.read_bars(symbol, "1m")
            old = [b for b in old if b.ts.isoformat() < cutoff]
            if not old:
                continue
            fives = rollup(old, minutes=5)
            rolled += self.insert_closed_bars(symbol, "5m", fives)
            # Delete only 1m rows whose 5-minute bucket now exists as a stored rollup.
            buckets = {b.ts.isoformat() for b in self.read_bars(symbol, "5m")}
            deletable = [b.ts.isoformat() for b in old if _bucket_start(b.ts, 5).isoformat() in buckets]
            if deletable:
                placeholders = ",".join("?" for _ in deletable)
                self.store.rows(
                    f"DELETE FROM bars_intraday WHERE venue = ? AND symbol = ? AND timeframe = '1m' AND ts IN ({placeholders})",
                    (self.venue, symbol, *deletable),
                )
                deleted += len(deletable)
        return {"rolled_up_5m": rolled, "deleted_1m": deleted}


def _bucket_start(ts: datetime, minutes: int) -> datetime:
    return ts.replace(minute=(ts.minute // minutes) * minutes, second=0, microsecond=0)


def rollup(bars: list[Bar], *, minutes: int) -> list[Bar]:
    """Aggregate finer bars into `minutes`-buckets: first open, max high, min low, last close, summed volume.
    Pure + deterministic; buckets with no bars simply don't exist (gaps stay gaps, never zero-filled)."""
    buckets: dict[datetime, list[Bar]] = {}
    for b in sorted(bars, key=lambda b: b.ts):
        buckets.setdefault(_bucket_start(b.ts, minutes), []).append(b)
    out: list[Bar] = []
    for start in sorted(buckets):
        group = buckets[start]
        out.append(Bar(
            ts=start, open=group[0].open, high=max(b.high for b in group),
            low=min(b.low for b in group), close=group[-1].close,
            volume=sum((b.volume for b in group), Decimal("0")),
        ))
    return out


def _ts(raw: str) -> datetime:
    ts = datetime.fromisoformat(str(raw))
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
