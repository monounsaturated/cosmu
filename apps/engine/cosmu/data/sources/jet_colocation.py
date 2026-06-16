# intent: corporate-jet CO-LOCATION intensity per US-equity ticker, from the FREE, anonymous OpenSky
# Network /flights/aircraft REST endpoint. When two PUBLICLY LISTED companies' corporate aircraft land at
# the SAME airport around the same time it is a weak, noisy, but causally-PLAUSIBLE proxy for deal proximity
# (M&A talks, partnership, JV, board meeting). This turns that idea into a point-in-time, availability-
# stamped, LOW-CONFIDENCE numeric feature per ticker. This is a genuine hypothesis the Gate must FALSIFY
# out-of-sample — it is NOT a non-causal control.
#
# Differs from osint_opensky_daily.py (the MARKET-WIDE daily global flight COUNT) in that this is PER-TICKER:
# it counts how often a tracked company's aircraft co-located with another tracked company's aircraft.
#
# PIT CONTRACT (critical — read before touching):
#   obs_day          = the UTC calendar day the co-location events occurred
#   available_at     = obs_day + 1 day at 00:00 UTC
#                      (OpenSky publishes per-aircraft arrival history with >=1-day latency; we conservatively
#                       stamp next-day so we never claim knowledge before it is realistically available.)
#   as_of semantics  = a query for `as_of` returns the latest day whose available_at <= as_of.
#                      The latest knowable obs_day = as_of.date() - 1 day.  NO LOOK-AHEAD.
#   window           = the signal is a trailing-window aggregate (default 30 days) ENDING at the latest
#                      knowable day; we sum distinct (day, airport) co-location events across the window.
#   gaps             = a ticker NOT in the tracked aircraft map, or no arrivals knowable for it, yields
#                      value=None (NOT 0). A missing day is a data gap, never zero co-locations.
#
# COVERAGE HONESTY (thin + partial — FLAGGED):
#   * The tracked-aircraft map (_AIRCRAFT_BY_TICKER) is an ILLUSTRATIVE, EXTENSIBLE SEED of liquid US
#     large-caps -> corporate-aircraft ICAO-24 hex ids. Coverage is INTENTIONALLY PARTIAL. A ticker that is
#     not in the map => value None, never 0 (an honest "we don't track this", not "no deals happened").
#   * The hex ids below are PLAUSIBLE-LOOKING LOWERCASE PLACEHOLDERS. Real tail-number -> ICAO-24 mappings
#     are operator-extensible (e.g. via the FAA registry / OpenSky metadata); swap them in to expand coverage.
#   * OpenSky /flights/aircraft free tier: thin lookback, rate-limited, no documented revision policy.
#   * This source is THIN and UNTESTED on long histories — confidence 0.12 (extremely low). The Gate MUST
#     falsify it via out-of-sample; it is registered at tier1 and the low_confidence flag is True.
#
# OFFLINE / CI:
#   `offline=True` (or no network / any parse failure) -> bundled deterministic fixture, NO HTTP, NEVER an
#   exception. The fixture has same-airport co-location days (=> events), different-airport days (=> no
#   event), and a deliberately ABSENT day to exercise the "gaps are None, not 0" invariant.

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned, versioned transform — bump whenever the co-location aggregation logic changes so a gate-passed
# survivor stays byte-for-byte re-runnable.
TRANSFORM_VERSION = "jet-colocation-v1"

# Default trailing window (UTC days) over which co-location events are summed, ending at the latest knowable
# day. A wider window catches slow-moving deal travel; a narrower one is noisier.
_DEFAULT_WINDOW_DAYS = 30

