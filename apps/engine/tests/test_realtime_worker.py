# The realtime recording worker (cosmu/realtime/*, epic P3): closed-candles-only WS consumption with
# reconnect/backoff, idempotent durable bar writes + 1m→5m retention rollup, budget-guarded poll collectors,
# heartbeat visibility, crash-isolated supervision, and the OFF-by-default status endpoint. Offline +
# deterministic: every network/clock seam is injected; async paths run under asyncio.run (no plugin).

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.events_store import MarketEvent
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.realtime.bars_store import IntradayBarsStore, rollup
from cosmu.realtime.binance_ws import ConsumerHealth, parse_closed_kline, run_kline_consumer, stream_url
from cosmu.realtime.collectors import (
    Collector,
    CollectorOutput,
    fetch_cryptopanic_events,
    fetch_rss_events,
    run_collector,
)
from cosmu.realtime.worker import run_worker

_T0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/rt.sqlite3", openrouter_api_key=None))


def _bar(minute: int, price: str = "100") -> Bar:
    p = Decimal(price)
    return Bar(ts=_T0 + timedelta(minutes=minute), open=p, high=p, low=p, close=p, volume=Decimal("1"))


def _kline_frame(symbol: str, minute: int, *, closed: bool, close: str = "100") -> str:
    open_ms = int((_T0 + timedelta(minutes=minute)).timestamp() * 1000)
    return json.dumps({
        "stream": f"{symbol.lower()}@kline_1m",
        "data": {"e": "kline", "s": symbol,
                 "k": {"t": open_ms, "s": symbol, "x": closed,
                       "o": "99", "h": close, "l": "98", "c": close, "v": "5"}},
    })


# --------------------------------------------------------------------------------------- bars store / retention


def test_bars_store_dedups_within_batch_and_against_table(tmp_path):
    store = IntradayBarsStore(_store(tmp_path))
    assert store.insert_closed_bars("BTCUSDT", "1m", [_bar(0), _bar(0), _bar(1)]) == 2
    assert store.insert_closed_bars("BTCUSDT", "1m", [_bar(1), _bar(2)]) == 1  # replay writes only the new bar
    assert [b.ts for b in store.read_bars("BTCUSDT", "1m")] == [_bar(0).ts, _bar(1).ts, _bar(2).ts]
    assert store.latest_ts("BTCUSDT", "1m") == _bar(2).ts


