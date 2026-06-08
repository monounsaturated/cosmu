# Offline tests for the alt-data HISTORICAL backfill path: the catalog `spec.backfill` closures wired
# through DataManager.backfill so `manage backfill weather/wikipedia/exotic_controls --days N` returns
# HUNDREDS of point-in-time points (deep, retro-testable) instead of one current snapshot.
#
# Everything is injected — wide offline fixtures via duck-typed seams on stub bridge providers — so the
# whole catalog→manager→store path runs with NO live network. Invariants proven:
#   - depth: a 400-day backfill writes hundreds of points (the whole reason this exists)
#   - PIT honesty: every stored point's available_at <= as_of (no look-ahead)
#   - idempotency: a second backfill writes 0 new points (append-only + dedup on (provider,symbol,metric,ts))
#   - kind=="alt_history": the manager routes these sources through spec.backfill, not a single fetch

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from cosmu.data.providers.store import AltDataStore
from cosmu.ingest.manage import DataManager

_NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _manager(tmp_path, providers) -> DataManager:
    return DataManager(
        store=AltDataStore(tmp_path / "alt"),
        market_data_dir=tmp_path / "market_data",
        panel_dir=tmp_path / "panels",
        clock=lambda: _NOW,
        providers=providers,
    )


# --------------------------------------------------------------------------- seam-carrying stub providers


class _WeatherStub:
    """Stub weather bridge carrying a wide offline `backfill_fixture` the catalog closure reuses."""

    offline = True

    def __init__(self, n_days: int) -> None:
        start = date(2024, 1, 1)
        times = [(start + timedelta(days=i)).isoformat() for i in range(n_days)]
        self.backfill_fixture = {
            "nyc": {
                "latitude": 40.71, "longitude": -74.01,
                "daily": {
                    "time": times,
                    "temperature_2m_mean": [5.0 + (i % 7) for i in range(n_days)],
                    "precipitation_sum": [float(i % 5) for i in range(n_days)],
                    "windspeed_10m_max": [10.0 + (i % 10) for i in range(n_days)],
                },
            }
        }


class _WikiStub:
    """Stub wikipedia bridge carrying a `_fetcher` the catalog closure injects into the source."""

    def __init__(self, n_days: int) -> None:
        base = datetime(2024, 1, 1, tzinfo=UTC)
        items = [
            {"timestamp": (base + timedelta(days=i)).strftime("%Y%m%d") + "00", "views": 10_000 + i * 100}
            for i in range(n_days)
        ]
        self._payload = {"items": items}

    def _fetcher(self, _url: str) -> dict:
        return self._payload


class _ExoticStub:
    """Stub exotic-controls bridge carrying injected FDSN + NOAA history fetchers."""

    offline = False

    def __init__(self, n_days: int) -> None:
        start = date(2024, 1, 1)
        feats = []
        for d in range(n_days):
            day = datetime(start.year, start.month, start.day, 12, tzinfo=UTC) + timedelta(days=d)
            for k in range(3):
                feats.append({"properties": {"time": int(day.timestamp() * 1000), "mag": 2.0 + k}})
        self._usgs = {"features": feats}
        rows = [["time_tag", "Kp"]]  # header
        for d in range(n_days):
            day = datetime(start.year, start.month, start.day, tzinfo=UTC) + timedelta(days=d)
            for h in range(0, 24, 3):
                rows.append([(day + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S"), f"{(h / 3) % 9:.2f}"])
        self._kp = rows

    def usgs_history_fetcher(self, _url: str) -> dict:
        return self._usgs

    def kp_history_fetcher(self, _url: str) -> list:
        return self._kp


class _Providers:
    """Minimal duck-typed Providers carrying only the backfill seams the closures read."""

    def __init__(self, *, weather=None, wiki_pageviews=None, exotic_controls=None) -> None:
        self.weather = weather
        self.wiki_pageviews = wiki_pageviews
        self.exotic_controls = exotic_controls


# --------------------------------------------------------------------------- weather


def test_weather_backfill_returns_hundreds_not_one(tmp_path):
    mgr = _manager(tmp_path, _Providers(weather=_WeatherStub(n_days=300)))
    result = mgr.backfill("weather", days=400, symbols=["MARKET"])
    assert result["kind"] == "alt_history"
    r = result["results"]["weather_hub_stress"]
    assert r["written"] > 100  # deep history, not a single snapshot
    # PIT: every stored point is knowable by _NOW.
    stored = mgr._get_store().read_asof("openmeteo", "MARKET", "weather_hub_stress", _NOW)
    assert len(stored) == r["written"]
    for p in stored:
        assert p.available_at <= _NOW
    # Idempotent: re-running writes 0 new points.
    again = mgr.backfill("weather", days=400, symbols=["MARKET"])
    assert again["results"]["weather_hub_stress"]["written"] == 0


# --------------------------------------------------------------------------- wikipedia


def test_wikipedia_backfill_returns_deep_per_symbol_series(tmp_path):
    mgr = _manager(tmp_path, _Providers(wiki_pageviews=_WikiStub(n_days=200)))
    result = mgr.backfill("wikipedia", days=400, symbols=["BTCUSDT"])
    assert result["kind"] == "alt_history"
    raw = result["results"]["wiki_pageviews"]
    assert raw["written"] > 100
    # All three derived metrics are walked.
    assert set(result["results"]) == {"wiki_pageviews", "wiki_pageviews_log", "wiki_pageviews_zscore"}
    stored = mgr._get_store().read_asof("wikimedia", "BTCUSDT", "wiki_pageviews", _NOW)
    assert len(stored) == raw["written"]
    for p in stored:
        assert p.available_at <= _NOW
    again = mgr.backfill("wikipedia", days=400, symbols=["BTCUSDT"])
    assert again["results"]["wiki_pageviews"]["written"] == 0


# --------------------------------------------------------------------------- exotic controls


def test_exotic_controls_backfill_returns_hundreds(tmp_path):
    mgr = _manager(tmp_path, _Providers(exotic_controls=_ExoticStub(n_days=180)))
    result = mgr.backfill("exotic_controls", days=400, symbols=["MARKET"])
    assert result["kind"] == "alt_history"
    assert set(result["results"]) == {"usgs_earthquake_count", "usgs_max_magnitude", "noaa_kp_index"}
    for metric, store_provider in (
        ("usgs_earthquake_count", "usgs"),
        ("usgs_max_magnitude", "usgs"),
        ("noaa_kp_index", "noaa"),
    ):
        r = result["results"][metric]
        assert r["written"] > 100, f"{metric} should be deep, got {r['written']}"
        stored = mgr._get_store().read_asof(store_provider, "MARKET", metric, _NOW)
        assert len(stored) == r["written"]
        for p in stored:
            assert p.available_at <= _NOW
    again = mgr.backfill("exotic_controls", days=400, symbols=["MARKET"])
    assert again["results"]["noaa_kp_index"]["written"] == 0


def test_backfill_without_seam_does_not_crash(tmp_path):
    """A provider with no seams (e.g. live defaults, offline) still routes through alt_history safely."""

    class _Off:
        offline = True

    mgr = _manager(tmp_path, _Providers(weather=_Off()))
    result = mgr.backfill("weather", days=400, symbols=["MARKET"])
    assert result["kind"] == "alt_history"
    # The 2-day bundled fixture yields a tiny series — honest, never a crash.
    assert result["results"]["weather_hub_stress"]["written"] >= 0
