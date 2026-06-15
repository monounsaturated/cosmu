# intent: PHYSICS-grounded solar-system geometry features that financial-astrology folklore IGNORES.
# These are NOT zodiac/aspect heuristics — they are the real solar-planetary-coupling observables that
# appear in the solar-physics literature (Jose 1965; Charvatova's solar inertial motion; Landscheidt):
#
#   * SOLAR INERTIAL MOTION (SIM): the Sun's displacement from the solar-system barycenter, driven mostly
#     by Jupiter+Saturn. Amplitude ~2 solar radii. Charvatova links its "ordered/disordered" epochs to
#     solar activity. We emit the barycentric offset magnitude, its rate of change, and the Sun's
#     barycentric orbital angular velocity.
#   * TOTAL PLANETARY ANGULAR MOMENTUM (the Jose ~178.7-yr cycle): L = sum m_i (r_i x v_i) about the Sun.
#     Jose (1965) and Landscheidt argued its rate-of-change (torque dL/dt) modulates solar output. We emit
#     |L|, L_z, and the torque |dL/dt| — and short harmonics (the J-S 19.86yr, J-S-synodic terms) that are
#     resolvable in a ~10yr crypto / ~10yr equity window.
#   * HELIOCENTRIC vs GEOCENTRIC geometry already partly in astro_features_deep; here we add the
#     heliocentric Jupiter-Saturn separation (the real ~19.86yr cycle, NOT the geocentric one) and the
#     barycentric phase.
#   * LUNAR TIDAL (perigee/apogee) is in astro_features_deep; here we add the lunar tidal-FORCE proxy
#     (1/d^3) and the combined sun+moon syzygy tidal index (spring/neap), which is the genuine gravitational
#     tide, not the illumination.
#   * PLANETARY DECLINATION / out-of-bounds is in astro_features_deep; here we add the heliocentric
#     latitude excursion of the giant planets (their nodal crossings) for completeness.
#
# DETERMINISM / POINT-IN-TIME: every value is computed from ephem (libastro/XEphem, VSOP87-class) at
# midnight UTC of the day. Velocities use a BACKWARD one-day difference (previous day), so nothing is
# knowable only in the future. No price, no revision, no look-ahead. This is a NON-CAUSAL physics control
# panel: the hypothesis under test is whether any solar-planetary observable maps to returns/vol ABOVE a
# proper (autocorrelation-preserving) null. The sky almost certainly does not move Bitcoin; this exists to
# be falsified rigorously.

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import ephem
import numpy as np
import pandas as pd

_DEG = 180.0 / math.pi
_AU_M = ephem.meters_per_au

# Planet masses in SOLAR MASSES (JPL DE values). Jupiter dominates (~71% of planetary mass), so the SIM
# and angular-momentum signals are essentially a Jupiter+Saturn story with smaller outer-planet terms.
_MASS_SOLAR: dict[str, float] = {
    "mercury": 1.6601e-7,
    "venus": 2.4478e-6,
    "earth": 3.0035e-6,
    "mars": 3.2272e-7,
    "jupiter": 9.5479e-4,
    "saturn": 2.8588e-4,
    "uranus": 4.3662e-5,
    "neptune": 5.1514e-5,
    "pluto": 6.58e-9,
}

_PLANETS: dict[str, type] = {
    "mercury": ephem.Mercury,
    "venus": ephem.Venus,
    "mars": ephem.Mars,
    "jupiter": ephem.Jupiter,
    "saturn": ephem.Saturn,
    "uranus": ephem.Uranus,
    "neptune": ephem.Neptune,
    "pluto": ephem.Pluto,
}
# Earth's heliocentric position from the Sun body's geocentric vector (Sun.hlon is undefined; use Earth =
# -Sun_geocentric direction at Sun.earth_distance). We approximate Earth heliocentric = opposite the Sun.


def _ephem_date(dt: datetime) -> ephem.Date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return ephem.Date(datetime(dt.year, dt.month, dt.day, 0, 0, 0))


def _helio_xyz(cls: type, d: ephem.Date) -> np.ndarray:
    """Heliocentric ecliptic cartesian (AU) for a planet body at instant d, from (r, hlon, hlat)."""
    b = cls(d)
    r = float(b.sun_distance)
    lon = float(b.hlon)
    lat = float(b.hlat)
    cl = math.cos(lat)
    return np.array([r * cl * math.cos(lon), r * cl * math.sin(lon), r * math.sin(lat)])


def _earth_helio_xyz(d: ephem.Date) -> np.ndarray:
    """Earth's heliocentric position = the Sun's geocentric direction reversed, scaled by earth_distance."""
    s = ephem.Sun(d)
    ec = ephem.Ecliptic(s)
    lon = float(ec.lon) + math.pi  # Earth is opposite the Sun as seen geocentrically
    lat = -float(ec.lat)
    r = float(s.earth_distance)
    cl = math.cos(lat)
    return np.array([r * cl * math.cos(lon), r * cl * math.sin(lon), r * math.sin(lat)])


def _all_helio(d: ephem.Date) -> dict[str, np.ndarray]:
    out = {nm: _helio_xyz(cls, d) for nm, cls in _PLANETS.items()}
    out["earth"] = _earth_helio_xyz(d)
    return out


def _barycenter_offset(pos: dict[str, np.ndarray]) -> np.ndarray:
    """Solar-system barycenter position relative to the Sun (AU). Sun-from-barycenter is the negative."""
    num = np.zeros(3)
    msum = 1.0  # Sun mass
    for nm, r in pos.items():
        m = _MASS_SOLAR[nm]
        num += m * r
        msum += m
    return num / msum


def _total_angular_momentum(pos: dict[str, np.ndarray], vel: dict[str, np.ndarray]) -> np.ndarray:
    """Total planetary orbital angular momentum about the Sun: L = sum m_i (r_i x v_i). Units arbitrary but
    consistent (AU, AU/day, solar masses) — only its variation/harmonics matter, not the absolute scale."""
    L = np.zeros(3)
    for nm in pos:
        L += _MASS_SOLAR[nm] * np.cross(pos[nm], vel[nm])
    return L


