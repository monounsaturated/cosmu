# intent: non-causal control feature — deterministic lunar/planetary ephemeris per calendar day.
# Wire honestly and let the Gate falsify it.  NO look-ahead, NO fabrication: every datum is
# knowable at the start of the day itself (the astronomy is deterministic for any calendar date;
# available_at = midnight UTC of the day).  Non-causal source: the sky does not cause price moves
# — this is here purely as a control/noise feature so the Gate can confirm it finds no edge.
# Closed-form math only — no skyfield, no ephem, no external dependency beyond stdlib.

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from cosmu.data.sources.registry import SourceFeature, SourceKind

# Frozen, versioned transform — bump whenever the computation logic changes so a gate-passed
# (very unlikely) survivor stays byte-for-byte re-runnable.
TRANSFORM_VERSION = "astro-ephemeris-v1"

# ─── Closed-form ephemeris helpers ────────────────────────────────────────────────────────────

# J2000.0 epoch in UTC
_J2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)


def _jd_from_dt(dt: datetime) -> float:
    """Julian Day Number for a UTC datetime (fractional, continuous)."""
    delta = dt - _J2000
    return 2_451_545.0 + delta.total_seconds() / 86_400.0


def _lunar_phase_fraction(jd: float) -> float:
    """Illuminated fraction of the Moon's disc [0, 1].

    Uses a simplified analytical model accurate to ~2 % over multi-century spans.
    Source: Jean Meeus, "Astronomical Algorithms" (2nd ed.), Chapter 49 (Phase Angle).

    Phase fraction = (1 - cos(phase_angle)) / 2  where phase_angle is the angular
    separation between the Moon's ecliptic longitude and the Sun's ecliptic longitude.
    0 = new moon, 0.5 = quarter, 1 = full moon.

    Non-causal control feature — the Moon does not cause price moves.
    """
    # Days since J2000.0
    T = (jd - 2_451_545.0) / 36_525.0  # Julian centuries

    # Sun's mean anomaly (radians)
    M_sun = math.radians(357.5291092 + 35_999.0502909 * T)
    # Sun's equation of centre
    sun_eq_ctr = (1.9146 - 0.004817 * T - 0.000014 * T * T) * math.sin(M_sun)
    sun_eq_ctr += (0.019993 - 0.000101 * T) * math.sin(2 * M_sun)
    sun_eq_ctr += 0.000290 * math.sin(3 * M_sun)
    # Sun's ecliptic longitude (degrees)
    sun_lon = (280.46646 + 36_000.76983 * T + sun_eq_ctr) % 360.0

    # Moon's mean longitude (degrees)
    moon_lon_mean = (218.3165 + 481_267.8813 * T) % 360.0
    # Moon's mean anomaly (radians)
    M_moon = math.radians((134.9634 + 477_198.8676 * T) % 360.0)
    # Moon's elongation (radians)
    D = math.radians((297.8502 + 445_267.1115 * T) % 360.0)
    # Moon's argument of latitude (radians) — unused here, retained for reference
    # F = math.radians((93.2721 + 483_202.0175 * T) % 360.0)

    # Moon's longitude correction (simplified first-order)
    moon_eq_ctr = (6.2886 * math.sin(M_moon)
                   + 1.2740 * math.sin(2 * D - M_moon)
                   + 0.6583 * math.sin(2 * D)
                   + 0.2136 * math.sin(2 * M_moon)
                   - 0.1851 * math.sin(M_sun)
                   - 0.1143 * math.sin(2 * D - M_sun))

    moon_lon = (moon_lon_mean + moon_eq_ctr) % 360.0

    # Phase angle = difference in ecliptic longitude
    phase_angle_deg = (moon_lon - sun_lon) % 360.0
    phase_angle_rad = math.radians(phase_angle_deg)

    # Illuminated fraction
    return (1.0 - math.cos(phase_angle_rad)) / 2.0


def _sun_ecliptic_longitude_deg(jd: float) -> float:
    """Sun's apparent ecliptic longitude in degrees [0, 360).

    Simplified VSOP87 truncation — error < 0.01° over 1800–2200.
    Non-causal control feature.
    """
    T = (jd - 2_451_545.0) / 36_525.0
    M = math.radians(357.5291092 + 35_999.0502909 * T)
    lon = (280.46646
           + 36_000.76983 * T
           + (1.9146 - 0.004817 * T) * math.sin(M)
           + (0.019993 - 0.000101 * T) * math.sin(2 * M)
           + 0.000290 * math.sin(3 * M))
    return lon % 360.0