# ILLUSTRATIVE, EXTENSIBLE SEED: ~10 liquid US large-cap tickers -> their corporate-aircraft ICAO-24 hex ids.
# These hex ids are PLAUSIBLE-LOOKING LOWERCASE PLACEHOLDERS, not real registrations. Real tail-number ->
# ICAO-24 mappings are OPERATOR-EXTENSIBLE: add the company and its decoded hex ids to widen coverage.
# Coverage is INTENTIONALLY PARTIAL — a ticker absent from this map yields value None (never a fabricated 0).
_AIRCRAFT_BY_TICKER: dict[str, list[str]] = {
    "AAPL": ["a1b2c3", "a1b2c4"],
    "MSFT": ["b2c3d4"],
    "GOOGL": ["c3d4e5", "c3d4e6"],
    "AMZN": ["d4e5f6"],
    "META": ["e5f6a7"],
    "NVDA": ["f6a7b8"],
    "TSLA": ["a7b8c9"],
    "JPM": ["b8c9d0"],
    "BRK.B": ["c9d0e1"],
    "DIS": ["d0e1f2"],
}

# Deterministic offline fixture: per-day raw arrivals {iso_day: {icao24: airport_icao}}.
# Designed to exercise co-location detection:
#   2024-01-01: AAPL aircraft (a1b2c3) and MSFT aircraft (b2c3d4) BOTH land at KSJC  => co-location event(s)
#   2024-01-02: AAPL at KSJC, MSFT at KSEA (different airports)                       => NO event
#   2024-01-03: DELIBERATELY ABSENT                                                   => gap => None
#   2024-01-04: AAPL (a1b2c3) + GOOGL (c3d4e5) at KTEB; AAPL second jet (a1b2c4) at KLAX alone => 1 event for AAPL
#   2024-01-05: only AMZN (d4e5f6) lands at KSEA (lone aircraft)                       => NO event
_FIXTURE_ARRIVALS_BY_DAY: dict[str, dict[str, str]] = {
    "2024-01-01": {"a1b2c3": "KSJC", "b2c3d4": "KSJC"},
    "2024-01-02": {"a1b2c3": "KSJC", "b2c3d4": "KSEA"},
    # "2024-01-03" deliberately absent — gap is None, not 0
    "2024-01-04": {"a1b2c3": "KTEB", "c3d4e5": "KTEB", "a1b2c4": "KLAX"},
    "2024-01-05": {"d4e5f6": "KSEA"},
}

# A second fixture path: per-(ticker, iso_day) PRECOMPUTED co-location event counts. Lets a test exercise the
# window-aggregation step directly without re-deriving from raw arrivals. Mirrors _FIXTURE_ARRIVALS_BY_DAY.
_FIXTURE_COUNTS_BY_TICKER_DAY: dict[str, dict[str, int]] = {
    "AAPL": {"2024-01-01": 1, "2024-01-02": 0, "2024-01-04": 1, "2024-01-05": 0},
    "MSFT": {"2024-01-01": 1, "2024-01-02": 0, "2024-01-04": 0, "2024-01-05": 0},
    "GOOGL": {"2024-01-01": 0, "2024-01-02": 0, "2024-01-04": 1, "2024-01-05": 0},
}


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


def _ticker_of_icao24(icao24: str) -> str | None:
    """Reverse-lookup: which tracked ticker owns this ICAO-24 hex id (case-insensitive)? None if untracked."""
    target = icao24.lower()
    for ticker, hexes in _AIRCRAFT_BY_TICKER.items():
        if target in (h.lower() for h in hexes):
            return ticker
    return None


def detect_colocation_events(arrivals_by_ticker: dict[str, dict[str, str]], target: str) -> int:
    """PURE, testable core: count co-location events for `target` on ONE day.

    `arrivals_by_ticker` maps ticker -> {icao24: airport_icao} for the aircraft (of that ticker) that arrived
    somewhere that day. Returns the number of DISTINCT airports at which `target` co-located with at least one
    OTHER tracked ticker's aircraft that day.

    - A target aircraft landing at the same airport as another tracked ticker => that airport counts ONCE
      (even if multiple other companies / multiple jets share it — it is one (day, airport) co-location).
    - A lone target aircraft (no other tracked ticker at its airport) => contributes 0.
    - A target with no arrivals (absent from the map) => 0.
    No network, fully deterministic.
    """
    target_arr = arrivals_by_ticker.get(target)
    if not target_arr:
        return 0
    # Airports where OTHER tracked tickers were present that day.
    other_airports: set[str] = set()
    for ticker, arr in arrivals_by_ticker.items():
        if ticker == target:
            continue
        other_airports.update(arr.values())
    # Distinct airports at which the target also landed.
    target_airports = set(target_arr.values())
    return len(target_airports & other_airports)


