# Offline tests for the 1m intraday Binance Vision fetcher (IntradayBinanceVisionCache / fetch_1m_bars).
# NO live network: a canned `_fetcher(url)` replays zipped-CSV archive fixtures keyed by the
# monthly/daily Vision URL, exactly as data.binance.vision would serve them. Tests cover:
#   - basic fetch + cache round-trip (idempotent: second call writes 0 new bars)
#   - gap days skipped, never zero-filled
#   - future end date clamped to today
#   - _slice window filter is tight (no bars outside [start_ms, end_ms])
#   - market="perp" hits the right URL tree

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime

import pytest

from cosmu.data.intraday_binance_vision import IntradayBinanceVisionCache, fetch_1m_bars

_MIN_MS = 60_000  # 1 minute in ms
_DAY_BARS = 24 * 60  # 1440 bars per full UTC day of 1m klines


def _ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp() * 1000)


def _1m_row(ts_ms: int, seed: int = 1) -> str:
    """One 12-column Binance 1m kline CSV row. `seed` varies OHLCV so bars are identifiable."""
    o, h, lo, c, v = 100 + seed, 101 + seed, 99 + seed, 100.5 + seed, 10 + seed
    close_time = ts_ms + _MIN_MS - 1
    return f"{ts_ms},{o},{h},{lo},{c},{v},{close_time},0,0,0,0,0"


def _csv_for_day(year: int, month: int, day: int) -> str:
    """All 1440 1m bars for a UTC day as a Binance kline CSV."""
    lines: list[str] = []
    base = _ms(year, month, day)
    for i in range(_DAY_BARS):
        lines.append(_1m_row(base + i * _MIN_MS, seed=i % 100))
    return "\n".join(lines) + "\n"


