# Offline tests for the managed-data control surface (ingest/manage.py). Everything is injected — fixture
# providers, a canned funding-history fetcher, a canned bar backfiller, and a fixed clock — so the whole
# fetch / backfill / verify / update surface runs with NO live network.

from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.altdata import (
    AltDataPoint,
    AltDataStore,
    BinanceFundingHistoryProvider,
    FixtureAltDataProvider,
    FixtureNewsProvider,
)
from cosmu.ingest.bars import CcxtBarBackfiller, bar_cache_path, read_cached_bars
from cosmu.ingest.manage import DataManager
from cosmu.ingest.run import Providers

_T0 = datetime(2023, 1, 1, tzinfo=UTC)
_NOW = _T0 + timedelta(days=30)
_DAY_MS = 86_400_000
_FUND_MS = 8 * 3600 * 1000


def _empty() -> FixtureAltDataProvider:
    return FixtureAltDataProvider({})


def _funding_fixture() -> FixtureAltDataProvider:
    return FixtureAltDataProvider(
        {("BTCUSDT", "funding_rate"): [AltDataPoint(ts=_T0 + timedelta(days=i), available_at=_T0 + timedelta(days=i), value=0.0001 * i) for i in range(5)]}
    )


def _all_fixture_providers(**overrides) -> Providers:
    """A Providers set where every source is an empty fixture unless overridden — no source hits the network."""
    base = dict(
        funding=_empty(), feargreed=_empty(), news=FixtureNewsProvider({}), fred=_empty(),
        polymarket=_empty(), liquidations=_empty(), putcall=_empty(), defillama=_empty(),
        open_interest=_empty(), basis=_empty(), netflow=_empty(), osint=_empty(), polymarket_clob=_empty(),
        reddit=_empty(), lunarcrush=_empty(), xai_twitter=_empty(), venue_fees=_empty(), multiasset=_empty(),
    )
    base.update(overrides)
    return Providers(**base)


def _bar_rows(n: int) -> list[list]:
    start = int(_T0.timestamp() * 1000)
    return [[start + i * _DAY_MS, 100 + i, 101 + i, 99 + i, 100.5 + i, 10 + i] for i in range(n)]


def _bar_fetcher(rows: list[list]):
    def fetch(symbol: str, timeframe: str, since: int, limit: int) -> list[list]:
        return [r for r in rows if r[0] >= since][:limit]

    return fetch


def _funding_pages(n: int):
    rows = [{"fundingTime": int(_T0.timestamp() * 1000) + i * _FUND_MS, "fundingRate": f"{0.0001 * (1 if i % 2 else -1):.8f}"} for i in range(n)]

    def fetch(url: str) -> list[dict]:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        start = int(q["startTime"][0])
        end = int(q["endTime"][0]) if "endTime" in q else None
        lim = int(q["limit"][0])
        page = [r for r in rows if r["fundingTime"] >= start and (end is None or r["fundingTime"] <= end)]
        return page[:lim]

    return fetch


def _manager(tmp_path, **kw) -> DataManager:
    return DataManager(
        store=AltDataStore(tmp_path / "alt"),
        market_data_dir=tmp_path / "market_data",
        panel_dir=tmp_path / "panels",
        clock=lambda: _NOW,
        **kw,
    )


def test_fetch_single_source(tmp_path):
    providers = _all_fixture_providers(funding=_funding_fixture())
    mgr = _manager(tmp_path, providers=providers)
    n = mgr.fetch("funding", ["BTCUSDT"])
    assert n == 5
    far = _T0 + timedelta(days=99)
    assert len(mgr._get_store().read_asof("binance", "BTCUSDT", "funding_rate", far)) == 5


def test_fetch_unknown_source_raises(tmp_path):
    mgr = _manager(tmp_path, providers=_all_fixture_providers())
    with pytest.raises(ValueError, match="unknown source"):
        mgr.fetch("not_a_source", ["BTCUSDT"])


def test_update_delegates_to_run_once(tmp_path):
    providers = _all_fixture_providers(funding=_funding_fixture())
    mgr = _manager(tmp_path, providers=providers)
    counts = mgr.update(["BTCUSDT"])
    assert counts["funding_rate"] == 5  # run_once ran the full sweep; funding had fixture data
    assert "news_sentiment" in counts  # the full source set is present in the count dict


def test_backfill_funding_paginated(tmp_path):
    provider = BinanceFundingHistoryProvider(page_limit=500, _fetcher=_funding_pages(1650))
    mgr = _manager(tmp_path, providers=_all_fixture_providers(), funding_history=provider)
    result = mgr.backfill("funding", days=800, symbols=["BTCUSDT"])
    assert result["kind"] == "funding"
    r = result["results"]["BTCUSDT"]
    assert r.written == 1650
    assert r.span_days > 365  # >1yr depth in one call
    # Idempotent: a second backfill writes 0 new points.
    again = mgr.backfill("funding", days=800, symbols=["BTCUSDT"])
    assert again["results"]["BTCUSDT"].written == 0


