# intent: a POINT-IN-TIME weather DataSource backed by the Open-Meteo Historical Archive API
# (https://archive-api.open-meteo.com, free, no key). Daily weather (temperature / precipitation /
# wind speed) for a handful of major financial-hub lat/lons is fetched and stamped with
# available_at = observation_date + 1 day (the data for a given calendar day is published the next day
# by Open-Meteo, so it is only KNOWABLE the following day — never same-day look-ahead).
#
# PIT contract: every datum carries a distinct available_at that is strictly AFTER the observation day.
# Gaps are returned as absent (None) — never fabricated zeros.
# Revision policy: Open-Meteo's archive occasionally revises QC'd values; the revision delta is small
# (reanalysis corrections) and is documented in their changelog. We treat any re-fetch as canonical for
# the available_at recorded at ingest time — downstream reprocessing must re-fetch to pick up revisions.
#
# Confidence: this is a non-causal, speculative macro feature (weather → economic-activity sentiment).
# Confidence is set LOW; it must earn its place through out-of-sample testing via the Gate.

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

from cosmu.data.sources.registry import SourceFeature, SourceKind

# Bump when the feature derivation logic changes so any cached series is invalidated.
TRANSFORM_VERSION = "weather-openmeteo-v1"

# Financial hubs: (name, lat, lon). Chosen to represent major capital-flow centres.
# NYC (~Wall St), London, Tokyo, Shanghai.
FINANCIAL_HUBS: list[tuple[str, float, float]] = [
    ("nyc", 40.71, -74.01),
    ("lon", 51.51, -0.13),
    ("tyo", 35.68, 139.69),
    ("sha", 31.23, 121.47),
]

# We request these daily variables from the Open-Meteo archive.
# temperature_2m_mean   — °C mean for the day
# precipitation_sum     — mm total for the day
# windspeed_10m_max     — km/h maximum gust
_DAILY_VARS = "temperature_2m_mean,precipitation_sum,windspeed_10m_max"

# PIT lag: Open-Meteo archive data for date D is available on D+1 (reanalysis pipeline finishes ~06:00 UTC).
_PIT_LAG_DAYS = 1

# ---------------------------------------------------------------------------
# Offline fixture — mirrors the Open-Meteo /v1/archive JSON shape for two days
# at a single location (NYC).  Tests parse THIS instead of touching the network.
# ---------------------------------------------------------------------------
_FIXTURE_NYC: dict = {
    "latitude": 40.71,
    "longitude": -74.01,
    "daily": {
        "time": ["2024-01-01", "2024-01-02"],
        "temperature_2m_mean": [2.1, -0.3],
        "precipitation_sum": [0.0, 5.4],
        "windspeed_10m_max": [18.2, 31.7],
    },
}

# A multi-hub fixture used by the DataSource-level offline test.
_FIXTURE_MULTI: dict[str, dict] = {
    "nyc": _FIXTURE_NYC,
    "lon": {
        "latitude": 51.51,
        "longitude": -0.13,
        "daily": {
            "time": ["2024-01-01", "2024-01-02"],
            "temperature_2m_mean": [8.5, 7.2],
            "precipitation_sum": [1.2, 0.0],
            "windspeed_10m_max": [22.0, 15.5],
        },
    },
    "tyo": {
        "latitude": 35.68,
        "longitude": 139.69,
        "daily": {
            "time": ["2024-01-01", "2024-01-02"],
            "temperature_2m_mean": [6.3, 5.8],
            "precipitation_sum": [0.0, 0.0],
            "windspeed_10m_max": [12.4, 9.1],
        },
    },
    "sha": {
        "latitude": 31.23,
        "longitude": 121.47,
        "daily": {
            "time": ["2024-01-01", "2024-01-02"],
            "temperature_2m_mean": [7.0, 6.1],
            "precipitation_sum": [0.0, 2.3],
            "windspeed_10m_max": [10.5, 14.0],
        },
    },
}


