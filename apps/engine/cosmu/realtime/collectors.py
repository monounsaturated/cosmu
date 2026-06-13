# intent: BUDGET-GUARDED POLL COLLECTORS (realtime-data-lane epic P3) — the worker's short-poll lane for
# sources with no stream: each Collector wraps one sync fetcher (injectable, key-gated, reusing the existing
# source modules' parsing) and runs it every `interval_s` (+ full jitter) under a HARD daily call budget —
# on exhaustion it SKIPS-AND-COUNTS, never hammers a free API (the epic §6 guard). Outputs flow to two sinks:
# typed MarketEvents (receipt-time available_at — the recorded-live history tweets/news strategies need) and
# numeric alt points (deduped per (provider,symbol,metric,ts) before append so a poll of an unchanged daily
# series writes 0). invariants: one failing poll is counted + retried next tick (never a crash); budgets and
# clocks are injectable + deterministic in tests; a keyless fetcher returns [] (honest degradation).

from __future__ import annotations

import asyncio
import json
import random
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cosmu.data.altdata import AltDataPoint
from cosmu.data.events_store import MarketEvent

# (provider, symbol, metric, point) — the alt sink's unit.
AltRecord = tuple[str, str, str, AltDataPoint]


@dataclass
class CollectorOutput:
    events: list[MarketEvent] = field(default_factory=list)
    alt: list[AltRecord] = field(default_factory=list)


@dataclass
class CollectorState:
    """Mutable per-collector health the heartbeat snapshots."""

    name: str
    last_ok: datetime | None = None
    polls: int = 0
    items: int = 0
    errors: int = 0
    budget_skips: int = 0
    last_error: str = ""
    _budget_day: str = ""
    _budget_used: int = 0

    def snapshot(self, now: datetime) -> dict:
        return {
            "last_ok": self.last_ok.isoformat() if self.last_ok else None,
            "lag_s": (now - self.last_ok).total_seconds() if self.last_ok else None,
            "polls": self.polls, "items": self.items, "errors": self.errors,
            "budget_skips": self.budget_skips, "last_error": self.last_error[:160],
        }

    def take_budget(self, day: str, daily_budget: int) -> bool:
        """One poll's budget check — resets at the UTC date boundary; False = skip this tick."""
        if day != self._budget_day:
            self._budget_day, self._budget_used = day, 0
        if self._budget_used >= daily_budget:
            self.budget_skips += 1
            return False
        self._budget_used += 1
        return True


@dataclass
class Collector:
    name: str
    fetch: Callable[[], CollectorOutput]   # sync; run via to_thread; injectable in tests
    interval_s: float
    daily_budget: int
    state: CollectorState = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.state is None:
            self.state = CollectorState(name=self.name)


async def run_collector(
    collector: Collector,
    *,
    events_sink: Callable[[list[MarketEvent]], None],
    alt_sink: Callable[[list[AltRecord]], None],
    stop: asyncio.Event,
    rng: random.Random | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> CollectorState:
    """The supervised poll loop: jittered interval → budget gate → threaded fetch → sinks. Every failure is
    counted and survived; the loop exits promptly on `stop`."""
    rng = rng or random.Random()
    now_fn = now_fn or (lambda: datetime.now(tz=UTC))
    state = collector.state
    while not stop.is_set():
        now = now_fn()
        if state.take_budget(now.date().isoformat(), collector.daily_budget):
            state.polls += 1
            try:
                out = await asyncio.to_thread(collector.fetch)
                if out.events:
                    await asyncio.to_thread(events_sink, out.events)
                if out.alt:
                    await asyncio.to_thread(alt_sink, out.alt)
                state.items += len(out.events) + len(out.alt)
                state.last_ok = now_fn()
            except Exception as exc:  # noqa: BLE001 — one failed poll never kills the collector
                state.errors += 1
                state.last_error = str(exc)
        delay = collector.interval_s * (0.75 + 0.5 * rng.random())  # ±25% full-jitter around the interval
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.05, delay))
        except TimeoutError:
            pass
    return state


# --------------------------------------------------------------------------- concrete fetchers (sync, thin)
# Each composes an EXISTING source module's parsing where one exists; all are injectable/keyless-honest.


def fetch_rss_events(
    *,
    feeds: list[str] | None = None,
    fetch_url: Callable[[str], str] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    max_items_per_feed: int = 30,
) -> CollectorOutput:
    """Headline events from the curated public RSS feeds (keyless): `ts` = the item's own published time,
    `available_at` = OUR receipt (now). Dedup downstream rides the events store's content_hash."""
    from cosmu.data.sources.rss_news import _DEFAULT_FEEDS, _fetch_url, _parse_rss_items_with_titles

    feeds = feeds if feeds is not None else list(_DEFAULT_FEEDS["MARKET"])
    fetch_url = fetch_url or _fetch_url
    now = (now_fn or (lambda: datetime.now(tz=UTC)))()
    events: list[MarketEvent] = []
    for url in feeds:
        host = urllib.parse.urlparse(url).netloc
        for published, title in _parse_rss_items_with_titles(fetch_url(url))[-max_items_per_feed:]:
            events.append(MarketEvent(
                provider="rss", source=host, symbols=(), ts=published, available_at=now, title=title,
            ).hydrated())
    return CollectorOutput(events=events)


def fetch_cryptopanic_events(
    *,
    api_key: str,
    currencies: tuple[str, ...] = ("BTC", "ETH"),
    fetcher: Callable[[str], dict] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> CollectorOutput:
    """CryptoPanic /posts/ headlines as typed events (key-gated: no key → []). `ts` = published_at,
    `available_at` = receipt."""
    if not api_key:
        return CollectorOutput()
    now = (now_fn or (lambda: datetime.now(tz=UTC)))()

    def _default_fetch(url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 — fixed https host
            return json.loads(resp.read().decode("utf-8"))

    fetch = fetcher or _default_fetch
    events: list[MarketEvent] = []
    for coin in currencies:
        params = urllib.parse.urlencode(
            {"auth_token": api_key, "currencies": coin, "public": "true", "kind": "news", "page_size": 50}
        )
        payload = fetch(f"https://cryptopanic.com/api/v1/posts/?{params}")
        for post in payload.get("results", []) or []:
            title = str(post.get("title") or "").strip()
            raw_ts = str(post.get("published_at") or "")
            if not title or not raw_ts:
                continue
            try:
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            events.append(MarketEvent(
                provider="cryptopanic", source=str((post.get("source") or {}).get("title") or ""),
                symbols=(f"{coin}USDT",), ts=ts, available_at=now, title=title,
            ).hydrated())
    return CollectorOutput(events=events)


def fetch_polymarket_points(
    *,
    source=None,  # noqa: ANN001 — PolymarketClobSource (injectable)
    now_fn: Callable[[], datetime] | None = None,
) -> CollectorOutput:
    """The latest Polymarket implied-prob reading as a recorded-live alt point: `available_at` = receipt
    (the worker's clock), regardless of the source's own daily-candle stamps — recorded-live history is the
    only honest backtest basis for a real-time strategy (epic §3 PIT rule)."""
    from cosmu.data.sources.polymarket import PolymarketClobSource

    src = source if source is not None else PolymarketClobSource()
    now = (now_fn or (lambda: datetime.now(tz=UTC)))()
    points = src.fetch_series("MARKET", "pm_implied_prob", limit=1)
    if not points:
        return CollectorOutput()
    latest = points[-1]
    return CollectorOutput(alt=[
        ("polymarket_rt", "MARKET", "pm_implied_prob_rt", AltDataPoint(ts=now, available_at=now, value=float(latest.value))),
    ])