def test_backfill_bars_multi_venue(tmp_path):
    rows = _bar_rows(500)
    mgr = _manager(
        tmp_path,
        providers=_all_fixture_providers(),
        bar_backfiller_factory=lambda venue: CcxtBarBackfiller(venue, page_limit=300, _fetcher=_bar_fetcher(rows)),
    )
    result = mgr.backfill("bars", days=800, symbols=["BTCUSDT"], timeframes=("1d",))
    assert result["kind"] == "bars"
    # Both default venues (binance + kraken) populated.
    for venue in ("binance", "kraken"):
        r = result["results"][(venue, "BTCUSDT", "1d")]
        assert r.written == 500
        cached = read_cached_bars(bar_cache_path(tmp_path / "market_data" / venue, "BTCUSDT", "1d"))
        assert len(cached) == 500


def test_backfill_single_venue_selector(tmp_path):
    rows = _bar_rows(100)
    mgr = _manager(
        tmp_path,
        providers=_all_fixture_providers(),
        bar_backfiller_factory=lambda venue: CcxtBarBackfiller(venue, page_limit=300, _fetcher=_bar_fetcher(rows)),
    )
    result = mgr.backfill("bars:kraken", days=400, symbols=["BTCUSDT"], timeframes=("1d",))
    assert set(result["results"].keys()) == {("kraken", "BTCUSDT", "1d")}


def test_verify_reports_have_and_missing(tmp_path):
    providers = _all_fixture_providers(funding=_funding_fixture())
    mgr = _manager(tmp_path, providers=providers)
    mgr.fetch("funding", ["BTCUSDT"])
    report = mgr.verify(["BTCUSDT"], include_bars=True)
    summary = report.summary()
    assert summary["total"] > 0
    # funding present; the many un-ingested sources show as missing.
    funding = [s for s in report.series if s.metric == "funding_rate"][0]
    assert funding.rows == 5
    assert summary["missing"] >= 1
    # Bars are included and all missing (nothing backfilled yet).
    bar_series = [s for s in report.series if s.kind == "bars"]
    assert bar_series and all(s.status == "missing" for s in bar_series)


def test_verify_no_bars_flag(tmp_path):
    mgr = _manager(tmp_path, providers=_all_fixture_providers())
    report = mgr.verify(["BTCUSDT"], include_bars=False)
    assert all(s.kind == "alt" for s in report.series)


def test_verify_covers_multiple_timeframes(tmp_path):
    mgr = _manager(tmp_path, providers=_all_fixture_providers())
    report = mgr.verify(["BTCUSDT"], timeframes=("1d", "4h", "1h"), include_bars=True)
    bar_tfs = {s.metric for s in report.series if s.kind == "bars"}
    # Every requested timeframe is reported per venue (binance + kraken), all missing (nothing backfilled).
    assert bar_tfs == {"bars:1d", "bars:4h", "bars:1h"}
    assert all(s.status == "missing" for s in report.series if s.kind == "bars")


def test_backfill_bars_multi_timeframe(tmp_path):
    rows = _bar_rows(120)
    mgr = _manager(
        tmp_path,
        providers=_all_fixture_providers(),
        bar_backfiller_factory=lambda venue: CcxtBarBackfiller(venue, page_limit=300, _fetcher=_bar_fetcher(rows)),
    )
    result = mgr.backfill("bars:binance", days=400, symbols=["BTCUSDT"], timeframes=("1d", "4h"))
    assert set(result["results"].keys()) == {("binance", "BTCUSDT", "1d"), ("binance", "BTCUSDT", "4h")}
    for tf in ("1d", "4h"):
        cached = read_cached_bars(bar_cache_path(tmp_path / "market_data" / "binance", "BTCUSDT", tf))
        assert len(cached) == 120


def test_build_panels_and_verify_panel_coverage(tmp_path):
    # Backfill bars + ingest funding, then build the ML panels and verify their coverage.
    rows = _bar_rows(60)
    mgr = _manager(
        tmp_path,
        providers=_all_fixture_providers(funding=_funding_fixture()),
        bar_backfiller_factory=lambda venue: CcxtBarBackfiller(venue, page_limit=300, _fetcher=_bar_fetcher(rows)),
    )
    mgr.backfill("bars:binance", days=400, symbols=["BTCUSDT"], timeframes=("1d",))
    mgr.fetch("funding", ["BTCUSDT"])
    written = mgr.build_panels(["BTCUSDT"], timeframes=("1d",), alt_features=("funding_rate",))
    assert written[("BTCUSDT", "1d")] == 60
    # Idempotent: a second build writes 0 new rows.
    assert mgr.build_panels(["BTCUSDT"], timeframes=("1d",), alt_features=("funding_rate",))[("BTCUSDT", "1d")] == 0
    # A symbol with no cached bars → an honest 0 (no fabricated panel).
    assert mgr.build_panels(["NOPEUSDT"], timeframes=("1d",))[("NOPEUSDT", "1d")] == 0
    # verify --panels surfaces the built panel as a non-missing series.
    report = mgr.verify(["BTCUSDT"], timeframes=("1d",), include_bars=False, include_panels=True)
    panels = [s for s in report.series if s.kind == "panel"]
    assert panels and panels[0].rows == 60 and panels[0].status != "missing"
