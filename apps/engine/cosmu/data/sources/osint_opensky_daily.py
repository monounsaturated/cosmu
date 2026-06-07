# intent: daily global flight-count from the FREE, anonymous OpenSky Network /flights/all REST endpoint.
# Turns the raw "number of unique ICAO-24 aircraft seen per UTC day" into a point-in-time, availability-
# stamped, LOW-CONFIDENCE numeric feature. Differs from osint_adsb.py (live instantaneous snapshot) in
# that it aggregates a full UTC day in arrears and is knowable only on the NEXT day (available_at = day+1T00:00Z).
#
# PIT CONTRACT (critical — read before touching):
#   flight_date      = the UTC calendar day the flights occurred
#   available_at     = flight_date + 1 day at 00:00 UTC
#                      (OpenSky publishes historical aggregates with ≥1-day latency; we conservatively stamp
#                       next-day so we never claim knowledge before it is realistically available.)
#   as_of semantics  = a query for `as_of` returns the latest day whose available_at ≤ as_of.
#                      That means data for day D is usable only from D+1 00:00 UTC onward.  NO LOOK-AHEAD.
#   gaps             = absent (None value), NOT 0.  A missing day is a data gap, not zero flights.
#
# COVERAGE HONESTY (thin-history risk — FLAGGED):
#   * OpenSky /flights/all free tier: max ~30-day lookback, no guarantee of archival depth.
#   * Rate-limited: anonymous users get ~400 req/day; we issue one REST call per 2-hour window (12 per day).
#   * No revision policy documented by OpenSky.  Assume additions-only (new aircraft decoded post-hoc) but
#     treat any previously stored count as immutable once banked.
#   * History before ~2019 may be absent or incomplete.
#   * This source is THIN and UNTESTED on long histories — confidence 0.10 (extremely low).  The Gate MUST
#     falsify it via out-of-sample; it is registered at tier1 and the low_confidence flag is True.
#
# OFFLINE / CI:
#   `offline=True` (or no network) → bundled deterministic fixture, no HTTP.
#   The fixture deliberately has a gap (day 3 absent) to exercise the "gaps are None, not 0" invariant.

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned, versioned transform — bump whenever aggregation logic changes so a gate-passed survivor stays
# byte-for-byte re-runnable.
TRANSFORM_VERSION = "opensky-daily-flights-v1"

# OpenSky /flights/all accepts UNIX-second `begin` / `end` (window ≤ 7200 s = 2 hours per call).
# We slice a UTC day into 12 two-hour windows and count unique ICAO-24 addresses seen across all slices.
_WINDOW_SEC = 7_200  # 2 hours in seconds
_WINDOWS_PER_DAY = 24 * 3600 // _WINDOW_SEC  # 12

# Deterministic offline fixture.
# Keys are ISO date strings ("YYYY-MM-DD"); values are unique-aircraft counts.
# Day "2024-01-03" is intentionally absent to exercise the gap-is-None (not 0) invariant.
_FIXTURE_DAILY_COUNTS: dict[str, int] = {
    "2024-01-01": 142_831,
    "2024-01-02": 138_206,
    # "2024-01-03" deliberately absent — gap is None, not 0
    "2024-01-04": 141_509,
    "2024-01-05": 143_002,
}

# Fake per-window response shape: list of flight dicts each containing "icao24".
_FIXTURE_WINDOW_FLIGHTS: list[dict] = [
    {"icao24": "a1b2c3", "firstSeen": 1_704_067_200, "lastSeen": 1_704_070_000},
    {"icao24": "d4e5f6", "firstSeen": 1_704_067_300, "lastSeen": 1_704_071_000},
    {"icao24": "a1b2c3", "firstSeen": 1_704_067_400, "lastSeen": 1_704_072_000},  # duplicate → deduped
]