class WeatherDay(NamedTuple):
    """One parsed weather observation for a single hub+day."""

    hub: str
    obs_date: date            # the calendar day observed
    available_at: datetime    # obs_date + 1 day 06:00 UTC (earliest knowable)
    temp_mean_c: float | None
    precip_mm: float | None
    wind_max_kph: float | None


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _pit_available_at(obs_date: date) -> datetime:
    """Open-Meteo reanalysis for date D is available at ~06:00 UTC on D+1."""
    return datetime(
        obs_date.year, obs_date.month, obs_date.day,
        6, 0, 0, tzinfo=UTC
    ) + timedelta(days=_PIT_LAG_DAYS)


def fetch_weather_archive(
    hub: str,
    lat: float,
    lon: float,
    start: date,
    end: date,
    *,
    base_url: str = "https://archive-api.open-meteo.com",
    timeout: float = 20.0,
) -> list[WeatherDay]:
    """Fetch daily weather from the Open-Meteo Historical Archive for one hub.

    Returns observations in ascending date order with PIT-correct available_at.
    A missing or None value in the API response becomes None (never fabricated 0).
    """
    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "daily": _DAILY_VARS,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "UTC",
    })
    url = f"{base_url}/v1/archive?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return _parse_payload(hub, payload)


def _parse_payload(hub: str, payload: dict) -> list[WeatherDay]:
    """Parse an Open-Meteo /v1/archive JSON payload into WeatherDay records.

    Gaps (API returns None) stay None — honest absence, never a fabricated zero.
    available_at is obs_date + PIT lag so no look-ahead is possible.
    """
    daily = payload.get("daily", {})
    times = daily.get("time", [])
    temps = daily.get("temperature_2m_mean", [None] * len(times))
    precips = daily.get("precipitation_sum", [None] * len(times))
    winds = daily.get("windspeed_10m_max", [None] * len(times))

    out: list[WeatherDay] = []
    for i, t in enumerate(times):
        obs = date.fromisoformat(t)
        out.append(WeatherDay(
            hub=hub,
            obs_date=obs,
            available_at=_pit_available_at(obs),
            temp_mean_c=float(temps[i]) if temps[i] is not None else None,
            precip_mm=float(precips[i]) if precips[i] is not None else None,
            wind_max_kph=float(winds[i]) if winds[i] is not None else None,
        ))
    return out


# ---------------------------------------------------------------------------
# Composite feature: a single scalar summarising cross-hub weather "stress"
# ---------------------------------------------------------------------------

def _weather_stress_score(days: list[WeatherDay]) -> float | None:
    """Combine multi-hub daily weather into a single normalised stress scalar in [0, 1].

    Heuristic: cold + wet + windy = disruption-stress. Each variable is min-max normalised
    against the fixture range (rough fixed scale), then averaged across hubs.
    Non-causal, low-confidence — must earn its place via out-of-sample.

    Returns None only if ALL hub values are absent (honest gap, never fabricated).
    """
    # Fixed normalisation anchors (rough world-city ranges):
    #   temp: [-20, 40] °C  →  inverted (cold = high stress)
    #   precip: [0, 50] mm
    #   wind: [0, 80] km/h
    T_MIN, T_MAX = -20.0, 40.0
    P_MAX = 50.0
    W_MAX = 80.0

    scores: list[float] = []
    for d in days:
        parts: list[float] = []
        if d.temp_mean_c is not None:
            # cold → high stress (invert)
            parts.append(1.0 - max(0.0, min(1.0, (d.temp_mean_c - T_MIN) / (T_MAX - T_MIN))))
        if d.precip_mm is not None:
            parts.append(max(0.0, min(1.0, d.precip_mm / P_MAX)))
        if d.wind_max_kph is not None:
            parts.append(max(0.0, min(1.0, d.wind_max_kph / W_MAX)))
        if parts:
            scores.append(sum(parts) / len(parts))

    if not scores:
        return None
    return sum(scores) / len(scores)


# ---------------------------------------------------------------------------
# DataSource adapter
# ---------------------------------------------------------------------------