def _jupiter_ecliptic_longitude_deg(jd: float) -> float:
    """Jupiter's mean ecliptic longitude in degrees [0, 360) — simplified VSOP87 leading terms.

    Accuracy ~0.3° over the period 1950–2050.
    Non-causal control feature.
    """
    T = (jd - 2_451_545.0) / 36_525.0
    # Mean longitude: L0 + L1*T (secular term from VSOP87 L series)
    # L0 = 34.351484°, L1 = 3034.905675°/century (Meeus T9.a)
    lon = 34.351484 + 3034.905675 * T
    # Leading equation-of-centre correction
    M = math.radians((20.9 + 3034.906 * T) % 360.0)
    lon += 5.555 * math.sin(M) + 0.168 * math.sin(2 * M)
    return lon % 360.0


def _saturn_ecliptic_longitude_deg(jd: float) -> float:
    """Saturn's mean ecliptic longitude in degrees [0, 360) — simplified VSOP87 leading terms.

    Accuracy ~0.5° over the period 1950–2050.
    Non-causal control feature.
    """
    T = (jd - 2_451_545.0) / 36_525.0
    # L0 = 50.077444°, L1 = 1222.113794°/century (Meeus T9.a)
    lon = 50.077444 + 1222.113794 * T
    M = math.radians((317.0 + 1222.114 * T) % 360.0)
    lon += 6.393 * math.sin(M) + 0.130 * math.sin(2 * M)
    return lon % 360.0


# Sun–Jupiter angular separation (synodic), clamped to [0, 180]
def _sun_jupiter_aspect_deg(jd: float) -> float:
    """Absolute angular separation between the Sun and Jupiter [0, 180].

    A 0° aspect is conjunction; 180° is opposition.
    Non-causal control feature.
    """
    diff = abs(_sun_ecliptic_longitude_deg(jd) - _jupiter_ecliptic_longitude_deg(jd))
    if diff > 180.0:
        diff = 360.0 - diff
    return diff


# ─── AstroEphemerisProvider — AltDataProvider seam ────────────────────────────────────────────

@dataclass
class AstroEphemerisProvider:
    """Deterministic daily ephemeris provider (pure stdlib, no network, no API key).

    Non-causal control feature — wire honestly; the Gate will falsify it.

    Supported metrics:
        lunar_phase_fraction  — Moon illuminated fraction [0, 1]. 0 = new, 1 = full.
        sun_longitude_deg     — Sun ecliptic longitude [0, 360). Proxy for calendar season.
        jupiter_longitude_deg — Jupiter ecliptic longitude [0, 360). ~12-year cycle.
        saturn_longitude_deg  — Saturn ecliptic longitude [0, 360). ~29-year cycle.
        sun_jupiter_aspect    — Sun–Jupiter angular separation [0, 180]. 0 = conjunction.

    Point-in-time contract: available_at = midnight UTC of the day (the geometry is knowable
    at the start of any calendar day — deterministic, no revision, no look-ahead).
    A gap is absent, not fabricated as 0.
    """

    _SUPPORTED: frozenset[str] = frozenset({
        "lunar_phase_fraction",
        "sun_longitude_deg",
        "jupiter_longitude_deg",
        "saturn_longitude_deg",
        "sun_jupiter_aspect",
    })

    def _compute_for_day(self, day: date, metric: str) -> float:
        """Compute ephemeris value for a calendar day (midnight UTC)."""
        dt = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=UTC)
        jd = _jd_from_dt(dt)
        if metric == "lunar_phase_fraction":
            return _lunar_phase_fraction(jd)
        if metric == "sun_longitude_deg":
            return _sun_ecliptic_longitude_deg(jd)
        if metric == "jupiter_longitude_deg":
            return _jupiter_ecliptic_longitude_deg(jd)
        if metric == "saturn_longitude_deg":
            return _saturn_ecliptic_longitude_deg(jd)
        if metric == "sun_jupiter_aspect":
            return _sun_jupiter_aspect_deg(jd)
        raise ValueError(f"Unknown astro metric: {metric!r}")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list:
        """Return ascending AltDataPoints for the requested metric over the last `limit` days.

        `symbol` is ignored (the sky is market-wide); the caller supplies it to match the
        AltDataProvider protocol.  A gap → absent, never fabricated as 0.
        available_at = midnight UTC of the day (deterministic, knowable at day start — no look-ahead).
        """
        from cosmu.data.providers._types import AltDataPoint

        if metric not in self._SUPPORTED:
            return []

        today = datetime.now(tz=UTC).date()
        out: list[AltDataPoint] = []
        for i in range(limit - 1, -1, -1):
            day = today - timedelta(days=i)
            available_at = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=UTC)
            value = self._compute_for_day(day, metric)
            out.append(AltDataPoint(ts=available_at, available_at=available_at, value=value))
        return out


# ─── AstroEphemerisSource — DataSource protocol seam ──────────────────────────────────────────

@dataclass
class AstroEphemerisSource:
    """Named, point-in-time DataSource wrapping AstroEphemerisProvider for one metric.

    Non-causal control feature — wire honestly; the Gate will falsify it.

    Availability: the day's midnight UTC (the geometry is deterministic and knowable at
    the start of any calendar date — no look-ahead, no revision, no fabrication).
    Confidence is deliberately low: non-causal OSINT must earn its place via OOS.

    Docstring tag: non-causal control feature.
    """

    name: str
    metric: str
    prior: str
    kind: SourceKind = "osint"
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.1  # deliberately very low — non-causal, must earn its place via OOS
    _provider: AstroEphemerisProvider | None = None

    def __post_init__(self) -> None:
        if self._provider is None:
            self._provider = AstroEphemerisProvider()

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def query(self, scope: str, as_of: datetime, *, limit: int = 365) -> SourceFeature:
        """Latest ephemeris value knowable at `as_of` (midnight UTC of the as_of day).

        The ephemeris is fully deterministic so we compute directly for the as_of date
        (no rolling window needed — any date in history is equally computable).
        available_at = midnight UTC of the as_of date (the geometry is knowable at day-start;
        no look-ahead).  If as_of falls before a sensible epoch (year < 1000) we return None.

        Non-causal control feature — the Gate is expected to reject it; wired honestly so it
        has the chance to do so without any fabrication or look-ahead contaminating the test.
        `scope` / `limit` are part of the protocol but unused (sky is market-wide, computation
        is O(1) per point — no rolling window).
        """
        del scope, limit  # market-wide; computation is O(1) — no window needed
        # Guard: do not compute for unreasonably ancient dates (model accuracy degrades outside
        # ~1000–3000 CE; treat as "no data" to avoid fabricating garbage values).
        if as_of.year < 1000 or as_of.year > 3000:
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
        # available_at = midnight UTC of the as_of day (deterministic, knowable at day-start)
        available_at = datetime(as_of.year, as_of.month, as_of.day, 0, 0, 0, tzinfo=UTC)
        provider = self._provider or AstroEphemerisProvider()
        value = provider._compute_for_day(available_at.date(), self.metric)
        return SourceFeature(
            name=self.name,
            scope="MARKET",
            as_of=as_of,
            value=float(value),
            available_at=available_at,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )


# ─── Convenience factory — all astro features at once ─────────────────────────────────────────

_ASTRO_FEATURES: dict[str, dict[str, str]] = {
    "astro_lunar_phase": {
        "metric": "lunar_phase_fraction",
        "prior": (
            "NON-CAUSAL CONTROL FEATURE — lunar phase fraction [0, 1]. 0 = new moon, 1 = full moon. "
            "Wired honestly; the Gate is expected to reject it. Deterministic; no look-ahead, no revision."
        ),
    },
    "astro_sun_longitude": {
        "metric": "sun_longitude_deg",
        "prior": (
            "NON-CAUSAL CONTROL FEATURE — Sun ecliptic longitude [0, 360). Proxy for calendar season. "
            "Wired honestly; the Gate is expected to reject it. Deterministic; no look-ahead, no revision."
        ),
    },
    "astro_jupiter_longitude": {
        "metric": "jupiter_longitude_deg",
        "prior": (
            "NON-CAUSAL CONTROL FEATURE — Jupiter ecliptic longitude [0, 360). ~12-year cycle. "
            "Wired honestly; the Gate is expected to reject it. Deterministic; no look-ahead, no revision."
        ),
    },
    "astro_saturn_longitude": {
        "metric": "saturn_longitude_deg",
        "prior": (
            "NON-CAUSAL CONTROL FEATURE — Saturn ecliptic longitude [0, 360). ~29-year cycle. "
            "Wired honestly; the Gate is expected to reject it. Deterministic; no look-ahead, no revision."
        ),
    },
    "astro_sun_jupiter_aspect": {
        "metric": "sun_jupiter_aspect",
        "prior": (
            "NON-CAUSAL CONTROL FEATURE — Sun–Jupiter angular separation [0, 180] degrees. "
            "0 = conjunction, 180 = opposition. ~12-year synodic cycle. "
            "Wired honestly; the Gate is expected to reject it. Deterministic; no look-ahead, no revision."
        ),
    },
}


def make_astro_sources() -> list[AstroEphemerisSource]:
    """Return one AstroEphemerisSource per astro feature, sharing a single provider instance.

    Non-causal control features — wire honestly, let the Gate falsify them.
    """
    provider = AstroEphemerisProvider()
    return [
        AstroEphemerisSource(
            name=name,
            metric=meta["metric"],
            prior=meta["prior"],
            _provider=provider,
        )
        for name, meta in _ASTRO_FEATURES.items()
    ]


__all__ = [
    "TRANSFORM_VERSION",
    "AstroEphemerisProvider",
    "AstroEphemerisSource",
    "make_astro_sources",
    "_lunar_phase_fraction",
    "_sun_ecliptic_longitude_deg",
    "_jupiter_ecliptic_longitude_deg",
    "_saturn_ecliptic_longitude_deg",
    "_sun_jupiter_aspect_deg",
    "_jd_from_dt",
]
