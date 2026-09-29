# Offline tests for the keyless BULK bar backfill from Binance Vision (BinanceVisionBarBackfiller) + the
# Vision-bulk / ccxt-tail composite (BulkTailBarBackfiller). NO live network: a canned `_fetcher(url)` replays
# zipped-CSV archive fixtures keyed by the monthly/daily URL, exactly as data.binance.vision would serve them.

from __future__ import annotations

import calendar
import io
import zipfile
from datetime import UTC, datetime

from cosmu.ingest.bars import (
    BinanceVisionBarBackfiller,
    BulkTailBarBackfiller,
    bar_cache_path,
    read_cached_bars,
    write_bars_cache,
)

_DAY_MS = 86_400_000


def _ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


def _row(ms: int, day_seed: int, *, micros: bool = False) -> str:
    """One 12-column Binance kline CSV row (we only read the first six). `day_seed` makes the OHLCV deterministic
    so a parsed bar is identifiable. `micros` stamps open_time in microseconds (the 2025+ Vision quirk)."""
    ts = ms * 1000 if micros else ms
    o, h, low, c, v = 100 + day_seed, 101 + day_seed, 99 + day_seed, 100.5 + day_seed, 10 + day_seed
    return f"{ts},{o},{h},{low},{c},{v},{ms + _DAY_MS - 1},0,0,0,0,0"


def _csv_month(year: int, month: int, *, micros: bool = False, header: bool = False) -> str:
    """A monthly 1d-kline CSV: one bar per UTC day of the month (what `<SYM>-1d-<YYYY-MM>.zip` holds)."""
    lines = ["open_time,open,high,low,close,volume,close_time,qv,n,tbb,tbq,ignore"] if header else []
    for d in range(1, calendar.monthrange(year, month)[1] + 1):
        lines.append(_row(_ms(year, month, d), d, micros=micros))
    return "\n".join(lines) + "\n"


def _csv_day(year: int, month: int, day: int, *, extra: list[int] | None = None) -> str:
    """A daily 1d-kline CSV: the single bar for that day (what `<SYM>-1d-<YYYY-MM-DD>.zip` holds), plus any
    `extra` open_time ms rows (used to prove the end-of-window filter drops bars past `end_ms`)."""
    rows = [_row(_ms(year, month, day), day)]
    for ms in extra or []:
        rows.append(_row(ms, day))
    return "\n".join(rows) + "\n"


def _zip(csv_text: str, name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


def _make_fetcher(months: dict[str, str], days: dict[str, str]):
    """Replay data.binance.vision: map a monthly/daily archive URL to its zipped CSV, or None (404) if absent.
    Records every requested URL on `.calls` so a test can assert the spot/perp path + which months were hit."""
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


# A fixed past window so "complete months" vs "current partial month" is deterministic (no dependence on now):
# 2024-01-01 → 2024-03-15. Months Jan/Feb are complete (monthly archives); March is the current month (daily).
_START = _ms(2024, 1, 1)
_END = _ms(2024, 3, 15)


def _full_fixture(**month_kw):
    months = {"2024-01": _csv_month(2024, 1, **month_kw), "2024-02": _csv_month(2024, 2)}
    days = {f"2024-03-{d:02d}": _csv_day(2024, 3, d) for d in range(1, 16)}
    return _make_fetcher(months, days)


def test_archive_to_bars_then_idempotent_write(tmp_path):
    # archive → parse → write_bars_cache yields the expected bars, and a re-run writes 0 (the core contract).
    fetcher = _full_fixture()
    prov = BinanceVisionBarBackfiller("spot", _fetcher=fetcher)
    bars = prov.fetch_history("BTCUSDT", "1d", start_ms=_START, end_ms=_END)

    expected = 31 + 29 + 15  # Jan monthly + Feb monthly (leap year) + Mar 01..15 daily
    assert len(bars) == expected
    assert [b.ts for b in bars] == sorted(b.ts for b in bars)        # ascending
    assert len({b.ts for b in bars}) == expected                     # de-duped on ts
    assert bars[0].ts == datetime(2024, 1, 1, tzinfo=UTC)
    assert bars[-1].ts == datetime(2024, 3, 15, tzinfo=UTC)

    path = bar_cache_path(tmp_path / "binance", "BTCUSDT", "1d")
    assert write_bars_cache(path, bars) == expected
    assert len(read_cached_bars(path)) == expected
    # Re-run the WHOLE pull and re-merge: idempotent → 0 new bars.
    rerun = BinanceVisionBarBackfiller("spot", _fetcher=_full_fixture()).fetch_history(
        "BTCUSDT", "1d", start_ms=_START, end_ms=_END
    )
    assert write_bars_cache(path, rerun) == 0
    assert len(read_cached_bars(path)) == expected


def test_microsecond_open_time_is_normalized_to_ms():
    # Some 2025+ Vision archives stamp open_time in microseconds; the bars must still land on the right ms day.
    prov = BinanceVisionBarBackfiller("spot", _fetcher=_full_fixture(micros=True))
    bars = prov.fetch_history("BTCUSDT", "1d", start_ms=_START, end_ms=_END)
    assert bars[0].ts == datetime(2024, 1, 1, tzinfo=UTC)
    assert bars[30].ts == datetime(2024, 1, 31, tzinfo=UTC)  # last Jan bar, not a year-33000 timestamp


def test_header_row_is_skipped():
    # A leading `open_time,...` header row (newer archives include one) must not become a bar.
    prov = BinanceVisionBarBackfiller("spot", _fetcher=_full_fixture(header=True))
    bars = prov.fetch_history("BTCUSDT", "1d", start_ms=_START, end_ms=_END)
    assert len(bars) == 31 + 29 + 15  # header skipped → same count as the no-header fixture


def test_missing_month_is_a_gap_not_zero_filled():
    # A 404 on an early month (listing started later) is skipped, never zero-filled — the rest still loads.
    months = {"2024-01": _csv_month(2024, 1)}  # Feb absent → 404
    days = {f"2024-03-{d:02d}": _csv_day(2024, 3, d) for d in range(1, 16)}
    prov = BinanceVisionBarBackfiller("spot", _fetcher=_make_fetcher(months, days))
    bars = prov.fetch_history("BTCUSDT", "1d", start_ms=_START, end_ms=_END)
    assert len(bars) == 31 + 15  # Jan + March only; no fabricated February
    assert not any(b.ts.month == 2 for b in bars)


def test_excludes_bars_after_end():
    # A bar past end_ms (a future/out-of-window row inside an archive) is dropped — never a future ts.
    months = {"2024-01": _csv_month(2024, 1), "2024-02": _csv_month(2024, 2)}
    days = {f"2024-03-{d:02d}": _csv_day(2024, 3, d) for d in range(1, 15)}
    # The last in-window day carries an extra row 12h past end → must be filtered out.
    days["2024-03-15"] = _csv_day(2024, 3, 15, extra=[_END + _DAY_MS // 2])
    prov = BinanceVisionBarBackfiller("spot", _fetcher=_make_fetcher(months, days))
    bars = prov.fetch_history("BTCUSDT", "1d", start_ms=_START, end_ms=_END)
    assert bars[-1].ts == datetime(2024, 3, 15, tzinfo=UTC)        # the 12h-late row was excluded
    assert max(int(b.ts.timestamp() * 1000) for b in bars) <= _END


def test_spot_and_perp_use_distinct_vision_trees():
    spot = _full_fixture()
    BinanceVisionBarBackfiller("spot", _fetcher=spot).fetch_history("BTCUSDT", "1d", start_ms=_START, end_ms=_END)
    assert all("/data/spot/" in u for u in spot.calls)
    assert any("/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01.zip" in u for u in spot.calls)

    perp = _full_fixture()
    BinanceVisionBarBackfiller("perp", _fetcher=perp).fetch_history("BTCUSDT", "1d", start_ms=_START, end_ms=_END)
    assert all("/data/futures/um/" in u for u in perp.calls)


def test_invalid_market_rejected():
    import pytest

    with pytest.raises(ValueError, match="market"):
        BinanceVisionBarBackfiller("options")


class _StubTail:
    """A canned recent-tail backfiller: returns bars for the ts list it was given, recording the start_ms it was
    asked to resume from (so the test can prove the tail resumes near the last bulk bar)."""

    def __init__(self, ts_list: list[int]) -> None:
        self._ts = ts_list
        self.seen_start: int | None = None

    def fetch_history(self, symbol, timeframe, *, start_ms, end_ms=None):
        from cosmu.ingest.bars import _bar_from_ccxt

        self.seen_start = start_ms
        return [_bar_from_ccxt([ts, 1, 1, 1, 1, 1]) for ts in self._ts if ts >= start_ms]


def test_bulk_tail_composite_merges_and_resumes_after_bulk():
    # Bulk = Vision (Jan/Feb/Mar fixture); tail = the next few days Vision hasn't archived yet.
    bulk = BinanceVisionBarBackfiller("spot", _fetcher=_full_fixture())
    tail = _StubTail([_ms(2024, 3, 15), _ms(2024, 3, 16), _ms(2024, 3, 17)])  # incl. an overlap with bulk's last
    comp = BulkTailBarBackfiller(bulk, tail)
    bars = comp.fetch_history("BTCUSDT", "1d", start_ms=_START, end_ms=_END)

    # Tail resumed within one step of the last bulk bar (no boundary gap), not from _START.
    assert tail.seen_start is not None and tail.seen_start >= _ms(2024, 3, 15) - _DAY_MS
    # Bulk (75) + the two genuinely-new tail days (03-16, 03-17); the overlapping 03-15 is deduped, bulk wins.
    assert len(bars) == 31 + 29 + 15 + 2
    assert bars[-1].ts == datetime(2024, 3, 17, tzinfo=UTC)
    assert [b.ts for b in bars] == sorted(b.ts for b in bars)