def test_rollup_aggregates_ohlcv_correctly():
    bars = [
        Bar(ts=_T0, open=Decimal("10"), high=Decimal("12"), low=Decimal("9"), close=Decimal("11"), volume=Decimal("1")),
        Bar(ts=_T0 + timedelta(minutes=1), open=Decimal("11"), high=Decimal("15"), low=Decimal("10"), close=Decimal("14"), volume=Decimal("2")),
        Bar(ts=_T0 + timedelta(minutes=6), open=Decimal("14"), high=Decimal("14"), low=Decimal("13"), close=Decimal("13"), volume=Decimal("3")),
    ]
    fives = rollup(bars, minutes=5)
    assert len(fives) == 2  # two buckets touched; the empty bucket between them does NOT exist (no zero-fill)
    first = fives[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (
        Decimal("10"), Decimal("15"), Decimal("9"), Decimal("14"), Decimal("3"))


def test_retention_rolls_up_then_deletes_only_covered_rows(tmp_path):
    store = IntradayBarsStore(_store(tmp_path))
    now = _T0 + timedelta(days=100)
    old = [_bar(i) for i in range(10)]                # 100 days old → past retention
    recent_ts = now - timedelta(days=1)
    recent = [Bar(ts=recent_ts, open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"))]
    store.insert_closed_bars("BTCUSDT", "1m", old + recent)

    result = store.run_retention(now=now, retention_days=90)

    assert result["rolled_up_5m"] == 2 and result["deleted_1m"] == 10
    assert len(store.read_bars("BTCUSDT", "5m")) == 2          # the rollups exist
    remaining = store.read_bars("BTCUSDT", "1m")
    assert [b.ts for b in remaining] == [recent_ts]            # recent 1m data untouched
    # Idempotent: a second run finds nothing old to do.
    again = store.run_retention(now=now, retention_days=90)
    assert again == {"rolled_up_5m": 0, "deleted_1m": 0}


# --------------------------------------------------------------------------------------- WS consumer


def test_parse_closed_kline_only_emits_closed_candles():
    closed = parse_closed_kline(_kline_frame("BTCUSDT", 3, closed=True, close="101"))
    assert closed is not None
    symbol, bar = closed
    assert symbol == "BTCUSDT" and bar.ts == _T0 + timedelta(minutes=3) and bar.close == Decimal("101")
    assert parse_closed_kline(_kline_frame("BTCUSDT", 4, closed=False)) is None  # in-progress → dropped
    assert parse_closed_kline(json.dumps({"data": {"e": "trade"}})) is None      # non-kline → ignored


def test_stream_url_shape():
    url = stream_url(["BTCUSDT", "ETHUSDT"])
    assert url.endswith("btcusdt@kline_1m/ethusdt@kline_1m")


def _consume(frames_per_connect: list[list[str | Exception]], *, max_loops: int) -> tuple[list, ConsumerHealth]:
    """Drive run_kline_consumer against scripted connections: each inner list is one connection's frames
    (an Exception entry raises mid-stream). After the script is exhausted, stop is set."""
    received: list[tuple[str, Bar]] = []
    health = ConsumerHealth(name="t")
    stop = asyncio.Event()
    attempts = {"n": 0}

    async def connect(_url: str):
        i = attempts["n"]
        attempts["n"] += 1
        if i >= len(frames_per_connect) or attempts["n"] > max_loops:
            stop.set()
            return
        for item in frames_per_connect[i]:
            if isinstance(item, Exception):
                raise item
            yield item
        if i == len(frames_per_connect) - 1:
            stop.set()

    asyncio.run(run_kline_consumer(
        ["BTCUSDT"], lambda s, b: received.append((s, b)), stop=stop, health=health, connect=connect,
    ))
    return received, health


def test_consumer_sinks_closed_bars_and_reconnects_after_errors():
    frames = [
        [_kline_frame("BTCUSDT", 0, closed=True), _kline_frame("BTCUSDT", 1, closed=False)],
        [OSError("socket reset")],                                  # transport error mid-stream → backoff
        ["not json at all", _kline_frame("BTCUSDT", 1, closed=True)],  # bad frame skipped, stream survives
    ]
    received, health = _consume(frames, max_loops=10)
    assert [b.ts for _, b in received] == [_T0, _T0 + timedelta(minutes=1)]  # closed candles only
    assert health.closed_bars == 2 and health.reconnects >= 2
    assert health.frame_errors == 1 and "frame:" in health.last_error


def test_consumer_survives_a_sink_failure():
    def bad_sink(_s: str, _b: Bar) -> None:
        raise RuntimeError("db blip")

    health = ConsumerHealth(name="t")
    stop = asyncio.Event()

    async def connect(_url: str):
        yield _kline_frame("BTCUSDT", 0, closed=True)
        yield _kline_frame("BTCUSDT", 1, closed=True)
        stop.set()

    asyncio.run(run_kline_consumer(["BTCUSDT"], bad_sink, stop=stop, health=health, connect=connect))
    assert health.frame_errors == 2 and "sink:" in health.last_error
    assert health.closed_bars == 0  # nothing recorded as OK — silence would have lied


# --------------------------------------------------------------------------------------- collectors


def _run_collector_until(collector: Collector, *, ticks: int, now_fn=None) -> tuple[list, list]:
    events_out: list[MarketEvent] = []
    alt_out: list = []
    stop = asyncio.Event()
    seen = {"n": 0}
    original = collector.fetch

    def counting_fetch() -> CollectorOutput:
        seen["n"] += 1
        if seen["n"] >= ticks:
            stop.set()
        return original()

    collector.fetch = counting_fetch
    asyncio.run(asyncio.wait_for(run_collector(
        collector, events_sink=events_out.extend, alt_sink=alt_out.extend, stop=stop, now_fn=now_fn,
    ), timeout=10))
    return events_out, alt_out


def test_collector_delivers_and_counts():
    ev = MarketEvent(provider="t", source="s", symbols=(), ts=_T0, available_at=_T0, title="x").hydrated()
    c = Collector(name="t", fetch=lambda: CollectorOutput(events=[ev]), interval_s=0.01, daily_budget=100)
    events, _alt = _run_collector_until(c, ticks=3)
    assert len(events) == 3 and c.state.polls == 3 and c.state.errors == 0


def test_collector_budget_exhaustion_skips_never_hammers():
    calls = {"n": 0}

    def fetch() -> CollectorOutput:
        calls["n"] += 1
        return CollectorOutput()

    c = Collector(name="t", fetch=fetch, interval_s=0.01, daily_budget=2)
    stop = asyncio.Event()

    async def run():
        task = asyncio.create_task(run_collector(c, events_sink=lambda e: None, alt_sink=lambda a: None, stop=stop))
        while c.state.budget_skips < 3:  # well past the budget — fetches must have stopped
            await asyncio.sleep(0.01)
        stop.set()
        await task

    asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert calls["n"] == 2  # the daily budget is a hard ceiling


def test_collector_fetch_error_is_counted_and_survived():
    boom = {"first": True}

    def fetch() -> CollectorOutput:
        if boom["first"]:
            boom["first"] = False
            raise OSError("api down")
        return CollectorOutput()

    c = Collector(name="t", fetch=fetch, interval_s=0.01, daily_budget=100)
    _run_collector_until(c, ticks=2)
    assert c.state.errors == 1 and "api down" in c.state.last_error
    assert c.state.polls >= 2  # it kept polling after the failure


_RSS_FIXTURE = """<?xml version="1.0"?><rss><channel>
<item><title>BTC ETF inflows hit a record</title><pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate></item>
<item><title>Exchange outage resolved</title><pubDate>Mon, 01 Jun 2026 11:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_rss_fetcher_stamps_receipt_availability():
    now = _T0 + timedelta(minutes=5)
    out = fetch_rss_events(feeds=["https://example.com/feed"], fetch_url=lambda _u: _RSS_FIXTURE,
                           now_fn=lambda: now)
    assert len(out.events) == 2
    assert all(e.available_at == now for e in out.events)          # receipt clock — the trading axis
    assert all(e.ts < now for e in out.events)                     # publish clock — the event-study axis
    assert out.events[0].provider == "rss" and out.events[0].source == "example.com"


def test_cryptopanic_fetcher_is_key_gated_and_typed():
    assert fetch_cryptopanic_events(api_key="").events == []  # no key → honest nothing

    payload = {"results": [
        {"title": "Whale moves 10k BTC", "published_at": "2026-06-01T10:00:00Z", "source": {"title": "CoinDesk"}},
        {"title": "", "published_at": "2026-06-01T10:01:00Z"},  # empty title → dropped
    ]}
    now = _T0 + timedelta(minutes=9)
    out = fetch_cryptopanic_events(api_key="k", currencies=("BTC",), fetcher=lambda _u: payload,
                                   now_fn=lambda: now)
    [e] = out.events
    assert e.provider == "cryptopanic" and e.symbols == ("BTCUSDT",) and e.source == "CoinDesk"
    assert e.available_at == now and e.ts == datetime(2026, 6, 1, 10, 0, tzinfo=UTC)


# --------------------------------------------------------------------------------------- worker integration


def test_worker_end_to_end_records_bars_events_and_heartbeats(tmp_path):
    store = _store(tmp_path)
    stop = asyncio.Event()

    async def connect(_url: str):
        yield _kline_frame("BTCUSDT", 0, closed=True, close="100")
        yield _kline_frame("BTCUSDT", 1, closed=False)             # in-progress — must NOT be recorded
        yield _kline_frame("ETHUSDT", 1, closed=True, close="50")
        while not stop.is_set():                                   # hold the stream open until shutdown
            await asyncio.sleep(0.01)

    ev = MarketEvent(provider="t", source="s", symbols=(), ts=_T0, available_at=_T0, title="headline").hydrated()
    collector = Collector(name="fixture", fetch=lambda: CollectorOutput(events=[ev]), interval_s=0.02, daily_budget=5)

    async def run():
        task = asyncio.create_task(run_worker(
            store, settings=store.settings, stop=stop, symbols=("BTCUSDT", "ETHUSDT"),
            collectors=[collector], connect=connect, heartbeat_interval_s=0.05,
        ))
        deadline = asyncio.get_running_loop().time() + 8
        bars = IntradayBarsStore(store)
        while asyncio.get_running_loop().time() < deadline:
            have_bars = len(bars.read_bars("BTCUSDT", "1m")) >= 1 and len(bars.read_bars("ETHUSDT", "1m")) >= 1
            have_beat = store.row("SELECT id FROM events WHERE kind='realtime_heartbeat'") is not None
            have_event = store.row("SELECT id FROM market_events WHERE provider='t'") is not None
            if have_bars and have_beat and have_event:
                break
            await asyncio.sleep(0.02)
        stop.set()
        return await task

    state = asyncio.run(asyncio.wait_for(run(), timeout=15))

    bars = IntradayBarsStore(store)
    assert [b.close for b in bars.read_bars("BTCUSDT", "1m")] == [Decimal("100")]
    assert [b.close for b in bars.read_bars("ETHUSDT", "1m")] == [Decimal("50")]   # closed candles only
    assert store.row("SELECT id FROM market_events WHERE provider = 't'") is not None
    beat = store.row("SELECT payload FROM events WHERE kind='realtime_heartbeat' ORDER BY id DESC LIMIT 1")
    consumers = json.loads(beat["payload"])["consumers"]
    assert "binance_ws_1m" in consumers and "fixture" in consumers  # the badge's source of truth
    assert state.ws.closed_bars == 2


# --------------------------------------------------------------------------------------- the status endpoint


def test_realtime_status_endpoint_states(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import cosmu.api._shared as shared
    from cosmu.api.app import app

    store = _store(tmp_path)
    monkeypatch.setattr(shared, "store", store)
    monkeypatch.setattr("cosmu.api.routers.realtime.store", store)
    client = TestClient(app)

    # Default: the worker is OFF — status says so, no fabricated freshness.
    body = client.get("/realtime/status").json()
    assert body["enabled"] is False and body["status"] == "off"
    assert body["last_heartbeat_at"] is None

    # Enabled but silent → 'never' (the honest alarm state before the first beat).
    monkeypatch.setattr(shared.settings, "realtime_worker_enabled", True)
    monkeypatch.setattr("cosmu.api.routers.realtime.settings", shared.settings)
    body = client.get("/realtime/status").json()
    assert body["status"] == "never"

    # A fresh heartbeat → 'fresh' with consumer snapshots; an old one → 'stale'.
    store.append_event(actor="realtime", kind="realtime_heartbeat", ref_type="worker", ref_id="t",
                       payload={"consumers": {"binance_ws_1m": {"lag_s": 5}}})
    body = client.get("/realtime/status").json()
    assert body["status"] == "fresh" and body["consumers"]["binance_ws_1m"]["lag_s"] == 5