def _arrivals_by_ticker_for_day(arrivals: dict[str, str]) -> dict[str, dict[str, str]]:
    """Group one day's raw {icao24: airport} arrivals into {ticker: {icao24: airport}} for tracked aircraft.
    Untracked ICAO-24 ids are dropped (they cannot be attributed to a listed company)."""
    grouped: dict[str, dict[str, str]] = defaultdict(dict)
    for icao24, airport in arrivals.items():
        ticker = _ticker_of_icao24(icao24)
        if ticker is not None and airport:
            grouped[ticker][icao24] = airport
    return dict(grouped)


def _fetch_aircraft_arrivals(base_url: str, icao24: str, begin: int, end: int, timeout: float) -> list[dict]:
    """Fetch /flights/aircraft for one aircraft over [begin, end). Returns a list of flight dicts (may be
    empty). Any network / HTTP / parse failure returns [] — OSINT is best-effort; gaps are honest."""
    params = urllib.parse.urlencode({"icao24": icao24, "begin": begin, "end": end})
    url = f"{base_url}/flights/aircraft?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 — best-effort OSINT; degrade gracefully
        return []


def _live_arrivals_for_day(base_url: str, obs_day: date, timeout: float) -> dict[str, str] | None:
    """Live path: for every tracked aircraft, fetch its arrivals on `obs_day` (UTC) and keep the LAST
    estArrivalAirport seen that day. Returns {icao24: airport} for aircraft that arrived somewhere.
    Returns None if EVERY tracked aircraft query failed (no data knowable => gap, not an empty day)."""
    begin = _day_to_unix(obs_day)
    end = begin + 86_400
    arrivals: dict[str, str] = {}
    any_success = False
    for hexes in _AIRCRAFT_BY_TICKER.values():
        for icao24 in hexes:
            flights = _fetch_aircraft_arrivals(base_url, icao24, begin, end, timeout)
            if not flights:
                continue
            any_success = True
            for f in flights:
                airport = f.get("estArrivalAirport")
                if airport:
                    arrivals[icao24.lower()] = str(airport)
    return arrivals if any_success else None