def _zip(csv_text: str, name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


def _make_fetcher(day_map: dict[str, bytes]):
    """Replay Binance Vision: return the zipped bytes for a URL whose YYYY-MM-DD label is in `day_map`,
    or None (404) otherwise. Records all requested URLs on `.calls`."""
    calls: list[str] = []

    def fetch(url: str) -> bytes | None:
        calls.append(url)
        # URL shape: .../daily/klines/BTCUSDT/1m/BTCUSDT-1m-YYYY-MM-DD.zip
        stem = url.rsplit("/", 1)[1][:-4]   # BTCUSDT-1m-2024-01-02
        parts = stem.split("-", 2)          # ["BTCUSDT", "1m", "2024-01-02"]
        label = parts[2] if len(parts) == 3 else ""
        return day_map.get(label)

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def _fixture_map(*days: tuple[int, int, int]) -> dict[str, bytes]:
    """Build day_map for given (year, month, day) tuples."""
    out: dict[str, bytes] = {}
    for y, m, d in days:
        label = f"{y:04d}-{m:02d}-{d:02d}"
        stem = f"BTCUSDT-1m-{label}"
        out[label] = _zip(_csv_for_day(y, m, d), f"{stem}.csv")
    return out


# ---------------------------------------------------------------------------
# Core fetch + cache round-trip
# ---------------------------------------------------------------------------


def test_fetch_and_cache_idempotent(tmp_path):
    """First call fetches from Vision and caches; second call uses the cache (0 new network bytes)."""
    day_map = _fixture_map((2024, 1, 1), (2024, 1, 2), (2024, 1, 3))
    fetcher = _make_fetcher(day_map)
    cache = IntradayBinanceVisionCache(tmp_path / "cache", _fetcher=fetcher)

    bars = cache.fetch("BTCUSDT", date(2024, 1, 1), date(2024, 1, 3))

    assert len(bars) == _DAY_BARS * 3
    assert bars == sorted(bars, key=lambda b: b.ts)      # ascending
    assert len({b.ts for b in bars}) == len(bars)         # de-duped
    assert bars[0].ts == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    assert bars[-1].ts == datetime(2024, 1, 3, 23, 59, tzinfo=UTC)

    # Second call — coverage threshold already met, no new network calls.
    calls_before = len(fetcher.calls)
    bars2 = cache.fetch("BTCUSDT", date(2024, 1, 1), date(2024, 1, 3))
    assert len(fetcher.calls) == calls_before  # no additional fetches
    assert len(bars2) == len(bars)


def test_fetch_1m_bars_convenience_wrapper(tmp_path):
    """fetch_1m_bars is a thin wrapper over IntradayBinanceVisionCache — same result, different entry point."""
    day_map = _fixture_map((2024, 2, 5), (2024, 2, 6))
    fetcher = _make_fetcher(day_map)

    bars = fetch_1m_bars(
        "BTCUSDT", date(2024, 2, 5), date(2024, 2, 6),
        cache_dir=tmp_path / "via_fn", _fetcher=fetcher,
    )

    assert len(bars) == _DAY_BARS * 2
    assert bars[0].ts.date() == date(2024, 2, 5)
    assert bars[-1].ts.date() == date(2024, 2, 6)


# ---------------------------------------------------------------------------
# Gap / missing-day honesty
# ---------------------------------------------------------------------------


def test_missing_day_is_gap_not_zero_filled(tmp_path):
    """A 404 on a day (Vision doesn't have it) must be skipped, never zero-filled."""
    # Only Jan 1 and Jan 3 are in the fixture; Jan 2 is absent (404).
    day_map = _fixture_map((2024, 1, 1), (2024, 1, 3))
    cache = IntradayBinanceVisionCache(tmp_path / "cache", _fetcher=_make_fetcher(day_map))

    bars = cache.fetch("BTCUSDT", date(2024, 1, 1), date(2024, 1, 3))

    assert len(bars) == _DAY_BARS * 2  # only Jan 1 and Jan 3
    assert not any(b.ts.day == 2 for b in bars)    # no fabricated Jan 2 bars


# ---------------------------------------------------------------------------
# Window filter tightness
# ---------------------------------------------------------------------------


def test_bars_within_window_only(tmp_path):
    """Only bars whose open_time is within [start_ms, end_ms] are returned."""
    # We have Jan 1, 2, 3 but ask for Jan 2 only — Jan 1 and Jan 3 bars must not appear.
    day_map = _fixture_map((2024, 1, 1), (2024, 1, 2), (2024, 1, 3))
    cache = IntradayBinanceVisionCache(tmp_path / "cache", _fetcher=_make_fetcher(day_map))

    bars = cache.fetch("BTCUSDT", date(2024, 1, 2), date(2024, 1, 2))

    assert len(bars) == _DAY_BARS
    assert all(b.ts.date() == date(2024, 1, 2) for b in bars)


# ---------------------------------------------------------------------------
# Future-date clamping
# ---------------------------------------------------------------------------


def test_future_end_date_clamped_to_today(tmp_path):
    """Requesting an end date in the future is silently clamped to today; no future bars are emitted."""
    from datetime import date as _date
    today = datetime.now(UTC).date()
    future_end = _date(today.year + 1, 1, 1)

    # We provide no fixture — if the fetcher were called it would get no bars (all 404s).
    cache = IntradayBinanceVisionCache(tmp_path / "cache", _fetcher=_make_fetcher({}))

    bars = cache.fetch("BTCUSDT", _date(today.year + 1, 1, 1), future_end)

    # start > today after clamping → empty
    assert bars == []


def test_start_after_end_returns_empty(tmp_path):
    """If start > end (after clamping) fetch returns empty without erroring."""
    cache = IntradayBinanceVisionCache(tmp_path / "cache", _fetcher=_make_fetcher({}))
    bars = cache.fetch("BTCUSDT", date(2024, 3, 5), date(2024, 3, 1))
    assert bars == []


# ---------------------------------------------------------------------------
# Spot vs perp URL routing
# ---------------------------------------------------------------------------


def test_spot_hits_spot_tree(tmp_path):
    """market="spot" sends requests to data/spot/ not the futures tree."""
    day_map = _fixture_map((2024, 1, 1))
    fetcher = _make_fetcher(day_map)
    cache = IntradayBinanceVisionCache(tmp_path / "spot", market="spot", _fetcher=fetcher)
    cache.fetch("BTCUSDT", date(2024, 1, 1), date(2024, 1, 1))
    assert all("/data/spot/" in u for u in fetcher.calls)


def test_perp_hits_futures_um_tree(tmp_path):
    """market="perp" sends requests to data/futures/um/ not the spot tree."""
    day_map = _fixture_map((2024, 1, 1))
    # Remap label keys — perp paths still carry YYYY-MM-DD so the fetcher works the same way.
    fetcher = _make_fetcher(day_map)
    cache = IntradayBinanceVisionCache(tmp_path / "perp", market="perp", _fetcher=fetcher)
    cache.fetch("BTCUSDT", date(2024, 1, 1), date(2024, 1, 1))
    assert all("/data/futures/um/" in u for u in fetcher.calls)


def test_invalid_market_rejected(tmp_path):
    with pytest.raises(ValueError, match="market"):
        IntradayBinanceVisionCache(tmp_path, market="options")


# ---------------------------------------------------------------------------
# Cache file is present after fetch
# ---------------------------------------------------------------------------


def test_cache_file_written_atomically(tmp_path):
    """After a successful fetch a .json cache file exists and is valid JSON."""
    import json

    day_map = _fixture_map((2024, 1, 1))
    cache = IntradayBinanceVisionCache(tmp_path / "cache", _fetcher=_make_fetcher(day_map))
    cache.fetch("BTCUSDT", date(2024, 1, 1), date(2024, 1, 1))

    cache_files = list((tmp_path / "cache").glob("*.json"))
    assert len(cache_files) == 1
    rows = json.loads(cache_files[0].read_text())
    assert isinstance(rows, list) and len(rows) == _DAY_BARS
    # No partial / temp files left over.
    assert not list((tmp_path / "cache").glob("*.tmp"))
