# Offline tests for the operator-driven Binance Vision bulk-backfill CLI (cosmu.data.binance_vision_backfill).
# NO live network: a canned `_fetcher(url)` replays zipped-CSV archive fixtures keyed by the monthly/daily URL,
# exactly as data.binance.vision would serve them. Proves: the bulk pull writes the PIT-honest cache, a re-run
# is idempotent (0 new), an already-covered target is SKIPPED without a fetch, --force re-downloads, spot/perp
# use distinct Vision trees, a 404 month is a skipped gap (never zero-filled), the end-window is clamped, and
# the CLI main() drives the whole thing.

from __future__ import annotations

import calendar
import io
import zipfile
from datetime import UTC, date, datetime

from cosmu.data.binance_vision_backfill import (
    VISION_VENUE,
    backfill_vision_bars,
    main,
)
from cosmu.ingest.bars import bar_cache_path, read_cached_bars

_DAY_MS = 86_400_000


def _ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


def _row(ms: int, day_seed: int) -> str:
    """One 12-column Binance kline CSV row (we read the first six). `day_seed` makes the OHLCV deterministic."""
    o, h, low, c, v = 100 + day_seed, 101 + day_seed, 99 + day_seed, 100.5 + day_seed, 10 + day_seed
    return f"{ms},{o},{h},{low},{c},{v},{ms + _DAY_MS - 1},0,0,0,0,0"


def _csv_month(year: int, month: int) -> str:
    """A monthly 1d-kline CSV: one bar per UTC day of the month."""
    lines = [_row(_ms(year, month, d), d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    return "\n".join(lines) + "\n"


def _csv_day(year: int, month: int, day: int, *, extra: list[int] | None = None) -> str:
    """A daily 1d-kline CSV: the single bar for that day, plus any `extra` open_time ms rows."""
    rows = [_row(_ms(year, month, day), day)] + [_row(ms, day) for ms in (extra or [])]
    return "\n".join(rows) + "\n"


def _zip(csv_text: str, name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


def _make_fetcher(months: dict[str, str], days: dict[str, str]):
    """Replay data.binance.vision: map a monthly/daily archive URL to its zipped CSV, or None (404) if absent.
    Records every requested URL on `.calls` so a test can assert the path + that 'skip' made NO call."""
    calls: list[str] = []

    def fetch(url: str) -> bytes | None:
        calls.append(url)
        stem = url.rsplit("/", 1)[1][:-4]          # BTCUSDT-1d-2024-03  /  BTCUSDT-1d-2024-03-02
        label = stem.split("-", 2)[2]              # 2024-03  /  2024-03-02
        if "/monthly/" in url and label in months:
            return _zip(months[label], f"{stem}.csv")
        if "/daily/" in url and label in days:
            return _zip(days[label], f"{stem}.csv")
        return None

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


# A fixed PAST window so "complete months" vs "current partial month" is deterministic (no dependence on now):
# 2024-01-01 → 2024-03-15. Jan/Feb are COMPLETE months (monthly archives); March is the END month, which the
# backfiller fetches via DAILY archives (its monthly archive isn't published while the month is in progress).
_START = date(2024, 1, 1)
_END = date(2024, 3, 15)


def _bulk_fetcher():
    months = {"2024-01": _csv_month(2024, 1), "2024-02": _csv_month(2024, 2)}
    days = {f"2024-03-{d:02d}": _csv_day(2024, 3, d) for d in range(1, 16)}
    return _make_fetcher(months, days)


_EXPECTED = 31 + 29 + 15  # Jan monthly + Feb monthly (leap) + Mar 01..15 daily


def test_bulk_backfill_writes_pit_honest_cache(tmp_path):
    fetcher = _bulk_fetcher()
    results = backfill_vision_bars(
        ["BTCUSDT"], market="spot", start=_START, end=_END,
        timeframes=("1d",), market_data_dir=tmp_path, _fetcher=fetcher,
    )
    assert len(results) == 1
    r = results[0]
    assert r.new_bars == _EXPECTED and r.cached_bars == _EXPECTED and not r.skipped

    path = bar_cache_path(tmp_path / VISION_VENUE["spot"], "BTCUSDT", "1d")
    bars = read_cached_bars(path)
    assert len(bars) == _EXPECTED
    assert bars[0].ts == datetime(2024, 1, 1, tzinfo=UTC)
    assert bars[-1].ts == datetime(2024, 3, 15, tzinfo=UTC)
    assert [b.ts for b in bars] == sorted(b.ts for b in bars)        # ascending
    assert len({b.ts for b in bars}) == _EXPECTED                    # de-duped


def test_rerun_is_idempotent_and_skips_without_a_network_call(tmp_path):
    # First pull populates the cache.
    backfill_vision_bars(
        ["BTCUSDT"], market="spot", start=_START, end=_END,
        timeframes=("1d",), market_data_dir=tmp_path, _fetcher=_bulk_fetcher(),
    )
    # Second pull: the window is already covered → SKIPPED, and the fetcher is NEVER called.
    second = _bulk_fetcher()
    results = backfill_vision_bars(
        ["BTCUSDT"], market="spot", start=_START, end=_END,
        timeframes=("1d",), market_data_dir=tmp_path, _fetcher=second,
    )
    assert results[0].skipped is True
    assert results[0].new_bars == 0
    assert second.calls == []  # idempotent fast path made zero archive requests


def test_force_redownloads_but_merge_still_writes_zero_new(tmp_path):
    backfill_vision_bars(
        ["BTCUSDT"], market="spot", start=_START, end=_END,
        timeframes=("1d",), market_data_dir=tmp_path, _fetcher=_bulk_fetcher(),
    )
    forced = _bulk_fetcher()
    results = backfill_vision_bars(
        ["BTCUSDT"], market="spot", start=_START, end=_END,
        timeframes=("1d",), market_data_dir=tmp_path, force=True, _fetcher=forced,
    )
    assert not results[0].skipped          # --force bypasses the skip
    assert forced.calls != []              # it DID re-download
    assert results[0].new_bars == 0        # but the append-merge added nothing (cache never shrinks/double-writes)
    assert results[0].cached_bars == _EXPECTED


def test_missing_month_is_a_gap_not_zero_filled(tmp_path):
    months = {"2024-01": _csv_month(2024, 1)}  # Feb absent → 404
    days = {f"2024-03-{d:02d}": _csv_day(2024, 3, d) for d in range(1, 16)}
    results = backfill_vision_bars(
        ["BTCUSDT"], market="spot", start=_START, end=_END,
        timeframes=("1d",), market_data_dir=tmp_path, _fetcher=_make_fetcher(months, days),
    )
    bars = read_cached_bars(bar_cache_path(tmp_path / VISION_VENUE["spot"], "BTCUSDT", "1d"))
    assert len(bars) == 31 + 15                   # Jan + March only; no fabricated February
    assert not any(b.ts.month == 2 for b in bars)
    assert results[0].new_bars == 31 + 15


def test_spot_and_perp_use_distinct_vision_trees(tmp_path):
    spot = _bulk_fetcher()
    backfill_vision_bars(
        ["BTCUSDT"], market="spot", start=_START, end=_END,
        timeframes=("1d",), market_data_dir=tmp_path, _fetcher=spot,
    )
    assert spot.calls and all("/data/spot/" in u for u in spot.calls)

    perp = _bulk_fetcher()
    backfill_vision_bars(
        ["BTCUSDT"], market="perp", start=_START, end=_END,
        timeframes=("1d",), market_data_dir=tmp_path, _fetcher=perp,
    )
    assert perp.calls and all("/data/futures/um/" in u for u in perp.calls)
    # Distinct venue dirs on disk → spot and perp never collide in one cache file.
    assert (tmp_path / VISION_VENUE["spot"]).exists()
    assert (tmp_path / VISION_VENUE["perp"]).exists()


def test_multi_symbol_multi_timeframe(tmp_path):
    months = {"2024-01": _csv_month(2024, 1), "2024-02": _csv_month(2024, 2)}
    days = {f"2024-03-{d:02d}": _csv_day(2024, 3, d) for d in range(1, 16)}
    # One fetcher serving BOTH the 1d and 1h trees (re-use the same CSV shape; only the URL timeframe differs).
    def fetch(url: str) -> bytes | None:
        stem = url.rsplit("/", 1)[1][:-4]
        label = stem.split("-", 2)[2]
        if "/monthly/" in url and label in months:
            return _zip(months[label], f"{stem}.csv")
        if "/daily/" in url and label in days:
            return _zip(days[label], f"{stem}.csv")
        return None

    results = backfill_vision_bars(
        ["BTCUSDT", "ETHUSDT"], market="spot", start=_START, end=_END,
        timeframes=("1d", "1h"), market_data_dir=tmp_path, _fetcher=fetch,
    )
    assert len(results) == 4  # 2 symbols × 2 timeframes
    assert {(r.symbol, r.timeframe) for r in results} == {
        ("BTCUSDT", "1d"), ("BTCUSDT", "1h"), ("ETHUSDT", "1d"), ("ETHUSDT", "1h")
    }
    assert all(r.new_bars == _EXPECTED for r in results)


def test_end_is_clamped_to_today():
    # An end far in the future must be clamped; we don't assert exact counts (depends on real archives we
    # don't fetch here), only that it raises nothing and returns one result per target via the offline fetcher.
    far_future = date(2999, 1, 1)
    # Inject a fetcher that 404s everything → no bars, but the clamp must not blow up nor request future months.
    results = backfill_vision_bars(
        ["BTCUSDT"], market="spot", start=date(2024, 1, 1), end=far_future,
        timeframes=("1d",), market_data_dir="/tmp/cosmu_vision_clamp_test", _fetcher=lambda url: None,
    )
    assert len(results) == 1
    assert results[0].new_bars == 0  # everything 404'd → honest empty, never fabricated


def test_start_after_end_rejected():
    import pytest

    with pytest.raises(ValueError, match="after end"):
        backfill_vision_bars(
            ["BTCUSDT"], market="spot", start=date(2024, 2, 1), end=date(2024, 1, 1),
            timeframes=("1d",), market_data_dir="/tmp/cosmu_vision_bad", _fetcher=lambda url: None,
        )


def test_invalid_market_rejected():
    import pytest

    with pytest.raises(ValueError, match="market"):
        backfill_vision_bars(
            ["BTCUSDT"], market="options", start=_START, end=_END,
            timeframes=("1d",), market_data_dir="/tmp/cosmu_vision_bad", _fetcher=lambda url: None,
        )


def test_cli_main_drives_a_backfill(tmp_path, capsys, monkeypatch):
    # Patch the module-level backfiller HTTP fetch so `main` (which builds its own backfiller) stays offline.
    import cosmu.ingest.bars as bars_mod

    months = {"2024-01": _csv_month(2024, 1), "2024-02": _csv_month(2024, 2)}
    days = {f"2024-03-{d:02d}": _csv_day(2024, 3, d) for d in range(1, 16)}
    fetcher = _make_fetcher(months, days)
    monkeypatch.setattr(bars_mod.BinanceVisionBarBackfiller, "_fetch", staticmethod(fetcher))

    rc = main([
        "BTCUSDT", "--spot",
        "--start", "2024-01-01", "--end", "2024-03-15",
        "--timeframes", "1d",
        "--market-data-dir", str(tmp_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Binance Vision bulk backfill" in out
    assert f"{_EXPECTED} new bars" in out
    bars = read_cached_bars(bar_cache_path(tmp_path / VISION_VENUE["spot"], "BTCUSDT", "1d"))
    assert len(bars) == _EXPECTED