@dataclass
class JetColocationSource:
    """Corporate-jet co-location intensity per US-equity ticker as a named, point-in-time DataSource.

    Each observation answers: "over the trailing window ending at the latest knowable UTC day, on how many
    distinct (day, airport) pairs did ticker T's corporate aircraft co-locate with ANOTHER tracked company's
    aircraft?" Higher = more inter-company travel proximity (a weak deal-proximity proxy).

    The answer is published by OpenSky with >=1-day latency, so the latest knowable obs_day is
    as_of.date() - 1 day, and available_at = obs_day + 1 00:00 UTC. NEVER look-ahead.

    Coverage / honesty (flagged):
    - Per-ticker. A ticker NOT in the tracked-aircraft seed map => value None (NOT 0).
    - The seed map is illustrative & operator-extensible; hex ids are placeholders.
    - Confidence 0.12: extremely low. CAUSALLY-PLAUSIBLE hypothesis, not a non-causal control; the Gate must
      falsify it out-of-sample.
    """

    name: str = "jet_colocation"
    kind: SourceKind = "osint"
    metric: str = "jet_colocation"
    prior: str = (
        "Corporate-jet CO-LOCATION (two publicly-listed companies' aircraft landing at the same airport "
        "around the same time) is a weak, noisy, but causally-PLAUSIBLE proxy for deal proximity — M&A "
        "talks, partnership, JV, board meeting. This is a genuine hypothesis, NOT a non-causal control. "
        "Coverage is thin and INTENTIONALLY PARTIAL (an illustrative, operator-extensible seed of tracked "
        "aircraft); a ticker we do not track yields None (never 0). available_at = next day after the "
        "observation day (conservative >=1-day publication lag). LOW-CONFIDENCE: must earn its place via "
        "out-of-sample; flag low-confidence always."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.12  # extremely low — thin/partial-coverage OSINT; Gate must falsify
    base_url: str = "https://opensky-network.org/api"
    offline: bool = False
    timeout: float = 20.0
    window_days: int = _DEFAULT_WINDOW_DAYS
    # inject a fixture {iso_day: {icao24: airport}} for tests; None = use the bundled default
    _fixture: dict[str, dict[str, str]] = field(
        default_factory=lambda: {k: dict(v) for k, v in _FIXTURE_ARRIVALS_BY_DAY.items()}
    )

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _available_at(self, obs_day: date) -> datetime:
        """available_at is the next UTC midnight after the observation day (conservative next-day lag)."""
        next_day = obs_day + timedelta(days=1)
        return datetime(next_day.year, next_day.month, next_day.day, tzinfo=UTC)

    def _latest_knowable_day(self, as_of: datetime) -> date | None:
        """The most recent obs_day whose available_at (= obs_day+1 00:00 UTC) <= as_of.
        Returns None if as_of is before the first possible available_at."""
        # available_at(d) = d+1 00:00 UTC <= as_of  <=>  d <= (as_of in UTC).date() - 1 day.
        # Normalize to UTC FIRST: a tz-aware as_of ahead of UTC (e.g. UTC+14 just after local midnight) would
        # otherwise have as_of.date() one calendar day ahead of its true UTC date, making us claim a day
        # knowable whose UTC-midnight available_at is still in the future => look-ahead. A naive as_of is
        # assumed already-UTC (the codebase convention).
        utc_as_of = as_of.astimezone(UTC) if as_of.tzinfo is not None else as_of
        cutoff = utc_as_of.date() - timedelta(days=1)
        if cutoff < date(2015, 1, 1):  # OpenSky data pre-2015 is effectively absent
            return None
        return cutoff

    def _arrivals_for_day(self, obs_day: date) -> dict[str, str] | None:
        """Raw {icao24: airport} arrivals for `obs_day` (offline -> fixture, online -> live API).
        None means no data knowable for this day (gap, not an empty day)."""
        if self.offline:
            return self._fixture.get(obs_day.isoformat())  # absent key -> None (gap)
        return _live_arrivals_for_day(self.base_url, obs_day, self.timeout)

    def colocation_events_for_day(self, target: str, obs_day: date) -> int | None:
        """Co-location event count for `target` on one `obs_day`. None means the day is a gap (no data) OR
        the target is not tracked; an int (incl. 0) means we HAD data for the day."""
        if target not in _AIRCRAFT_BY_TICKER:
            return None
        arrivals = self._arrivals_for_day(obs_day)
        if arrivals is None:
            return None  # gap day — None, not 0
        grouped = _arrivals_by_ticker_for_day(arrivals)
        return detect_colocation_events(grouped, target)

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Trailing-window co-location intensity for ticker `scope` knowable at `as_of`.

        Sums distinct (day, airport) co-location events over the `window_days` trailing window ending at the
        latest UTC day whose available_at <= as_of. A ticker we do not track, or a window in which NO day had
        any knowable data, yields value=None — NEVER fabricated as 0. NO look-ahead.
        """
        del limit  # protocol-required; the window length is fixed by window_days
        latest_day = self._latest_knowable_day(as_of)
        if latest_day is None or scope not in _AIRCRAFT_BY_TICKER:
            return SourceFeature(
                name=self.name,
                scope=scope,
                as_of=as_of,
                value=None,
                available_at=None,
                confidence=self.confidence,
                transform_version=self.transform_version,
                prior=self.prior,
                low_confidence=self.low_confidence,
            )
        total = 0
        any_data = False
        for i in range(self.window_days):
            obs_day = latest_day - timedelta(days=i)
            events = self.colocation_events_for_day(scope, obs_day)
            if events is not None:
                any_data = True
                total += events
        return SourceFeature(
            name=self.name,
            scope=scope,
            as_of=as_of,
            value=float(total) if any_data else None,  # no knowable day in window => gap => None, not 0
            available_at=self._available_at(latest_day) if any_data else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )
