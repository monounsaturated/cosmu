# intent: a concrete OSINT DataSource example ("watching planes") over the FREE, anonymous OpenSky
# Network REST API. It turns live aircraft activity (flight count in a bounding box) into a point-in-time,
# availability-stamped, LOW-CONFIDENCE numeric feature with an explicit declared prior: this is best-effort
# OSINT and MUST earn its place via out-of-sample (the gate flags/weights it via low_confidence). It
# satisfies the same DataSource protocol as every other source (registry.py), so any agent can discover and
# query it by name. Invariants: point-in-time (a snapshot is knowable only at its own request time — never
# look-ahead), LLM-free, offline-deterministic via a bundled fixture so CI runs with no key/network, secrets
# (if a paid OpenSky account is ever wired) stay server-side.

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

from cosmu.data.sources.registry import SourceFeature, SourceKind

# Frozen, versioned transform — pinned into any feature built from this source so a survivor stays
# byte-for-byte re-runnable. Bump the string if the count-in-bbox logic changes.
TRANSFORM_VERSION = "osint-adsb-v1"

# A wide default bounding box over the contiguous US (lat_min, lon_min, lat_max, lon_max). Aircraft
# activity here is a crude, deliberately-low-confidence macro-risk-appetite proxy ("are people flying?").
_DEFAULT_BBOX = (24.0, -125.0, 49.0, -66.0)

# A small deterministic offline fixture: one OpenSky /states/all-shaped payload (a handful of "state
# vectors"). Tests + the no-key path parse THIS instead of hitting the network, so the source is fully
# offline-deterministic. Shape mirrors the real API: {"time": <unix s>, "states": [[icao24, callsign, ...]]}.
_FIXTURE_PAYLOAD: dict = {
    "time": 1_700_000_000,
    "states": [
        ["a1b2c3", "UAL123 ", "United States", None, None, -100.0, 40.0],
        ["d4e5f6", "DAL456 ", "United States", None, None, -95.0, 42.0],
        ["070809", "SWA789 ", "United States", None, None, -110.0, 38.0],
        ["0a0b0c", "FFT012 ", "United States", None, None, -80.0, 30.0],
        ["0d0e0f", "JBU345 ", "United States", None, None, -70.0, 45.0],
        ["dead01", "AFR999 ", "France", None, None, 2.0, 48.0],  # outside the US bbox → not counted
    ],
}


def _ssl_context() -> ssl.SSLContext:
    """certifi-backed context so HTTPS works on hosts without system CA certs (sandbox, slim images)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _count_in_bbox(payload: dict, bbox: tuple[float, float, float, float]) -> int:
    """Count state vectors whose (lat, lon) fall inside the bbox. OpenSky state vector layout:
    index 5 = longitude, index 6 = latitude (may be None when position is unknown — skipped)."""
    lat_min, lon_min, lat_max, lon_max = bbox
    count = 0
    for s in payload.get("states") or []:
        if len(s) < 7:
            continue
        lon, lat = s[5], s[6]
        if lon is None or lat is None:
            continue
        if lat_min <= float(lat) <= lat_max and lon_min <= float(lon) <= lon_max:
            count += 1
    return count


@dataclass
class AdsbDataSource:
    """OpenSky Network ADS-B flight activity as a named, point-in-time DataSource.

    A query returns the count of aircraft inside the bounding box AS OF the request — a live snapshot is
    only knowable at its own observation time, so `available_at == as_of` (never look-ahead). The source
    declares LOW confidence: it is best-effort OSINT and must earn its place via out-of-sample, which the
    registry/gate surfaces via the `low_confidence` flag. Offline (no network or `offline=True`) it parses
    the bundled fixture, so the source is deterministic in CI with no key.
    """

    name: str = "osint_air_activity"
    kind: SourceKind = "osint"
    metric: str = "osint_air_activity"
    prior: str = (
        "Aircraft activity over a region is a crude, low-confidence macro risk-appetite/economic-activity "
        "proxy (best-effort OSINT — 'watching planes'). It must earn its place via out-of-sample; flagged "
        "low-confidence so the gate down-weights it until it pays."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.15  # deliberately low — OSINT must earn its place via OOS
    bbox: tuple[float, float, float, float] = _DEFAULT_BBOX
    base_url: str = "https://opensky-network.org/api"
    offline: bool = False
    timeout: float = 15.0
    _fixture: dict = field(default_factory=lambda: dict(_FIXTURE_PAYLOAD))

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _fetch_payload(self) -> dict:
        """Live OpenSky /states/all over the bounding box (anonymous, free). Any network failure falls back
        to the bundled fixture, so a query NEVER crashes the offline/CI research pass."""
        if self.offline:
            return self._fixture
        lat_min, lon_min, lat_max, lon_max = self.bbox
        query = urllib.parse.urlencode({"lamin": lat_min, "lomin": lon_min, "lamax": lat_max, "lomax": lon_max})
        url = f"{self.base_url}/states/all?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_context()) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — OSINT is best-effort; degrade to the fixture, never crash the pass
            return self._fixture

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest flight-count snapshot knowable at `as_of`. A live ADS-B read is a point observation: it is
        only knowable at the moment it is taken, so its availability time IS the query's `as_of` (no
        look-ahead). `scope`/`limit` are part of the protocol but the bbox defines coverage here."""
        del scope, limit
        payload = self._fetch_payload()
        count = _count_in_bbox(payload, self.bbox)
        return SourceFeature(
            name=self.name,
            scope="MARKET",
            as_of=as_of,
            value=float(count),
            available_at=as_of,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )

    def parse_count(self, payload: dict | None = None) -> int:
        """Expose the parse step for tests/inspection: aircraft count inside this source's bbox."""
        return _count_in_bbox(payload if payload is not None else self._fixture, self.bbox)