def _compute_day(dt: datetime) -> dict[str, float]:
    d = _ephem_date(dt)
    d_prev = _ephem_date(dt - timedelta(days=1))
    row: dict[str, float] = {}

    pos = _all_helio(d)
    pos_prev = _all_helio(d_prev)
    vel = {nm: pos[nm] - pos_prev[nm] for nm in pos}  # AU/day, backward difference (PIT-safe)

    # ── Solar inertial motion (barycentric offset of the Sun) ──────────────────────────────
    bary = _barycenter_offset(pos)
    bary_prev = _barycenter_offset(pos_prev)
    off = float(np.linalg.norm(bary))
    off_prev = float(np.linalg.norm(bary_prev))
    row["sim_offset_au"] = off                              # |Sun-barycenter| distance
    row["sim_offset_solar_radii"] = off / 0.004650467      # in solar radii (the literature's unit)
    row["sim_offset_rate"] = off - off_prev                # d|offset|/dt (expansion/contraction)
    # Barycentric angular velocity of the Sun (how fast the Sun loops the barycenter) — Charvatova's
    # "ordered vs disordered" motion is about this turning rate.
    ang = math.atan2(bary[1], bary[0])
    ang_prev = math.atan2(bary_prev[1], bary_prev[0])
    dang = ((ang - ang_prev + math.pi) % (2 * math.pi)) - math.pi
    row["sim_angular_velocity"] = dang                     # rad/day of the Sun about the barycenter
    row["sim_offset_x"] = float(bary[0])
    row["sim_offset_y"] = float(bary[1])

    # ── Total planetary angular momentum (Jose cycle driver) ───────────────────────────────
    L = _total_angular_momentum(pos, vel)
    L_prev = _total_angular_momentum(pos_prev, {nm: pos_prev[nm] - _all_helio(_ephem_date(dt - timedelta(days=2)))[nm] for nm in pos})
    row["amom_total"] = float(np.linalg.norm(L))
    row["amom_z"] = float(L[2])
    # Torque |dL/dt| — Landscheidt's claimed solar-activity driver.
    row["amom_torque"] = float(np.linalg.norm(L - L_prev))

    # ── Heliocentric Jupiter-Saturn (the REAL 19.86yr cycle, not geocentric) ───────────────
    jl = math.atan2(pos["jupiter"][1], pos["jupiter"][0])
    sl = math.atan2(pos["saturn"][1], pos["saturn"][0])
    js = abs(((jl - sl + math.pi) % (2 * math.pi)) - math.pi)  # heliocentric separation [0,pi]
    row["helio_jup_sat_sep"] = js * _DEG
    row["helio_jup_sat_cos"] = math.cos(jl - sl)  # +1 conjunction, -1 opposition

    # ── Lunar tidal force (1/d^3) and sun+moon syzygy tidal index ──────────────────────────
    moon = ephem.Moon(d)
    sun = ephem.Sun(d)
    moon_d_au = float(moon.earth_distance)
    sun_d_au = float(sun.earth_distance)
    # tidal acceleration ∝ M / d^3; Moon/Sun mass ratio (in Earth-tide units) ≈ 2.2 : 1 at mean distance.
    tide_moon = 2.2 / (moon_d_au ** 3)
    tide_sun = 1.0 / (sun_d_au ** 3)
    # Spring/neap: the projection depends on the Sun-Moon elongation (syzygy = aligned = additive).
    moon_lon = float(ephem.Ecliptic(moon).lon)
    sun_lon = float(ephem.Ecliptic(sun).lon)
    elong = (moon_lon - sun_lon) % (2 * math.pi)
    # combined tidal magnitude with the cos(2*elong) spring/neap modulation of the solar contribution
    row["tide_lunar_force"] = tide_moon
    row["tide_combined"] = tide_moon + tide_sun * math.cos(2 * elong)
    row["tide_solar_force"] = tide_sun

    # ── Giant-planet heliocentric latitude (nodal excursion) ───────────────────────────────
    row["jupiter_helio_lat"] = math.asin(pos["jupiter"][2] / np.linalg.norm(pos["jupiter"])) * _DEG
    row["saturn_helio_lat"] = math.asin(pos["saturn"][2] / np.linalg.norm(pos["saturn"])) * _DEG

    return row


CONTINUOUS_COLS = [
    "sim_offset_au", "sim_offset_solar_radii", "sim_offset_rate", "sim_angular_velocity",
    "sim_offset_x", "sim_offset_y",
    "amom_total", "amom_z", "amom_torque",
    "helio_jup_sat_sep", "helio_jup_sat_cos",
    "tide_lunar_force", "tide_combined", "tide_solar_force",
    "jupiter_helio_lat", "saturn_helio_lat",
]


def physics_features(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Deterministic PHYSICS feature panel (SIM, angular momentum, real heliocentric J-S, true tides)."""
    if not isinstance(dates, pd.DatetimeIndex):
        dates = pd.DatetimeIndex(dates)
    if dates.tz is not None:
        cdts = dates.tz_convert("UTC").to_pydatetime()
    else:
        cdts = [d.replace(tzinfo=UTC) for d in dates.to_pydatetime()]
    rows = [_compute_day(dt) for dt in cdts]
    return pd.DataFrame(rows, index=dates).reindex(columns=CONTINUOUS_COLS).astype(float)


if __name__ == "__main__":
    idx = pd.date_range("2017-01-01", periods=500, freq="D")
    df = physics_features(idx)
    print("shape", df.shape)
    print(df.describe().T[["mean", "std", "min", "max"]])
    print("\nany NaN:", bool(df.isna().any().any()), "count", int(df.isna().sum().sum()))
    # sanity: SIM offset should hover ~1-2 solar radii, torque > 0, J-S sep in [0,180]
    print("\nsim_offset_solar_radii range:", df["sim_offset_solar_radii"].min(), df["sim_offset_solar_radii"].max())
    print("helio_jup_sat_sep range:", df["helio_jup_sat_sep"].min(), df["helio_jup_sat_sep"].max())
