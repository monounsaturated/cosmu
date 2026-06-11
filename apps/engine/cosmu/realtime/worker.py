# intent: the REALTIME WORKER SUPERVISOR (realtime-data-lane epic P3) — one asyncio task tree that RECORDS:
# Binance WS closed 1m candles → bars_intraday (+ best-effort local bar-cache write-through), budget-guarded
# poll collectors → market_events (lexicon-enriched, $0) / alt_data, a 60-second heartbeat into the events
# ledger (the staleness badge's source of truth), and daily retention (1m → 5m rollup). Runs IN-PROCESS
# inside the FastAPI lifespan (OFF by default — REALTIME_WORKER_ENABLED=1 activates; the operator's lean-infra
# decision 2026-06-11: no second Railway service) or standalone via `python3 -m cosmu.realtime.worker`.
# invariants: it RECORDS, never executes (no order path, no kill-switch to check — there is nothing to kill);
# every sub-task is crash-isolated and restarted with backoff (a dying consumer degrades freshness to the
# cron lane, never takes the API down); all writes are deduped/idempotent (restarts are normal, not
# incidents); DB and network work runs in threads so the API's event loop never blocks; stop → prompt, clean
# shutdown. Offline-testable: every seam (connect, fetchers, store, clock) injects.

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from cosmu.config.settings import Settings, get_settings
from cosmu.data.altdata import PgAltDataStore
from cosmu.data.events_store import MarketEvent, PgEventsStore
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.realtime.bars_store import IntradayBarsStore
from cosmu.realtime.binance_ws import ConsumerHealth, run_kline_consumer
from cosmu.realtime.collectors import (
    AltRecord,
    Collector,
    fetch_cryptopanic_events,
    fetch_polymarket_points,
    fetch_rss_events,
    run_collector,
)

logger = logging.getLogger("cosmu.realtime.worker")

# The recording universe: liquid majors, bounded (epic §6 storage math covers ~30 symbols; start at 10).
REALTIME_SYMBOLS: tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
)

HEARTBEAT_INTERVAL_S = 60.0
RETENTION_INTERVAL_S = 24 * 3600.0
_TASK_RESTART_BACKOFF_S = 5.0


@dataclass
class WorkerState:
    """The live registry the heartbeat snapshots — one health record per consumer/collector."""

    started_at: datetime
    ws: ConsumerHealth = field(default_factory=lambda: ConsumerHealth(name="binance_ws_1m"))
    collectors: list[Collector] = field(default_factory=list)
    heartbeats: int = 0
    task_restarts: int = 0

    def payload(self, now: datetime) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "heartbeats": self.heartbeats,
            "task_restarts": self.task_restarts,
            "consumers": {
                self.ws.name: self.ws.snapshot(now),
                **{c.name: c.state.snapshot(now) for c in self.collectors},
            },
        }


def _bar_sink(store: Store, *, cache_dir: str | None = None) -> Callable[[str, Bar], None]:
    """The WS consumer's sink: durable PG write (deduped) + best-effort local bar-cache write-through (the
    cache is ephemeral on Railway but keeps same-container reads warm). Rate is gentle (~symbols/minute),
    so per-bar writes need no queueing — boundedness comes from the rate itself."""
    bars = IntradayBarsStore(store)

    def sink(symbol: str, bar: Bar) -> None:
        bars.insert_closed_bars(symbol, "1m", [bar])
        if cache_dir is not None:
            try:
                from cosmu.ingest.bars import bar_cache_path, read_cached_bars, write_bars_cache

                path = bar_cache_path(cache_dir, symbol, "1m")
                if len(read_cached_bars(path)) < 100_000:  # bounded: the durable copy is PG, not this file
                    write_bars_cache(path, [bar])
            except Exception:  # noqa: BLE001 — the cache is a warm-read bonus, never load-bearing
                pass

    return sink


def _events_sink(store: Store) -> Callable[[list[MarketEvent]], None]:
    """Collector events → lexicon enrichment ($0, deterministic — LLM enrichment stays a batch/research
    concern) → the deduped durable store. Receipt-time available_at is already stamped by the fetchers."""
    events_store = PgEventsStore(store)

    def sink(events: list[MarketEvent]) -> None:
        from cosmu.ingest.llm_formatter import enrich_market_events

        events_store.append(enrich_market_events(events))

    return sink


def _alt_sink(store: Store) -> Callable[[list[AltRecord]], None]:
    alt = PgAltDataStore(store)

    def sink(records: list[AltRecord]) -> None:
        for provider, symbol, metric, point in records:
            alt.append(provider, symbol, metric, [point])

    return sink


def default_collectors(settings: Settings) -> list[Collector]:
    """The poll lane: cadences + daily budgets per source (epic §6 — stay polite on free APIs; budgets bound
    the worst case even if an interval is misconfigured). Key-gated fetchers degrade to [] keylessly."""
    return [
        Collector(name="rss_news", fetch=fetch_rss_events, interval_s=180.0, daily_budget=600),
        Collector(
            name="cryptopanic",
            fetch=lambda: fetch_cryptopanic_events(api_key=settings.cryptopanic_api_key or ""),
            interval_s=300.0,
            daily_budget=180,  # well under the free tier's daily quota even with retries
        ),
        Collector(name="polymarket", fetch=fetch_polymarket_points, interval_s=300.0, daily_budget=288),
    ]


async def _heartbeat_task(store: Store, state: WorkerState, *, stop: asyncio.Event,
                          interval_s: float = HEARTBEAT_INTERVAL_S) -> None:
    """The visibility contract (epic §3): a fresh `realtime_heartbeat` event every minute while alive; a
    stale heartbeat IS the worker-down signal the API/web read — silence is never ambiguous."""
    while not stop.is_set():
        now = datetime.now(tz=UTC)
        try:
            await asyncio.to_thread(
                store.append_event,
                actor="realtime", kind="realtime_heartbeat", ref_type="worker", ref_id="in-process",
                payload=state.payload(now),
            )
            state.heartbeats += 1
        except Exception as exc:  # noqa: BLE001 — a DB blip skips one beat, never kills the worker
            logger.warning("heartbeat write failed: %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            pass


async def _retention_task(store: Store, *, stop: asyncio.Event,
                          interval_s: float = RETENTION_INTERVAL_S) -> None:
    bars = IntradayBarsStore(store)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
            break  # stop was set
        except TimeoutError:
            pass
        try:
            result = await asyncio.to_thread(bars.run_retention)
            logger.info("retention: %s", result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("retention failed (retried next cycle): %s", exc)


async def _supervised(name: str, factory: Callable[[], object], state: WorkerState, stop: asyncio.Event) -> None:
    """Restart-on-unexpected-death wrapper. The loops inside already self-handle expected errors; this guards
    the truly unexpected so one consumer can never silently vanish for the worker's lifetime."""
    while not stop.is_set():
        try:
            await factory()  # type: ignore[misc]
            if not stop.is_set():
                state.task_restarts += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            state.task_restarts += 1
            logger.warning("task %s died (%s) — restarting in %ss", name, exc, _TASK_RESTART_BACKOFF_S)
        if not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=_TASK_RESTART_BACKOFF_S)
            except TimeoutError:
                pass


async def run_worker(
    store: Store | None = None,
    *,
    settings: Settings | None = None,
    stop: asyncio.Event | None = None,
    symbols: tuple[str, ...] = REALTIME_SYMBOLS,
    collectors: list[Collector] | None = None,
    connect=None,  # noqa: ANN001 — async connect seam for the WS consumer (tests inject)
    enable_ws: bool = True,
    heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S,
) -> WorkerState:
    """Run the whole recording tree until `stop`. Returns the final WorkerState (tests assert on it)."""
    settings = settings or get_settings()
    store = store or Store(settings)
    stop = stop or asyncio.Event()
    state = WorkerState(started_at=datetime.now(tz=UTC))
    state.collectors = collectors if collectors is not None else default_collectors(settings)

    events_sink, alt_sink = _events_sink(store), _alt_sink(store)
    tasks: list[asyncio.Task] = []
    if enable_ws:
        ws_kwargs = {"connect": connect} if connect is not None else {}
        tasks.append(asyncio.create_task(_supervised(
            "binance_ws",
            lambda: run_kline_consumer(list(symbols), _bar_sink(store), stop=stop, health=state.ws, **ws_kwargs),
            state, stop,
        )))
    for collector in state.collectors:
        tasks.append(asyncio.create_task(_supervised(
            collector.name,
            lambda c=collector: run_collector(c, events_sink=events_sink, alt_sink=alt_sink, stop=stop),
            state, stop,
        )))
    tasks.append(asyncio.create_task(_heartbeat_task(store, state, stop=stop, interval_s=heartbeat_interval_s)))
    tasks.append(asyncio.create_task(_retention_task(store, stop=stop)))

    try:
        await stop.wait()
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return state


def latest_heartbeat(store: Store) -> dict | None:
    """The newest realtime_heartbeat event row (ts + payload) — what /realtime/status and the badge read."""
    row = store.row(
        "SELECT ts, payload FROM events WHERE kind = 'realtime_heartbeat' ORDER BY id DESC LIMIT 1"
    )
    if not row:
        return None
    import json

    ts = datetime.fromisoformat(str(row["ts"]))
    return {"ts": (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).isoformat(),
            "payload": json.loads(row["payload"] or "{}")}


def _main(argv: list[str] | None = None) -> int:
    """Standalone mode (`python3 -m cosmu.realtime.worker`) — the optional split-out-later lane; the default
    deployment is in-process via the FastAPI lifespan behind REALTIME_WORKER_ENABLED."""
    import argparse
    import signal

    argparse.ArgumentParser(description="Run the realtime recording worker standalone (Ctrl-C to stop).").parse_args(argv)

    async def main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # platforms without signal handlers
                pass
        state = await run_worker(stop=stop)
        print(f"worker stopped — heartbeats={state.heartbeats} ws_bars={state.ws.closed_bars} "
              f"restarts={state.task_restarts}")

    asyncio.run(main())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
