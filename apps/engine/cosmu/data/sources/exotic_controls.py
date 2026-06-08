# intent: EXOTIC ORTHOGONALITY CONTROLS (non-causal, wire honestly).
#
# Two free, keyless geophysical/space-weather series purposely chosen because they carry zero
# plausible causal path to crypto prices — they are orthogonality control features the Gate is
# expected to kill.  Wiring them honestly gives the research harness a known-false baseline:
# if the Gate ever relies on earthquake counts or Kp index as a primary signal, that is a
# red-flag for data-snooping, not a genuine edge.
#
# Sources (both free, no API key):
#   USGS Earthquake Hazards Program — GeoJSON summary feed (daily counts + max magnitude).
#     Endpoint: https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson
#     The feed is continuously updated; "all_day" reflects the past 24 hours as of the request.
#     Real-world note: a day's catalog is substantially complete by midnight UTC the next day;
#     in a production daily-batch pipeline, store with available_at = obs_day + 1.  The live
#     query adapter stamps available_at = as_of (the moment of observation).
#     Revision behavior: USGS revises magnitudes retrospectively; the live feed reflects the
#     current best estimate.  Treat as revised — document in prior.
#
#   NOAA Space Weather Prediction Center — planetary Kp-index (3-hourly → daily max).
#     Endpoint: https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json
#     Kp measures geomagnetic storm intensity [0–9].
#     Real-world note: Kp is "estimated" at publication; definitive values arrive later.
#     Live query stamps available_at = as_of.
#
# PIT contract (LIVE query adapter — same convention as osint_adsb):
#   available_at = as_of (the snapshot is knowable at the moment it is taken — no look-ahead).
#   A gap is absent (value=None), NEVER filled with 0 — a parse failure returns None, not 0.
#   Non-causal: the Gate is expected to falsify these; they are never expected to survive.
#
# Docstring: "orthogonality control"

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from cosmu.data.providers._types import AltDataPoint
from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned transform versions — bump if the aggregation logic changes.
USGS_TRANSFORM_VERSION = "exotic-usgs-eq-v1"
NOAA_KP_TRANSFORM_VERSION = "exotic-noaa-kp-v1"

# ---------------------------------------------------------------------------
# Offline fixtures (deterministic, no network in tests)
# ---------------------------------------------------------------------------

# Shape mirrors a real USGS GeoJSON all_day feed: {"features": [{"properties": {"mag": ...}}]}
_USGS_FIXTURE: dict = {
    "metadata": {"time": 1_700_000_000_000},
    "features": [
        {"properties": {"mag": 2.1}},
        {"properties": {"mag": 3.5}},
        {"properties": {"mag": 1.8}},
        {"properties": {"mag": 5.2}},
        {"properties": {"mag": 0.9}},
    ],
}

# Shape mirrors a real NOAA Kp JSON: list of [time_tag, Kp, ...]
_NOAA_KP_FIXTURE: list = [
    ["2023-11-14 00:00:00", "0.33", "0", "-1", "7", "4"],
    ["2023-11-14 03:00:00", "1.67", "0", "-1", "7", "4"],
    ["2023-11-14 06:00:00", "3.00", "0", "-1", "7", "4"],
    ["2023-11-14 09:00:00", "2.33", "0", "-1", "7", "4"],
    ["2023-11-14 12:00:00", "1.00", "0", "-1", "7", "4"],
    ["2023-11-14 15:00:00", "0.67", "0", "-1", "7", "4"],
    ["2023-11-14 18:00:00", "4.33", "0", "-1", "7", "4"],
    ["2023-11-14 21:00:00", "2.00", "0", "-1", "7", "4"],
]


# Historical endpoints (date-range, for backfill — distinct from the live "all_day" snapshot feeds):
#   USGS FDSN event query — returns every event in [starttime, endtime] as GeoJSON features, each with a
#     properties.time (epoch ms) and properties.mag.  We bin by UTC day → daily count + daily max-mag.
#   NOAA Kp — the products JSON already carries ~30+ days of 3-hourly rows; we bin by UTC day → daily-max Kp.
_USGS_QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
_NOAA_KP_HISTORY_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"

# Daily-batch PIT convention (documented in every prior): a day's catalog/series is substantially
# complete by 00:00 UTC the NEXT day, so the earliest a calendar day D is honestly knowable is D+1.
_BACKFILL_PIT_LAG = timedelta(days=1)


def _backfill_available_at(obs_date: date) -> datetime:
    """Daily-batch PIT stamp: a calendar day's reading is knowable at 00:00 UTC the next day."""
    return datetime(obs_date.year, obs_date.month, obs_date.day, tzinfo=UTC) + _BACKFILL_PIT_LAG


def _ssl_context() -> ssl.SSLContext:
    """certifi-backed context so HTTPS works on hosts without system CA certs."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch_json(url: str, timeout: float = 15.0) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Parse helpers (pure functions — tested directly in isolation)
# ---------------------------------------------------------------------------

def _parse_usgs(payload: dict) -> tuple[int, float | None]:
    """Return (event_count, max_magnitude) from a USGS GeoJSON payload.

    A gap in magnitude data (all None mags) yields max_magnitude=None, not 0.
    """
    features = payload.get("features") or []
    count = len(features)
    mags = [
        float(f["properties"]["mag"])
        for f in features
        if isinstance((f.get("properties") or {}).get("mag"), int | float)
    ]
    max_mag = max(mags) if mags else None
    return count, max_mag


def _parse_kp(rows: list) -> float | None:
    """Return the daily-max Kp from NOAA Kp rows [[time_tag, kp_str, ...], ...].

    Kp values that cannot be parsed as float are skipped.  Returns None (gap) if no parseable
    value exists — never 0-fills a gap.
    """
    values: list[float] = []
    for row in rows:
        if not row or len(row) < 2:
            continue
        try:
            values.append(float(row[1]))
        except (ValueError, TypeError):
            continue
    return max(values) if values else None


# ---------------------------------------------------------------------------
# Historical (date-range) parse helpers — daily binning for backfill
# ---------------------------------------------------------------------------

def _parse_usgs_daily(payload: dict) -> dict[date, tuple[int, float | None]]:
    """Bin a USGS FDSN query GeoJSON into {utc_day: (event_count, max_magnitude)}.

    Each feature carries properties.time (epoch MILLISECONDS) and properties.mag.  A day with events
    but all-None magnitudes yields max_magnitude=None (honest gap, not 0).  Days with no events are
    simply ABSENT from the dict — never fabricated as 0-count (an unobserved day is unknown, not zero).
    """
    features = payload.get("features") or []
    counts: dict[date, int] = {}
    mags: dict[date, list[float]] = {}
    for f in features:
        props = f.get("properties") or {}
        t_ms = props.get("time")
        if not isinstance(t_ms, int | float):
            continue
        day = datetime.fromtimestamp(t_ms / 1000.0, tz=UTC).date()
        counts[day] = counts.get(day, 0) + 1
        mag = props.get("mag")
        if isinstance(mag, int | float):
            mags.setdefault(day, []).append(float(mag))
    out: dict[date, tuple[int, float | None]] = {}
    for day, count in counts.items():
        day_mags = mags.get(day)
        out[day] = (count, max(day_mags) if day_mags else None)
    return out


def _parse_kp_daily(rows: list) -> dict[date, float]:
    """Bin NOAA Kp 3-hourly rows [[time_tag, kp_str, ...], ...] into {utc_day: daily_max_kp}.

    A header row (non-numeric kp) or any unparseable value is skipped.  Days with no parseable value
    are ABSENT (honest gap — never 0-filled).
    """
    by_day: dict[date, float] = {}
    for row in rows:
        if not row or len(row) < 2:
            continue
        tag = row[0]
        try:
            kp = float(row[1])
        except (ValueError, TypeError):
            continue  # header ("Kp") or junk
        try:
            obs = datetime.fromisoformat(str(tag).replace("Z", "")).date()
        except ValueError:
            continue
        prev = by_day.get(obs)
        if prev is None or kp > prev:
            by_day[obs] = kp
    return by_day


def _fetch_json_seam(url: str, fetcher, timeout: float) -> object | None:
    """Fetch JSON via an injected `_fetcher(url)` seam if present, else the live `_fetch_json`.

    Returns None on any error so a backfill degrades to the fixture instead of crashing.
    """
    try:
        if fetcher is not None:
            return fetcher(url)
        return _fetch_json(url, timeout)
    except Exception:  # noqa: BLE001 — degrade gracefully, never crash a backfill pass
        return None


def _usgs_query_url(start: date, end: date) -> str:
    """FDSN event query URL for all events in [start, end] (inclusive end, GeoJSON)."""
    params = urllib.parse.urlencode({
        "format": "geojson",
        "starttime": start.isoformat(),
        "endtime": (end + timedelta(days=1)).isoformat(),  # endtime exclusive at FDSN → +1 day for inclusive
        "orderby": "time-asc",
    })
    return f"{_USGS_QUERY_URL}?{params}"


def _usgs_daily_window(start: date, end: date, *, fetcher, offline: bool, fixture: dict, timeout: float) -> dict[date, tuple[int, float | None]]:
    """Fetch + bin USGS events over [start, end] → {day: (count, max_mag)}. Degrades to fixture binning."""
    if offline:
        payload: object | None = fixture
    else:
        payload = _fetch_json_seam(_usgs_query_url(start, end), fetcher, timeout)
        if not isinstance(payload, dict):
            payload = fixture
    return _parse_usgs_daily(payload if isinstance(payload, dict) else {})


# ---------------------------------------------------------------------------
# UsgsEarthquakeSource
# ---------------------------------------------------------------------------

@dataclass
class UsgsEarthquakeSource:
    """USGS GeoJSON all-day earthquake feed — daily event count.

    Orthogonality control: there is no plausible causal path from global earthquake activity to
    crypto prices.  This source exists so the Gate has a known-false baseline to kill, providing
    evidence that the research harness is not noise-mining.  Docstring: "orthogonality control".

    PIT contract (live query adapter):
      available_at = as_of — a live snapshot is only knowable at the moment it is taken,
      matching the osint_adsb convention.  In a production daily-batch pipeline the ingest layer
      would store each day's fetch with available_at = obs_day + 1 day; that is documented in the
      prior but not enforced here (this is the live-query adapter, not the batch store).

      A gap in the feed (no features) yields value=0 for count (0 events is a valid reading, not
      a fabrication).  A gap in magnitudes (all None) yields max_magnitude=None, not 0 — because
      "unknown magnitude" is genuinely absent data.

    Revision risk: USGS revises magnitudes retrospectively; documented in prior.
    """

    name: str = "usgs_earthquake_count"
    kind: SourceKind = "osint"
    metric: str = "usgs_earthquake_count"
    prior: str = (
        "ORTHOGONALITY CONTROL: global earthquake event count (past 24 h) from the USGS free "
        "GeoJSON feed.  No plausible causal path to crypto prices — pure orthogonal noise wired "
        "honestly so the Gate has a known-false baseline to kill.  Revision risk: USGS revises "
        "magnitudes retrospectively; the live feed reflects the current best estimate (treat as "
        "revised data).  In a daily-batch pipeline, available_at = obs_day + 1 UTC midnight "
        "(next-day floor).  Live query: available_at = as_of.  Must be killed by the Gate."
    )
    transform_version: str = USGS_TRANSFORM_VERSION
    confidence: float = 0.05  # deliberately minimal — expected Gate kill

    base_url: str = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
    offline: bool = False
    timeout: float = 15.0
    _fixture: dict = field(default_factory=lambda: dict(_USGS_FIXTURE))
    _history_fetcher: object = None  # optional injected fetcher(url)->dict for the FDSN query (tests)

    @property
    def low_confidence(self) -> bool:
        return True  # always — orthogonality control

    def _fetch_payload(self) -> dict:
        """Live USGS GeoJSON feed.  Falls back to the fixture on any network failure."""
        if self.offline:
            return self._fixture
        try:
            result = _fetch_json(self.base_url, self.timeout)
            if isinstance(result, dict):
                return result
            return self._fixture
        except Exception:  # noqa: BLE001 — degrade gracefully, never crash the research pass
            return self._fixture

    def backfill(self, days: int, *, as_of: datetime | None = None) -> list[AltDataPoint]:
        """Pull `days` of daily earthquake-COUNT history as point-in-time AltDataPoints.

        Uses the USGS FDSN event query (starttime/endtime) — ONE request for the whole window,
        binned by UTC day → daily event count.  PIT stamp: available_at = obs_day + 1 (the daily
        catalog is substantially complete the next UTC midnight), so no look-ahead.  A day with no
        observed events is ABSENT (an unobserved day is unknown, not a fabricated 0).  Offline / error
        degrades to fixture binning so tests are deterministic with no network.
        """
        now = as_of or datetime.now(tz=UTC)
        end_date = now.date() - timedelta(days=1)
        start_date = end_date - timedelta(days=max(0, days - 1))
        if end_date < start_date:
            return []
        daily = _usgs_daily_window(
            start_date, end_date, fetcher=self._history_fetcher,
            offline=self.offline, fixture=self._fixture, timeout=self.timeout,
        )
        out: list[AltDataPoint] = []
        for obs_date in sorted(daily):
            if not (start_date <= obs_date <= end_date):
                continue
            count, _max_mag = daily[obs_date]
            available_at = _backfill_available_at(obs_date)
            if available_at > now:
                continue
            out.append(AltDataPoint(ts=available_at, available_at=available_at, value=float(count)))
        return out

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Point-in-time earthquake count snapshot.

        available_at = as_of (the snapshot is only knowable at the moment of observation — no
        look-ahead, same convention as osint_adsb).  scope/limit are part of the DataSource
        protocol but unused (market-wide geophysical series).
        """
        del scope, limit
        payload = self._fetch_payload()
        count, _max_mag = _parse_usgs(payload)
        return SourceFeature(
            name=self.name,
            scope="MARKET",
            as_of=as_of,
            value=float(count),
            available_at=as_of,  # live snapshot: knowable at observation time
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )

    def parse_count_and_max_mag(self, payload: dict | None = None) -> tuple[int, float | None]:
        """Expose the parse step for tests/inspection: (event_count, max_magnitude)."""
        return _parse_usgs(payload if payload is not None else self._fixture)


# ---------------------------------------------------------------------------
# UsgsMaxMagnitudeSource
# ---------------------------------------------------------------------------

@dataclass
class UsgsMaxMagnitudeSource:
    """USGS GeoJSON all-day feed — daily max earthquake magnitude.

    Orthogonality control (same as UsgsEarthquakeSource).  A separate named source so the Gate
    can test count and magnitude independently.  Docstring: "orthogonality control".

    PIT contract: available_at = as_of (live snapshot convention).
    Gap semantics: max_magnitude is None if no magnitude-bearing events are in the feed — a gap,
    not 0 (because "unknown magnitude" is genuinely absent, not zero).
    """

    name: str = "usgs_max_magnitude"
    kind: SourceKind = "osint"
    metric: str = "usgs_max_magnitude"
    prior: str = (
        "ORTHOGONALITY CONTROL: daily maximum earthquake magnitude from the USGS free GeoJSON "
        "feed.  No plausible causal path to crypto prices — pure orthogonal noise so the Gate "
        "has a known-false baseline.  Revision risk: USGS revises magnitudes retrospectively.  "
        "Gap = None (not 0) when no magnitude-bearing events exist.  Live query: available_at = "
        "as_of.  Must be killed by the Gate."
    )
    transform_version: str = USGS_TRANSFORM_VERSION
    confidence: float = 0.05

    base_url: str = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
    offline: bool = False
    timeout: float = 15.0
    _fixture: dict = field(default_factory=lambda: dict(_USGS_FIXTURE))
    _history_fetcher: object = None  # optional injected fetcher(url)->dict for the FDSN query (tests)

    @property
    def low_confidence(self) -> bool:
        return True

    def _fetch_payload(self) -> dict:
        if self.offline:
            return self._fixture
        try:
            result = _fetch_json(self.base_url, self.timeout)
            if isinstance(result, dict):
                return result
            return self._fixture
        except Exception:  # noqa: BLE001
            return self._fixture

    def backfill(self, days: int, *, as_of: datetime | None = None) -> list[AltDataPoint]:
        """Pull `days` of daily MAX-MAGNITUDE history as point-in-time AltDataPoints.

        Same FDSN window fetch as the count source (one request, binned by UTC day).  A day whose
        events all lack a magnitude yields NO point (max_magnitude is an honest gap, never a fabricated
        0 — and a day with no events is likewise absent).  PIT stamp: available_at = obs_day + 1.
        Offline / error degrades to fixture binning.
        """
        now = as_of or datetime.now(tz=UTC)
        end_date = now.date() - timedelta(days=1)
        start_date = end_date - timedelta(days=max(0, days - 1))
        if end_date < start_date:
            return []
        daily = _usgs_daily_window(
            start_date, end_date, fetcher=self._history_fetcher,
            offline=self.offline, fixture=self._fixture, timeout=self.timeout,
        )
        out: list[AltDataPoint] = []
        for obs_date in sorted(daily):
            if not (start_date <= obs_date <= end_date):
                continue
            _count, max_mag = daily[obs_date]
            if max_mag is None:
                continue  # honest gap — no magnitude data that day, never fabricate 0
            available_at = _backfill_available_at(obs_date)
            if available_at > now:
                continue
            out.append(AltDataPoint(ts=available_at, available_at=available_at, value=float(max_mag)))
        return out

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Point-in-time max magnitude snapshot.  value=None if no magnitude-bearing events
        (gap, not 0 — absent data must not be fabricated).  available_at = as_of."""
        del scope, limit
        payload = self._fetch_payload()
        _count, max_mag = _parse_usgs(payload)
        # A None max_mag is an honest gap — no magnitude data in the feed.  Do not fill with 0.
        return SourceFeature(
            name=self.name,
            scope="MARKET",
            as_of=as_of,
            value=max_mag,  # None if no magnitude data — gap, not 0
            available_at=as_of if max_mag is not None else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )

    def parse_max_magnitude(self, payload: dict | None = None) -> float | None:
        """Expose the parse step for tests/inspection: max magnitude or None."""
        _count, max_mag = _parse_usgs(payload if payload is not None else self._fixture)
        return max_mag


# ---------------------------------------------------------------------------
# NoaaKpIndexSource
# ---------------------------------------------------------------------------

@dataclass
class NoaaKpIndexSource:
    """NOAA SWPC planetary Kp geomagnetic index — daily maximum.

    Orthogonality control: geomagnetic activity has no plausible causal path to crypto prices.
    This source exists purely as a known-false orthogonal baseline; the Gate should kill it.
    Docstring: "orthogonality control".

    PIT contract (live query adapter):
      available_at = as_of — live snapshot knowable at the moment of observation, no look-ahead.
      In a production daily-batch pipeline the ingest layer would store with available_at = obs_day
      + 1 day (NOAA Kp is "estimated" at publication and later made "definitive"); documented in
      the prior.

    Gap semantics: value=None if no parseable Kp rows (gap, not 0 — absent data is not
    zero-filled).  Revision risk: NOAA Kp estimated→definitive; documented in prior.
    """

    name: str = "noaa_kp_index"
    kind: SourceKind = "osint"
    metric: str = "noaa_kp_index"
    prior: str = (
        "ORTHOGONALITY CONTROL: NOAA planetary Kp geomagnetic index (daily max [0–9]).  "
        "No plausible causal path to crypto prices — pure orthogonal noise wired honestly so "
        "the Gate has a known-false baseline to kill.  Revision risk: NOAA Kp is 'estimated' at "
        "publication and later replaced by a definitive value (treat as revised).  In a daily-"
        "batch pipeline, available_at = obs_day + 1 UTC midnight (next-day floor).  Live query: "
        "available_at = as_of.  Gap = None (not 0) when no parseable rows.  Must be killed by "
        "the Gate."
    )
    transform_version: str = NOAA_KP_TRANSFORM_VERSION
    confidence: float = 0.05

    base_url: str = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
    offline: bool = False
    timeout: float = 15.0
    _fixture: list = field(default_factory=lambda: list(_NOAA_KP_FIXTURE))
    # The NOAA products JSON already carries ~30+ days of 3-hourly rows, so the live feed IS the
    # history source — no separate endpoint needed. An optional injected fetcher seam for tests.
    history_url: str = _NOAA_KP_HISTORY_URL
    _history_fetcher: object = None

    @property
    def low_confidence(self) -> bool:
        return True

    def _fetch_payload(self) -> list:
        """Live NOAA Kp JSON.  Falls back to the fixture on any network failure."""
        if self.offline:
            return self._fixture
        try:
            result = _fetch_json(self.base_url, self.timeout)
            if isinstance(result, list):
                return result  # type: ignore[return-value]
            return self._fixture
        except Exception:  # noqa: BLE001
            return self._fixture

    def backfill(self, days: int, *, as_of: datetime | None = None) -> list[AltDataPoint]:
        """Pull `days` of daily-max Kp history as point-in-time AltDataPoints.

        The NOAA products JSON ships ~30+ days of 3-hourly rows in ONE response, so the whole window
        comes from a single request; we bin by UTC day → daily-max Kp.  PIT stamp: available_at =
        obs_day + 1 (NOAA Kp is 'estimated' at publication; the definitive daily value is honestly
        knowable the next UTC midnight).  Days with no parseable row are ABSENT (gap, never 0-filled).
        Offline / error degrades to fixture binning.
        """
        now = as_of or datetime.now(tz=UTC)
        end_date = now.date() - timedelta(days=1)
        start_date = end_date - timedelta(days=max(0, days - 1))
        if end_date < start_date:
            return []
        if self.offline:
            rows: object | None = self._fixture
        else:
            rows = _fetch_json_seam(self.history_url, self._history_fetcher, self.timeout)
            if not isinstance(rows, list):
                rows = self._fixture
        by_day = _parse_kp_daily(rows if isinstance(rows, list) else [])
        out: list[AltDataPoint] = []
        for obs_date in sorted(by_day):
            if not (start_date <= obs_date <= end_date):
                continue
            available_at = _backfill_available_at(obs_date)
            if available_at > now:
                continue
            out.append(AltDataPoint(ts=available_at, available_at=available_at, value=float(by_day[obs_date])))
        return out

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Point-in-time daily-max Kp snapshot.  value=None if no parseable rows (gap, not 0).
        available_at = as_of.  scope/limit unused (market-wide geophysical series)."""
        del scope, limit
        rows = self._fetch_payload()
        kp_max = _parse_kp(rows)
        return SourceFeature(
            name=self.name,
            scope="MARKET",
            as_of=as_of,
            value=kp_max,  # None if no parseable rows — gap, not 0
            available_at=as_of if kp_max is not None else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )

    def parse_kp_max(self, rows: list | None = None) -> float | None:
        """Expose the parse step for tests/inspection."""
        return _parse_kp(rows if rows is not None else self._fixture)


__all__ = [
    "NOAA_KP_TRANSFORM_VERSION",
    "USGS_TRANSFORM_VERSION",
    "NoaaKpIndexSource",
    "UsgsEarthquakeSource",
    "UsgsMaxMagnitudeSource",
    "_parse_kp",
    "_parse_kp_daily",
    "_parse_usgs",
    "_parse_usgs_daily",
]
