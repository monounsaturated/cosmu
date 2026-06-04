# Offline tests for the multi-asset BAR layer: the crypto-deep ccxt venues (Bybit/OKX) backfill through the
# same paginated path as Binance/Kraken, and the FREE non-crypto daily bars (stocks/FX/metals) come from Stooq
# CSV. Everything injected — no live network. Also exercises the managed backfill selector for a non-default
# venue (bars:stooq) end-to-end into the bar cache.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.ingest.bars import (
    CcxtBarBackfiller,
    StooqBarBackfiller,
    _stooq_bar_symbol,
    bar_cache_path,
    read_cached_bars,
)
from cosmu.ingest.manage import DataManager, _default_bar_backfiller

_T0 = datetime(2023, 1, 1, tzinfo=UTC)
_DAY_MS = 86_400_000

_STOOQ_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2023-01-01,100,101,99,100.5,10\n"
    "2023-01-02,100.5,102,100,101.5,12\n"
    "2023-01-03,101.5,103,101,102.5,11\n"
)


def _ccxt_rows(n: int) -> list[list]:
    start = int(_T0.timestamp() * 1000)
    return [[start + i * _DAY_MS, 100 + i, 101 + i, 99 + i, 100.5 + i, 10 + i] for i in range(n)]


def _ccxt_fetcher(rows):
    def fetch(symbol: str, timeframe: str, since: int, limit: int) -> list[list]:
        return [r for r in rows if r[0] >= since][:limit]
    return fetch


def test_bybit_and_okx_are_ccxt_venues():
    # Bybit + OKX use the BASE/USDT unified shape, so the existing paginated backfiller serves them.
    assert "bybit" in CcxtBarBackfiller._VENUE_SYMBOL
    assert "okx" in CcxtBarBackfiller._VENUE_SYMBOL
    for venue in ("bybit", "okx"):
        bf = CcxtBarBackfiller(venue, page_limit=300, _fetcher=_ccxt_fetcher(_ccxt_rows(120)))
        bars = bf.fetch_history("BTCUSDT", "1d", start_ms=int(_T0.timestamp() * 1000))
        assert len(bars) == 120


def test_stooq_bar_symbol_mapping():
    assert _stooq_bar_symbol("SPY") == "spy.us"       # US equity gets the .us suffix
    assert _stooq_bar_symbol("AAPL") == "aapl.us"
    assert _stooq_bar_symbol("^spx") == "^spx"        # already-native index passes through
    assert _stooq_bar_symbol("EURUSD") == "eurusd"    # FX pair lower-cases
    assert _stooq_bar_symbol("spy.us") == "spy.us"


def test_stooq_bar_backfiller_window_and_timeframe():
    bf = StooqBarBackfiller(_fetcher=lambda url: _STOOQ_CSV)
    bars = bf.fetch_history("SPY", "1d", start_ms=int(_T0.timestamp() * 1000))
    assert len(bars) == 3
    assert bars[0].close == Decimal("100.5")
    # window filter: start after the first bar drops it
    bars2 = bf.fetch_history("SPY", "1d", start_ms=int((_T0 + timedelta(days=1)).timestamp() * 1000))
    assert len(bars2) == 2
    # Stooq serves daily only — a sub-daily timeframe is honest [], never a fabricated bar
    assert bf.fetch_history("SPY", "1h", start_ms=int(_T0.timestamp() * 1000)) == []


def test_default_factory_picks_stooq_for_non_ccxt_venue():
    assert isinstance(_default_bar_backfiller("stooq"), StooqBarBackfiller)
    assert isinstance(_default_bar_backfiller("bybit"), CcxtBarBackfiller)


def test_manage_backfill_bars_stooq_into_cache(tmp_path):
    mgr = DataManager(
        market_data_dir=tmp_path / "market_data",
        clock=lambda: _T0 + timedelta(days=30),
        bar_backfiller_factory=lambda venue: StooqBarBackfiller(_fetcher=lambda url: _STOOQ_CSV),
    )
    result = mgr.backfill("bars:stooq", days=400, symbols=["SPY"], timeframe="1d")
    assert result["kind"] == "bars"
    r = result["results"][("stooq", "SPY")]
    assert r.written == 3
    cached = read_cached_bars(bar_cache_path(tmp_path / "market_data" / "stooq", "SPY", "1d"))
    assert len(cached) == 3
