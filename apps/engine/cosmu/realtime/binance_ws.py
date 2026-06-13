# intent: the Binance WebSocket KLINE consumer (realtime-data-lane epic P3) — subscribe to the combined
# 1m-kline stream for the configured universe and hand ONLY CLOSED candles (the `k.x == true` frames) to a
# sink, with reconnect + exponential backoff + jitter so a dropped socket degrades to a gap the cron lane
# covers, never a crash. inputs: symbols + an async `connect` seam yielding raw JSON frames; outputs: closed
# Bars pushed to the sink + a mutable ConsumerHealth the heartbeat reads. invariants: closed candles ONLY
# (the in-progress frame is dropped — the same contract data/market.py enforces for REST), the connect seam
# is injectable so tests run with ZERO network and the `websockets` dependency stays import-guarded,
# per-frame errors are counted + skipped (one bad frame never kills the stream), and the loop exits promptly
# when `stop` is set (clean lifespan shutdown).

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from cosmu.data.market import Bar

WS_URL = "wss://stream.binance.com:9443/stream?streams="

# Reconnect backoff: 1s → 2s → 4s … capped; full jitter so a fleet of consumers never thunders in sync.
_BACKOFF_BASE_S = 1.0
_BACKOFF_CAP_S = 60.0


@dataclass
class ConsumerHealth:
    """Mutable health the heartbeat task snapshots. `last_ok` = the last CLOSED bar receipt."""

    name: str
    last_ok: datetime | None = None
    frames: int = 0
    closed_bars: int = 0
    reconnects: int = 0
    frame_errors: int = 0
    last_error: str = ""

    def snapshot(self, now: datetime) -> dict:
        return {
            "last_ok": self.last_ok.isoformat() if self.last_ok else None,
            "lag_s": (now - self.last_ok).total_seconds() if self.last_ok else None,
            "frames": self.frames,
            "closed_bars": self.closed_bars,
            "reconnects": self.reconnects,
            "frame_errors": self.frame_errors,
            "last_error": self.last_error[:160],
        }


def stream_url(symbols: list[str], timeframe: str = "1m") -> str:
    streams = "/".join(f"{s.lower()}@kline_{timeframe}" for s in symbols)
    return WS_URL + streams


def parse_closed_kline(raw: str) -> tuple[str, Bar] | None:
    """One combined-stream frame → (symbol, closed Bar), or None for an in-progress candle / non-kline frame.
    The kline payload's `t` is the bar OPEN time in ms and `x` is the is-closed flag — only `x == true`
    frames become bars (the closed-candle invariant, enforced at the source)."""
    payload = json.loads(raw)
    k = (payload.get("data") or payload).get("k") or {}
    if not k or not k.get("x"):
        return None
    return (
        str(k["s"]),
        Bar(
            ts=datetime.fromtimestamp(int(k["t"]) / 1000, tz=UTC),
            open=Decimal(str(k["o"])), high=Decimal(str(k["h"])),
            low=Decimal(str(k["l"])), close=Decimal(str(k["c"])),
            volume=Decimal(str(k["v"])),
        ),
    )


async def _default_connect(url: str) -> AsyncIterator[str]:
    """The real transport — import-guarded so environments without `websockets` degrade to the cron lane
    (an ImportError is reported once via health.last_error, never a crash loop)."""
    import websockets  # noqa: PLC0415 — guarded: optional at import time, required only when the worker is ON

    async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**20) as ws:
        async for message in ws:
            yield message if isinstance(message, str) else message.decode("utf-8")


async def run_kline_consumer(
    symbols: list[str],
    sink: Callable[[str, Bar], None],
    *,
    stop: asyncio.Event,
    health: ConsumerHealth | None = None,
    connect: Callable[[str], AsyncIterator[str]] = _default_connect,
    timeframe: str = "1m",
    rng: random.Random | None = None,
) -> ConsumerHealth:
    """The supervised consume loop: (re)connect forever until `stop`, push every CLOSED bar to `sink`
    (a plain callable — the worker wraps the threaded DB write), count everything in `health`. A connect
    or stream error backs off exponentially with full jitter; a single bad frame is counted and skipped."""
    health = health or ConsumerHealth(name=f"binance_ws_{timeframe}")
    rng = rng or random.Random()
    url = stream_url(symbols, timeframe)
    failures = 0
    while not stop.is_set():
        try:
            async for raw in connect(url):
                if stop.is_set():
                    break
                health.frames += 1
                failures = 0  # a flowing stream resets the backoff ladder
                try:
                    parsed = parse_closed_kline(raw)
                except (ValueError, KeyError, TypeError) as exc:
                    health.frame_errors += 1
                    health.last_error = f"frame: {exc}"
                    continue
                if parsed is None:
                    continue
                symbol, bar = parsed
                try:
                    sink(symbol, bar)
                    health.closed_bars += 1
                    health.last_ok = datetime.now(tz=UTC)
                except Exception as exc:  # noqa: BLE001 — a sink hiccup (DB blip) must not kill the stream
                    health.frame_errors += 1
                    health.last_error = f"sink: {exc}"
            if stop.is_set():
                break
            # The server closed a healthy stream (24h Binance rotation) → reconnect immediately-ish.
            health.reconnects += 1
        except Exception as exc:  # noqa: BLE001 — transport/connect error → backoff, never crash the worker
            health.reconnects += 1
            health.last_error = f"connect: {exc}"
            failures += 1
        delay = min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * (2 ** max(0, failures - 1))) * rng.random()
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.05, delay))
        except TimeoutError:
            pass
    return health
