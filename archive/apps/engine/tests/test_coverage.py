# Offline tests for the data-quality / VERIFY engine (ingest/coverage.py). PURE + deterministic: the clock
# is injected, no network, no wall-time. Exercises rows/span/freshness, gap detection, the look-ahead
# integrity check, and the "missing" verdict for a series the store has no rows for.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataPoint, AltDataStore
from cosmu.ingest.coverage import (
    CoverageReport,
    bar_coverage,
    build_alt_coverage,
    series_coverage,
)
from cosmu.ingest.bars import Bar, bar_cache_path, read_cached_bars, write_bars_cache
from decimal import Decimal

_T0 = datetime(2023, 1, 1, tzinfo=UTC)
_NOW = _T0 + timedelta(days=40)


def _daily(n: int, *, lag_days: int = 1, start: datetime = _T0) -> list[AltDataPoint]:
    return [
        AltDataPoint(ts=start + timedelta(days=i), available_at=start + timedelta(days=i + lag_days), value=float(i))
        for i in range(n)
    ]


def test_ok_series_is_fresh_dense_and_clean():
    pts = _daily(39, start=_NOW - timedelta(days=39))  # last point ~yesterday → fresh
    cov = series_coverage(pts, provider="binance", symbol="BTCUSDT", metric="funding_rate", now=_NOW)
    assert cov.rows == 39
    assert cov.status == "ok"
    assert cov.lookahead_violations == 0
    assert cov.gaps == 0
    assert abs(cov.cadence_seconds - 86400) < 1


def test_missing_series_when_no_rows():
    cov = series_coverage([], provider="fred", symbol="MARKET", metric="macro_regime", now=_NOW)
    assert cov.rows == 0
    assert cov.status == "missing"
    assert cov.first_ts is None and cov.last_ts is None


def test_stale_series_flagged():
    pts = _daily(10, start=_T0)  # last available_at ~ _T0+10d, but now is _T0+40d → ~30d old
    cov = series_coverage(pts, provider="cboe", symbol="MARKET", metric="putcall_ratio", now=_NOW)
    assert cov.status == "stale"
    assert cov.freshness_seconds > 3 * 86400


def test_gap_detection():
    early = _daily(10, start=_T0)
    late = _daily(10, start=_T0 + timedelta(days=25))  # a ~15-day hole in the middle
    cov = series_coverage(early + late, provider="binance", symbol="BTCUSDT", metric="open_interest", now=_T0 + timedelta(days=36))
    assert cov.gaps >= 1
    assert cov.missing_buckets >= 10
    assert cov.status in ("gappy", "stale")  # the hole is the point; freshness depends on `now`


def test_lookahead_violation_detected():
    good = _daily(5, start=_NOW - timedelta(days=5))
    leak = AltDataPoint(ts=_NOW - timedelta(days=1), available_at=_NOW - timedelta(days=3), value=9.0)  # avail < ts
    cov = series_coverage(good + [leak], provider="x", symbol="BTCUSDT", metric="some_metric", now=_NOW)
    assert cov.lookahead_violations == 1
    assert cov.status == "lookahead"  # a point-in-time leak outranks freshness/gaps


def test_revisions_collapse_to_one_observation_per_ts():
    ts = _NOW - timedelta(days=2)
    v1 = AltDataPoint(ts=ts, available_at=ts, value=1.0)
    v2 = AltDataPoint(ts=ts, available_at=ts + timedelta(hours=6), value=2.0)  # a later revision of the SAME ts
    cov = series_coverage([v1, v2], provider="news", symbol="BTCUSDT", metric="news_sentiment", now=_NOW)
    assert cov.rows == 1  # revisions are not double-counted as observations


def test_build_alt_coverage_reports_have_and_missing(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    store.append("binance", "BTCUSDT", "funding_rate", _daily(20, start=_NOW - timedelta(days=20)))
    specs = [
        ("binance", "BTCUSDT", "funding_rate"),  # present
        ("fred", "MARKET", "macro_regime"),       # absent → missing
    ]
    series = build_alt_coverage(store, specs, now=_NOW)
    report = CoverageReport(generated_at=_NOW, series=series)
    summary = report.summary()
    assert summary["total"] == 2
    assert summary["missing"] == 1
    assert summary["ok"] == 1
    text = report.to_text()
    assert "what we have / what's stale / what's missing" in text
    assert "macro_regime" in text
    # JSON shape is stable for tooling.
    d = report.to_dict()
    assert d["summary"]["total"] == 2
    assert {s["metric"] for s in d["series"]} == {"funding_rate", "macro_regime"}


def test_bar_coverage_from_cache(tmp_path):
    bars = [
        Bar(ts=_NOW - timedelta(days=i), open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"))
        for i in range(10)
    ]
    path = bar_cache_path(tmp_path / "binance", "BTCUSDT", "1d")
    write_bars_cache(path, bars)
    cov = bar_coverage(read_cached_bars(path), venue="binance", symbol="BTCUSDT", timeframe="1d", now=_NOW)
    assert cov.kind == "bars"
    assert cov.rows == 10
    assert cov.lookahead_violations == 0  # bars carry no available_at axis
    assert cov.status == "ok"