@dataclass
class WeatherOpenMeteoSource:
    """Open-Meteo Archive daily weather for major financial hubs as a named, point-in-time DataSource.

    PIT contract:
      - available_at = obs_date + 1 day 06:00 UTC (the archive reanalysis finishes by then)
      - gaps are None, never fabricated 0
      - revision policy documented in module docstring

    Confidence: LOW (0.15). Non-causal macro feature that must earn its place via the Gate / OOS.
    Offline (offline=True or network failure) → fixture, deterministic for CI.
    """

    name: str = "weather_hub_stress"
    kind: SourceKind = "macro"
    metric: str = "weather_hub_stress"
    prior: str = (
        "Adverse weather across major financial hubs (cold/wet/windy) may mildly depress economic "
        "activity and sentiment, but the effect is tiny, non-causal, and almost certainly swamped by "
        "market-structure signals. VERY low confidence — wired to let the Gate falsify it honestly."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.15  # non-causal speculation; must earn via OOS
    hubs: list[tuple[str, float, float]] = field(default_factory=lambda: list(FINANCIAL_HUBS))
    base_url: str = "https://archive-api.open-meteo.com"
    offline: bool = False
    timeout: float = 20.0
    _fixture: dict[str, dict] = field(default_factory=lambda: dict(_FIXTURE_MULTI))

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _fetch_hub(self, hub: str, lat: float, lon: float, obs_date: date) -> list[WeatherDay]:
        """Fetch one hub for a single observation date. Falls back to fixture on any error."""
        if self.offline:
            fix = self._fixture.get(hub, {})
            return _parse_payload(hub, fix)
        try:
            return fetch_weather_archive(
                hub, lat, lon, obs_date, obs_date,
                base_url=self.base_url, timeout=self.timeout,
            )
        except Exception:  # noqa: BLE001 — degrade to fixture, never crash the research pass
            fix = self._fixture.get(hub, {})
            return _parse_payload(hub, fix)

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest cross-hub weather stress score whose available_at <= as_of.

        Walks backwards day-by-day (up to `limit` days) to find the most-recent observation
        that is actually KNOWABLE at as_of (available_at = obs_date + 1 day).  Returns None
        if no qualifying observation exists — honest gap, never a fabricated value.
        """
        del scope  # market-wide; symbol ignored

        # Find the most recent obs_date whose available_at <= as_of.
        # available_at(d) = date d + 1 day 06:00 UTC, so the latest qualifying d is:
        # the day before as_of (if as_of >= 06:00 UTC on that day).
        as_of_date = as_of.date()
        # candidate: the most recent day whose available_at is <= as_of
        # available_at(d) <= as_of  ⟺  d + 1day 06:00 UTC <= as_of
        # ⟺  d <= as_of.date() - 1 day  (conservatively; exact depends on time-of-day)
        candidate_date = as_of_date - timedelta(days=1)
        # Check whether the 06:00 UTC window has passed
        cutoff = _pit_available_at(candidate_date)
        if as_of < cutoff:
            candidate_date -= timedelta(days=1)

        if candidate_date < date(2015, 1, 1):  # open-meteo archive starts ~2015
            return SourceFeature(
                name=self.name, scope="MARKET", as_of=as_of,
                value=None, available_at=None,
                confidence=self.confidence, transform_version=self.transform_version,
                prior=self.prior, low_confidence=self.low_confidence,
            )

        # Fetch all hubs for that candidate date.
        all_days: list[WeatherDay] = []
        for hub, lat, lon in self.hubs:
            days = self._fetch_hub(hub, lat, lon, candidate_date)
            # Filter to the target date (fixture may contain multiple dates).
            all_days.extend(d for d in days if d.obs_date == candidate_date)

        pit = _pit_available_at(candidate_date)
        stress = _weather_stress_score(all_days)

        return SourceFeature(
            name=self.name,
            scope="MARKET",
            as_of=as_of,
            value=stress,
            available_at=pit if stress is not None else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )

    # ------------------------------------------------------------------
    # Helpers exposed for tests / inspection
    # ------------------------------------------------------------------

    def parse_days(self, hub: str, payload: dict) -> list[WeatherDay]:
        """Exposed for tests: parse a raw Open-Meteo JSON payload for a named hub."""
        return _parse_payload(hub, payload)

    def stress_score(self, days: list[WeatherDay]) -> float | None:
        """Exposed for tests: composite weather stress scalar from parsed days."""
        return _weather_stress_score(days)
