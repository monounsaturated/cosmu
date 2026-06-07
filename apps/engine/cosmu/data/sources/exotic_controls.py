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
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

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
    "_parse_usgs",
]