def _ssl_context() -> ssl.SSLContext:
    """certifi-backed TLS context; falls back to system store if certifi is absent."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _day_to_unix(d: date) -> int:
    """UTC midnight of `d` as a Unix timestamp (integer seconds)."""
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


def _fetch_window(base_url: str, begin: int, end: int, timeout: float) -> list[dict]:
    """Fetch /flights/all for one 2-hour window. Returns list of flight dicts (may be empty).
    Any network or HTTP failure returns [] — OSINT is best-effort; gaps are honest."""
    params = urllib.parse.urlencode({"begin": begin, "end": end})
    url = f"{base_url}/flights/all?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 — best-effort OSINT; degrade gracefully
        return []


def _count_unique_aircraft_for_day(base_url: str, flight_date: date, timeout: float) -> int | None:
    """Live path: query 12 two-hour windows across `flight_date` (UTC), return unique ICAO-24 count.
    Returns None if ALL windows fail (no data knowable → gap, not 0)."""
    seen: set[str] = set()
    any_success = False
    start = _day_to_unix(flight_date)
    for i in range(_WINDOWS_PER_DAY):
        begin = start + i * _WINDOW_SEC
        end = begin + _WINDOW_SEC
        flights = _fetch_window(base_url, begin, end, timeout)
        if flights:
            any_success = True
            for f in flights:
                icao = f.get("icao24")
                if icao:
                    seen.add(str(icao).lower())
    return len(seen) if any_success else None


@dataclass
class OpenSkyDailyFlightsSource:
    """OpenSky Network daily global flight count as a named, point-in-time DataSource.

    Each observation answers: "how many unique aircraft (ICAO-24) were seen globally on UTC day D?"
    The answer is published by OpenSky with ≥1-day latency, so available_at = D+1 00:00 UTC.
    A query for `as_of` returns the latest day whose available_at ≤ as_of — never look-ahead.
    Gaps (missing days) yield value=None; they are never filled with 0.

    Coverage risk (flagged):
    - Free/anonymous OpenSky: ~30-day lookback, rate-limited (~400 req/day free tier).
    - History pre-2019 may be absent or incomplete.
    - Confidence 0.10: extremely low; must earn its place via OOS (Gate falsifies or not).
    """

    name: str = "opensky_daily_flights"
    kind: SourceKind = "osint"
    metric: str = "opensky_daily_flights"
    prior: str = (
        "Global daily flight count (unique ICAO-24 aircraft seen on OpenSky Network) is a crude, "
        "LOW-CONFIDENCE macro economic-activity / risk-appetite proxy — 'are people flying today?'. "
        "Coverage is thin (≤30-day free-tier history, rate-limited), history pre-2019 unreliable. "
        "available_at = next day after the flight date (conservative ≥1-day publication lag). "
        "Gaps are None (not 0). Must earn its place via out-of-sample; flag low-confidence always."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.10  # extremely low — thin history OSINT; Gate must falsify
    base_url: str = "https://opensky-network.org/api"
    offline: bool = False
    timeout: float = 20.0
    # inject a fixture dict {iso_date: count} for tests; None = use the bundled default
    _fixture: dict[str, int] = field(default_factory=lambda: dict(_FIXTURE_DAILY_COUNTS))

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _available_at(self, flight_date: date) -> datetime:
        """available_at is the next UTC midnight after the flight date (conservative next-day lag)."""
        next_day = flight_date + timedelta(days=1)
        return datetime(next_day.year, next_day.month, next_day.day, tzinfo=UTC)

    def _latest_knowable_day(self, as_of: datetime) -> date | None:
        """The most recent flight_date whose available_at (= flight_date+1 00:00 UTC) ≤ as_of.
        Returns None if as_of is before the first possible available_at (i.e. day 0+1 = day 1)."""
        # available_at(d) = d+1 00:00 UTC ≤ as_of  ⟺  d ≤ as_of.date() - 1 day
        cutoff = as_of.date() - timedelta(days=1)
        if cutoff < date(2015, 1, 1):  # OpenSky data pre-2015 is effectively absent
            return None
        return cutoff

    def fetch_count_for_date(self, flight_date: date) -> int | None:
        """Return unique aircraft count for `flight_date` (offline → fixture, online → live API).
        None means no data for this day (gap, not zero)."""
        if self.offline:
            key = flight_date.isoformat()
            return self._fixture.get(key)  # absent key → None (gap)
        return _count_unique_aircraft_for_day(self.base_url, flight_date, self.timeout)

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest daily flight count knowable at `as_of`.

        Returns the most recent UTC day whose available_at ≤ as_of.  If that day has no data
        (gap in fixture or all API windows failed) the value is None — NEVER fabricated as 0.
        `scope` and `limit` are part of the protocol; this source is market-wide (scope is ignored).
        """
        del scope, limit  # market-wide; scope is protocol-required but unused
        flight_day = self._latest_knowable_day(as_of)
        if flight_day is None:
            return SourceFeature(
                name=self.name,
                scope="MARKET",
                as_of=as_of,
                value=None,
                available_at=None,
                confidence=self.confidence,
                transform_version=self.transform_version,
                prior=self.prior,
                low_confidence=self.low_confidence,
            )
        count = self.fetch_count_for_date(flight_day)
        return SourceFeature(
            name=self.name,
            scope="MARKET",
            as_of=as_of,
            value=float(count) if count is not None else None,
            available_at=self._available_at(flight_day),
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )

    def parse_count(self, payload: list[dict] | None = None) -> int:
        """Expose the unique-aircraft-count step for tests/inspection. `payload` mirrors one window's
        API response (list of flight dicts with 'icao24'); if None, uses _FIXTURE_WINDOW_FLIGHTS."""
        flights = payload if payload is not None else list(_FIXTURE_WINDOW_FLIGHTS)
        seen: set[str] = set()
        for f in flights:
            icao = f.get("icao24")
            if icao:
                seen.add(str(icao).lower())
        return len(seen)
