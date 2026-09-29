# Offline tests for the historical funding backfill (paginated Binance provider + idempotent dedup append +
# run-level memoization). NO live network: a canned `_fetcher` replays Binance `fundingRate` pages.

from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataPoint, AltDataStore, BinanceFundingHistoryProvider
from cosmu.ingest.pipeline import MemoizingProvider, append_dedup, backfill_funding

_FUND_MS = 8 * 3600 * 1000  # Binance funds every 8h
_START = int(datetime(2023, 1, 1, tzinfo=UTC).timestamp() * 1000)
_N = 1650  # ~1.5 years of 8h funding → proves a single backfill spans >1yr


def _full_history(n: int = _N) -> list[dict]:
    return [{"fundingTime": _START + i * _FUND_MS, "fundingRate": f"{0.0001 * (1 if i % 2 else -1):.8f}"} for i in range(n)]


def _paged_fetcher(full_rows: list[dict]):
    """Simulate Binance: return up to `limit` rows with startTime <= fundingTime <= endTime, ascending."""
    def fetch(url: str) -> list[dict]:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        start = int(q["startTime"][0])
        end = int(q["endTime"][0]) if "endTime" in q else None
        lim = int(q["limit"][0])
        page = [r for r in full_rows if r["fundingTime"] >= start and (end is None or r["fundingTime"] <= end)]
        return page[:lim]
    return fetch


def test_paginates_full_history_across_many_pages_over_one_year():
    full = _full_history()
    prov = BinanceFundingHistoryProvider(page_limit=500, _fetcher=_paged_fetcher(full))  # tiny page → many pages
    pts = prov.fetch_history("BTCUSDT", start_ms=_START, end_ms=full[-1]["fundingTime"])
    assert len(pts) == _N  # every row walked, despite the 500-row page cap
    # ascending, de-duped, and the realized rate IS the point-in-time stamp (available_at == ts)
    assert [p.ts for p in pts] == sorted(p.ts for p in pts)
    assert len({p.ts for p in pts}) == _N
    assert all(p.available_at == p.ts for p in pts)
    assert (pts[-1].ts - pts[0].ts) > timedelta(days=365)  # ≥1 year of depth in one call


def test_stops_on_short_final_page():
    full = _full_history(1650)
    prov = BinanceFundingHistoryProvider(page_limit=1000, _fetcher=_paged_fetcher(full))
    pts = prov.fetch_history("BTCUSDT", start_ms=_START, end_ms=full[-1]["fundingTime"])
    assert len(pts) == 1650  # page1=1000 (full) + page2=650 (<1000 → exhausted, stop)


def test_overlapping_page_boundary_is_deduped():
    # A misbehaving feed that re-emits the boundary row on the next page must not double-count it.
    pages = iter([
        [{"fundingTime": 0, "fundingRate": "0.0001"}, {"fundingTime": 1, "fundingRate": "0.0002"}],
        [{"fundingTime": 1, "fundingRate": "0.0002"}, {"fundingTime": 2, "fundingRate": "0.0003"}],  # ft=1 overlaps
    ])
    prov = BinanceFundingHistoryProvider(page_limit=2, _fetcher=lambda url: next(pages, []))
    pts = prov.fetch_history("BTCUSDT", start_ms=0, end_ms=10)
    assert [int(p.ts.timestamp() * 1000) for p in pts] == [0, 1, 2]  # ft=1 appears exactly once


def test_fetch_series_returns_trailing_limit():
    full = _full_history()
    prov = BinanceFundingHistoryProvider(page_limit=1000, _fetcher=_paged_fetcher(full))
    pts = prov.fetch_series("BTCUSDT", "funding_rate", limit=10)
    assert len(pts) <= 10
    assert prov.fetch_series("BTCUSDT", "open_interest", limit=10) == []  # wrong metric → empty


def test_backfill_is_idempotent_and_records_span(tmp_path):
    full = _full_history()
    store = AltDataStore(tmp_path / "alt")
    prov = BinanceFundingHistoryProvider(page_limit=1000, _fetcher=_paged_fetcher(full))

    first = backfill_funding(store, prov, ["BTCUSDT"], start_ms=_START, end_ms=full[-1]["fundingTime"])
    assert first["BTCUSDT"].written == _N
    assert first["BTCUSDT"].span_days > 365
    stored = store.read_all("binance", "BTCUSDT", "funding_rate")
    assert len(stored) == _N

    # Re-run: append-only + dedup on (provider, symbol, metric, ts) → ZERO new rows, view unchanged.
    second = backfill_funding(store, prov, ["BTCUSDT"], start_ms=_START, end_ms=full[-1]["fundingTime"])
    assert second["BTCUSDT"].written == 0
    assert len(store.read_all("binance", "BTCUSDT", "funding_rate")) == _N


def test_append_dedup_only_writes_new_points(tmp_path):
    full = _full_history(10)
    store = AltDataStore(tmp_path / "alt")
    prov = BinanceFundingHistoryProvider(page_limit=1000, _fetcher=_paged_fetcher(full))
    pts = prov.fetch_history("ETHUSDT", start_ms=_START, end_ms=full[-1]["fundingTime"])
    assert append_dedup(store, "binance", "ETHUSDT", "funding_rate", pts) == 10
    assert append_dedup(store, "binance", "ETHUSDT", "funding_rate", pts) == 0  # all already present
    # extend the window with two genuinely-new points → only those two are written
    base = prov.fetch_history("ETHUSDT", start_ms=_START, end_ms=full[-1]["fundingTime"])
    last = base[-1].ts
    new1 = AltDataPoint(ts=last + timedelta(hours=8), available_at=last + timedelta(hours=8), value=0.001)
    new2 = AltDataPoint(ts=last + timedelta(hours=16), available_at=last + timedelta(hours=16), value=0.002)
    assert append_dedup(store, "binance", "ETHUSDT", "funding_rate", base + [new1, new2]) == 2


def test_memoizing_provider_fetches_each_window_once():
    class Counter:
        def __init__(self):
            self.calls: list[tuple[str, str, int]] = []

        def fetch_series(self, symbol, metric, *, limit):
            self.calls.append((symbol, metric, limit))
            return [object()]

    inner = Counter()
    mem = MemoizingProvider(inner)
    a = mem.fetch_series("MARKET", "VIXCLS", limit=1000)
    b = mem.fetch_series("MARKET", "VIXCLS", limit=1000)  # same window → served from cache
    assert a is b
    assert inner.calls == [("MARKET", "VIXCLS", 1000)]  # inner hit exactly once
    assert mem.calls == 1
    mem.fetch_series("MARKET", "VIXCLS", limit=500)  # different window → a real miss
    assert mem.calls == 2
