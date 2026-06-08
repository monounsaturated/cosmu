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
from cosmu.ingest import catalog
from cosmu.ingest.bars import CcxtBarBackfiller, bar_cache_path, read_cached_bars
from cosmu.ingest.manage import DataManager, _main
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


# ---------------------------------------------------------------------------
# update_deep — best-effort full backfill of ALL catalog sources
# ---------------------------------------------------------------------------


def test_update_deep_returns_per_source_summary(tmp_path):
    """update_deep returns a {source: 'OK...' | 'FAIL:...'} dict with an entry for every catalog source
    plus bars. Best-effort: a provider that always raises never aborts the run."""
    provider = BinanceFundingHistoryProvider(page_limit=500, _fetcher=_funding_pages(10))
    rows = _bar_rows(5)
    mgr = _manager(
        tmp_path,
        providers=_all_fixture_providers(funding=_funding_fixture()),
        funding_history=provider,
        bar_backfiller_factory=lambda venue: CcxtBarBackfiller(venue, page_limit=300, _fetcher=_bar_fetcher(rows)),
    )
    summary = mgr.update_deep(["BTCUSDT"], days=400, timeframes=("1d",))
    # bars and funding must be present
    assert "bars" in summary
    assert "funding" in summary
    # every catalog source must appear
    for name in catalog.managed_sources():
        assert name in summary, f"missing: {name}"
    # bars succeeded (fixture provides rows)
    assert summary["bars"].startswith("OK")
    # funding succeeded
    assert summary["funding"].startswith("OK")


def test_update_deep_best_effort_on_failure(tmp_path):
    """A provider that always raises must produce FAIL in the summary but NOT abort the whole run."""

    class _BoomProvider:
        def fetch(self, *a, **kw):
            raise RuntimeError("network down")

        # Providers checks for attribute existence; add all needed attrs to satisfy Providers(**base).
        def fetch_numeric(self, *a, **kw):
            raise RuntimeError("network down")

        def fetch_market_wide(self, *a, **kw):
            raise RuntimeError("network down")

    # The funding provider raises; all other sources are empty fixtures.
    class _BoomFundingHistory:
        def fetch(self, *a, **kw):
            raise RuntimeError("history down")

    rows = _bar_rows(5)
    mgr = _manager(
        tmp_path,
        providers=_all_fixture_providers(),
        funding_history=_BoomFundingHistory(),
        bar_backfiller_factory=lambda venue: CcxtBarBackfiller(venue, page_limit=300, _fetcher=_bar_fetcher(rows)),
    )
    summary = mgr.update_deep(["BTCUSDT"], days=400, timeframes=("1d",))
    # bars OK (fixture backfiller works), funding FAIL (history provider raises)
    assert summary["bars"].startswith("OK")
    assert summary["funding"].startswith("FAIL")
    # rest of the alt sources are present (they might be OK with empty fixture providers)
    assert len(summary) >= 2


def test_update_deep_idempotent(tmp_path):
    """Running update_deep twice should produce 0 new rows on the second pass."""
    provider = BinanceFundingHistoryProvider(page_limit=500, _fetcher=_funding_pages(20))
    rows = _bar_rows(10)
    mgr = _manager(
        tmp_path,
        providers=_all_fixture_providers(funding=_funding_fixture()),
        funding_history=provider,
        bar_backfiller_factory=lambda venue: CcxtBarBackfiller(venue, page_limit=300, _fetcher=_bar_fetcher(rows)),
    )
    first = mgr.update_deep(["BTCUSDT"], days=400, timeframes=("1d",))
    second = mgr.update_deep(["BTCUSDT"], days=400, timeframes=("1d",))
    # bars: second run writes 0 new rows
    assert "0 new rows" in second["bars"]
    # funding: second run writes 0 new rows
    assert "0 new rows" in second["funding"]


# ---------------------------------------------------------------------------
# catalog SourceSpec flags
# ---------------------------------------------------------------------------


def test_source_spec_key_gated_flag():
    """Sources known to require an API key must have key_gated=True."""
    sources = catalog.managed_sources()
    for name in ("lunarcrush", "xai", "llm_index", "reddit_volume", "cryptopanic"):
        assert sources[name].key_gated, f"{name} should be key_gated=True"


def test_source_spec_non_causal_flag():
    """Non-causal orthogonality controls must be flagged."""
    sources = catalog.managed_sources()
    for name in ("astro", "weather", "exotic_controls"):
        assert sources[name].non_causal, f"{name} should be non_causal=True"


def test_source_spec_causal_sources_not_flagged():
    """High-signal causal sources must NOT be flagged as non-causal."""
    sources = catalog.managed_sources()
    for name in ("funding", "news", "macro", "lunarcrush"):
        assert not sources[name].non_causal, f"{name} should not be non_causal"


# ---------------------------------------------------------------------------
# CLI: manage sources + manage update --deep (via _main)
# ---------------------------------------------------------------------------


def test_cli_sources_prints_table(capsys):
    """manage sources must print every catalog source with key-gated / non-causal columns."""
    rc = _main(["sources"])
    assert rc == 0
    out = capsys.readouterr().out
    # Header
    assert "key-gated" in out
    assert "non-causal" in out
    # Every source name appears
    for name in catalog.managed_sources():
        assert name in out, f"source {name!r} missing from 'sources' output"
    # Known flags are present in the output
    assert "yes" in out  # at least one key-gated / non-causal source


def test_cli_update_deep_flag(tmp_path, capsys, monkeypatch):
    """manage update --deep must complete without error and print OK/FAIL summary header."""
    rows = _bar_rows(5)
    provider = BinanceFundingHistoryProvider(page_limit=500, _fetcher=_funding_pages(10))

    def _make_manager(**_kw):
        return _manager(
            tmp_path,
            providers=_all_fixture_providers(funding=_funding_fixture()),
            funding_history=provider,
            bar_backfiller_factory=lambda venue: CcxtBarBackfiller(venue, page_limit=300, _fetcher=_bar_fetcher(rows)),
        )

    monkeypatch.setattr("cosmu.ingest.manage.DataManager", _make_manager)
    monkeypatch.setattr("cosmu.ingest.manage._symbols", lambda _: ["BTCUSDT"])
    rc = _main(["update", "--deep", "--symbols", "BTCUSDT", "--timeframe", "1d"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DEEP UPDATE" in out
    assert "OK" in out
