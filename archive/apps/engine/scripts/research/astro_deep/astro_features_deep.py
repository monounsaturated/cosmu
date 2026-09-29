# intent: DEEPEST honest pure-astro feature library — a broad, deterministic daily panel of
# geocentric + heliocentric geometry, lunar mechanics, aspects, harmonics, eclipses and a few
# financial-astrology "specials" that practitioners actually trade.
#
# CARDINAL RULE OF THIS CODEBASE — NO FABRICATION.  Every value here is *deterministic geometry*
# computed from the `ephem` (libastro / XEphem) library: it IS real astronomy, knowable exactly at
# the day's midnight UTC.  There is no market data, no price, no look-ahead, no revision.  The sky
# does not cause price moves — this panel exists so the Gate can be handed a maximally broad set of
# honest, non-causal features and falsify them on out-of-sample data.  The financial-astrology
# composites (Bradley-siderograph-style sum, Mars–Saturn flags, …) are clearly labelled NON-CAUSAL
# heuristics with documented, fixed weights; they encode a *belief proxy*, not a causal claim.
#
# Public contract (matches the integrator's expectation exactly):
#     deep_astro_features(dates: pd.DatetimeIndex) -> pd.DataFrame   # indexed by `dates`, all-numeric
#     CONTINUOUS_COLS / CIRCULAR_COLS / BINARY_COLS / CATEGORICAL_COLS   # together cover every column
#
# Determinism / point-in-time: each row is computed for midnight UTC of that calendar day.  The only
# day-over-day coupling is the apparent-speed / retrograde estimate, which uses the *previous* day
# (a backward difference) so it remains knowable at the day's start — never the next day.  No future
# information enters any column.

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import ephem
import numpy as np
import pandas as pd

# ─── Constants ────────────────────────────────────────────────────────────────────────────────

TRANSFORM_VERSION = "astro-features-deep-v1"

_DEG = 180.0 / math.pi  # radians → degrees
_KM_PER_AU = ephem.meters_per_au / 1000.0

# Out-of-bounds: a body is "out of bounds" when its declination exceeds the Sun's maximum
# (the obliquity of the ecliptic, ~23.44°) — a real, named condition in observational astrology.
_OBLIQUITY_DEG = 23.4392911

# Mean synodic month (new-moon → new-moon), days.  Used only to normalise lunation *age*; the
# new/full-moon *instants* themselves come from ephem's exact solver, not this constant.
_SYNODIC_MONTH = 29.530588

# Moon perigee / apogee bracket (km) — long-term extremes used to map distance → a [0,1] proximity.
_MOON_PERIGEE_KM = 356_500.0
_MOON_APOGEE_KM = 406_700.0

# The ten classical bodies, in canonical order.  `ephem` body classes.
_BODIES: list[tuple[str, type]] = [
    ("sun", ephem.Sun),
    ("moon", ephem.Moon),
    ("mercury", ephem.Mercury),
    ("venus", ephem.Venus),
    ("mars", ephem.Mars),
    ("jupiter", ephem.Jupiter),
    ("saturn", ephem.Saturn),
    ("uranus", ephem.Uranus),
    ("neptune", ephem.Neptune),
    ("pluto", ephem.Pluto),
]

# Bodies for which a heliocentric longitude is geometrically meaningful (NOT Sun/Moon).
# ephem exposes `.hlon` (heliocentric ecliptic longitude, radians) on planet bodies directly.
_HELIO_BODIES = ["mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto"]

# Major (Ptolemaic) aspects: name → exact angle in degrees.
_ASPECTS: dict[str, float] = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}
_HARD_ASPECTS = {"conjunction", "square", "opposition"}
_SOFT_ASPECTS = {"sextile", "trine"}

# Default and tight orbs (degrees) for aspect classification.
_ORB_WIDE = 6.0
_ORB_TIGHT = 3.0

# Harmonic divisors n: an aspect of the n-th harmonic is a multiple of 360/n degrees.
_HARMONICS = [2, 3, 4, 5, 6, 8]
_HARMONIC_ORB = 4.0  # orb (deg) for "near a multiple of 360/n"

# Sun-sign element (0=fire,1=earth,2=air,3=water) and modality (0=cardinal,1=fixed,2=mutable),
# indexed by zodiac sign 0..11 (Aries..Pisces).
_SIGN_ELEMENT = [0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3]
_SIGN_MODALITY = [0, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1, 2]


# ─── Low-level ephem helpers ──────────────────────────────────────────────────────────────────

def _ephem_date(dt: datetime) -> ephem.Date:
    """ephem.Date for the midnight-UTC instant of a (tz-aware or naive→UTC) datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return ephem.Date(datetime(dt.year, dt.month, dt.day, 0, 0, 0))


def _geo_ecliptic_lon_deg(body_cls: type, d: ephem.Date) -> float:
    """Geocentric apparent ecliptic longitude [0,360) for a body class at instant d."""
    b = body_cls(d)
    return (ephem.Ecliptic(b).lon * _DEG) % 360.0


def _mean_node_lon_deg(d: ephem.Date) -> float:
    """Mean longitude of the Moon's ascending node (Rahu / North Node), degrees [0,360).

    Meeus, *Astronomical Algorithms*, eq. 47.7 (mean node):
        Ω = 125.04452 − 1934.136261·T   (T in Julian centuries from J2000.0)
    Mean (not true) node — accurate to ~1.5° vs. the osculating node; ample for a flag/feature.
    """
    jd = ephem.julian_date(d)
    t = (jd - 2_451_545.0) / 36_525.0
    return (125.04452 - 1934.136261 * t) % 360.0


def _ang_sep_deg(lon_a: float, lon_b: float) -> float:
    """Smallest unsigned separation between two ecliptic longitudes, [0,180]."""
    diff = abs(lon_a - lon_b) % 360.0
    return diff if diff <= 180.0 else 360.0 - diff


# ─── Per-day computation ──────────────────────────────────────────────────────────────────────

def _compute_day(dt: datetime) -> dict[str, float]:
    """Compute the full deterministic astro panel for one calendar day (midnight UTC).

    `dt` is the day in question; `prev` (one day earlier) is used only for the *backward*
    apparent-speed / retrograde difference, which keeps everything knowable at the day's start.
    """
    d = _ephem_date(dt)
    d_prev = _ephem_date(dt - timedelta(days=1))
    row: dict[str, float] = {}

    # ── Per-body geocentric block ──────────────────────────────────────────────────────────
    geo_lon: dict[str, float] = {}
    for name, cls in _BODIES:
        lon = _geo_ecliptic_lon_deg(cls, d)
        lon_prev = _geo_ecliptic_lon_deg(cls, d_prev)
        geo_lon[name] = lon

        # Apparent speed: signed day-over-day longitude change, wrapped to (-180,180].
        speed = ((lon - lon_prev + 180.0) % 360.0) - 180.0
        row[f"{name}_lon_deg"] = lon
        row[f"{name}_speed_deg"] = speed
        row[f"{name}_retrograde"] = 1.0 if speed < 0.0 else 0.0

        # Declination (geocentric, of date) + out-of-bounds flag (|decl| > obliquity).
        b = cls(d)
        decl = b.dec * _DEG
        row[f"{name}_decl_deg"] = decl
        row[f"{name}_out_of_bounds"] = 1.0 if abs(decl) > _OBLIQUITY_DEG else 0.0

        # Zodiac sign 0..11 (Aries=0 at 0° ecliptic longitude).
        row[f"{name}_sign"] = float(int(lon // 30.0) % 12)

    # ── Heliocentric longitudes (planets only) ─────────────────────────────────────────────
    # ephem exposes `.hlon` — heliocentric ecliptic longitude (radians) — on planet bodies.
    # Accuracy: libastro/XEphem VSOP87-class, sub-arcminute over the modern era — far tighter
    # than any orb we use.  Sun/Moon are excluded: a heliocentric longitude of the Sun or Moon
    # is not geometrically meaningful (Sun is the origin; Moon orbits Earth, not the Sun).
    for name in _HELIO_BODIES:
        cls = dict(_BODIES)[name]
        b = cls(d)
        row[f"{name}_helio_lon_deg"] = (b.hlon * _DEG) % 360.0

    # ── Lunar mechanics ────────────────────────────────────────────────────────────────────
    moon = ephem.Moon(d)
    # Illuminated fraction [0,1].  ephem `.phase` is the illuminated *percentage*.
    illum = float(moon.phase) / 100.0
    row["moon_illum_frac"] = illum

    # Synodic age: position within the current lunation, 0=new … →1.  Exact instants from ephem.
    prev_new = ephem.previous_new_moon(d)
    next_new = ephem.next_new_moon(d)
    next_full = ephem.next_full_moon(d)
    lun_len = float(next_new) - float(prev_new)
    age_frac = (float(d) - float(prev_new)) / lun_len if lun_len > 0 else 0.0
    row["moon_synodic_age"] = min(max(age_frac, 0.0), 1.0)
    row["moon_days_to_new"] = float(next_new) - float(d)
    row["moon_days_to_full"] = float(next_full) - float(d)
    row["moon_near_new"] = 1.0 if row["moon_days_to_new"] <= 1.5 else 0.0
    row["moon_near_full"] = 1.0 if row["moon_days_to_full"] <= 1.5 else 0.0

    # Distance + perigee/apogee proximity in [0,1] (0=at perigee, 1=at apogee), clamped.
    dist_km = float(moon.earth_distance) * _KM_PER_AU
    row["moon_distance_km"] = dist_km
    prox = (dist_km - _MOON_PERIGEE_KM) / (_MOON_APOGEE_KM - _MOON_PERIGEE_KM)
    row["moon_perigee_apogee_prox"] = min(max(prox, 0.0), 1.0)

    # NB: lunar declination is already emitted as `moon_decl_deg` in the per-body block above
    # (the Moon is one of the ten bodies), so we do not duplicate it here.

    # Ascending-node (Rahu) longitude + a void-of-course APPROXIMATION.
    node_lon = _mean_node_lon_deg(d)
    row["moon_node_lon_deg"] = node_lon

    # VOID-OF-COURSE APPROXIMATION (documented, deliberately lightweight):
    #   True VOC = the Moon will form no further EXACT major aspect to another body before it
    #   leaves its current zodiac sign.  Computing the exact next-aspect instant per day is heavy.
    #   We approximate with the cheap, common proxy: VOC ⇢ the Moon is in the LAST 3° of its
    #   current sign AND, scanning the other nine bodies, none lies in the small forward arc the
    #   Moon still has to travel within an orb (i.e. no *applying* major aspect remains in-sign).
    #   This catches the canonical "late-degree, nothing left to perfect" VOC windows; it will
    #   miss VOCs that begin earlier in a sign.  Flag only — clearly an approximation.
    moon_lon = geo_lon["moon"]
    deg_into_sign = moon_lon % 30.0
    deg_left_in_sign = 30.0 - deg_into_sign
    voc = 0.0
    if deg_left_in_sign <= 3.0:
        applying = False
        for name in ("sun", "mercury", "venus", "mars", "jupiter",
                     "saturn", "uranus", "neptune", "pluto"):
            other = geo_lon[name]
            for ang in _ASPECTS.values():
                # forward longitude at which the Moon would perfect this aspect to `other`
                target = (other + ang) % 360.0
                fwd = (target - moon_lon) % 360.0  # degrees the Moon must still advance
                if 0.0 < fwd <= deg_left_in_sign + _ORB_WIDE:
                    applying = True
                    break
            if applying:
                break
        voc = 0.0 if applying else 1.0
    row["moon_void_of_course"] = voc

    # ── Aspects (all unordered body pairs) ─────────────────────────────────────────────────
    names = [n for n, _ in _BODIES]
    # Wide-orb (default 6°) and tight-orb (3°) variants computed in one pass.
    for orb, suffix in ((_ORB_WIDE, ""), (_ORB_TIGHT, "_tight")):
        per_type = dict.fromkeys(_ASPECTS, 0.0)
        hard = 0.0
        soft = 0.0
        stress = 0.0
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                sep = _ang_sep_deg(geo_lon[names[i]], geo_lon[names[j]])
                # nearest major aspect
                best_name = None
                best_delta = orb + 1.0
                for aname, aangle in _ASPECTS.items():
                    delta = abs(sep - aangle)
                    if delta < best_delta:
                        best_delta = delta
                        best_name = aname
                if best_name is not None and best_delta <= orb:
                    per_type[best_name] += 1.0
                    if best_name in _HARD_ASPECTS:
                        hard += 1.0
                    else:
                        soft += 1.0
                    # continuous tightness/stress: 1.0 at exact, →0 at the orb edge
                    stress += (orb - best_delta) / orb
        for aname in _ASPECTS:
            row[f"aspect_{aname}_count{suffix}"] = per_type[aname]
        row[f"hard_aspect_count{suffix}"] = hard
        row[f"soft_aspect_count{suffix}"] = soft
        row[f"aspect_tightness_stress{suffix}"] = stress

    # ── Harmonics (counts near multiples of 360/n) ─────────────────────────────────────────
    for n in _HARMONICS:
        base = 360.0 / n
        cnt = 0.0
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                sep = _ang_sep_deg(geo_lon[names[i]], geo_lon[names[j]])
                # distance to the nearest multiple of `base` in [0,180]
                k = round(sep / base)
                if abs(sep - k * base) <= _HARMONIC_ORB:
                    cnt += 1.0
        row[f"harmonic_{n}_count"] = cnt

    # ── Eclipses (approximation via syzygy-at-node) ────────────────────────────────────────
    # APPROXIMATION (documented): an eclipse occurs when a new moon (solar) or full moon (lunar)
    # happens while the Moon is near a node — i.e. its ecliptic LATITUDE at the syzygy instant is
    # small.  We take the next new AND next full moon, compute |Moon ecliptic latitude| at each,
    # and treat |lat| < 1.5° as "eclipse-grade" (solar ≲1.4°, lunar ≲1.0° are the textbook
    # central limits; 1.5° is a permissive partial-eclipse bound).  days_to_next_eclipse is the
    # day-count to the nearer qualifying syzygy; if neither upcoming syzygy qualifies we fall back
    # to the nearer syzygy distance (still deterministic, just not eclipse-grade) and leave the
    # window flag off.  Approximate — it can miss/early-count partials at the latitude boundary.
    cand_days = []
    for syz in (next_new, next_full):
        m_syz = ephem.Moon(syz)
        lat = abs(ephem.Ecliptic(m_syz).lat * _DEG)
        if lat < 1.5:
            cand_days.append(float(syz) - float(d))
    if cand_days:
        dte = min(cand_days)
        row["days_to_next_eclipse"] = dte
        row["eclipse_window"] = 1.0 if abs(dte) <= 3.0 else 0.0
    else:
        # No eclipse-grade syzygy imminent: report distance to the nearer plain syzygy, no window.
        row["days_to_next_eclipse"] = min(float(next_new) - float(d), float(next_full) - float(d))
        row["eclipse_window"] = 0.0

    # ── Calendar / zodiac extras (Sun-sign element & modality) ─────────────────────────────
    sun_sign = int(geo_lon["sun"] // 30.0) % 12
    row["sun_element"] = float(_SIGN_ELEMENT[sun_sign])
    row["sun_modality"] = float(_SIGN_MODALITY[sun_sign])

    # ── Financial-astrology specials (NON-CAUSAL belief-proxies, fixed documented heuristics) ─
    # Mercury retrograde — the one feature with an actual (weak, debunked) "belief-proxy" paper
    # trail.  Explicit flag duplicates mercury_retrograde for discoverability.
    row["mercury_retrograde_flag"] = row["mercury_retrograde"]

    # Mars–Saturn hard aspect (conj/square/opp within wide orb) — "tension" pair folklore.
    ms = _ang_sep_deg(geo_lon["mars"], geo_lon["saturn"])
    row["mars_saturn_hard_aspect"] = 1.0 if any(
        abs(ms - _ASPECTS[a]) <= _ORB_WIDE for a in _HARD_ASPECTS
    ) else 0.0

    # Jupiter–Saturn any major aspect (the ~20-yr "great-conjunction" cycle, a market-cycle staple).
    js = _ang_sep_deg(geo_lon["jupiter"], geo_lon["saturn"])
    row["jupiter_saturn_aspect"] = 1.0 if any(
        abs(js - ang) <= _ORB_WIDE for ang in _ASPECTS.values()
    ) else 0.0

    # Bradley-siderograph-style composite (DOCUMENTED NON-CAUSAL HEURISTIC).
    #   Donald Bradley's 1948 "siderograph" summed weighted heliocentric/geocentric aspect terms
    #   into a single "sidereal potential" curve.  We DO NOT reproduce his proprietary table; we
    #   build a transparent analogue: a weighted sum of cos(aspect-harmonic) terms for a handful of
    #   slow-pair separations, with FIXED, hand-chosen weights below.  The cosines make conjunction
    #   (sep→0) maximally positive and opposition maximally negative for the 1st harmonic, etc.
    #   These weights are an arbitrary heuristic — they encode NO causal claim and are frozen so the
    #   feature is byte-reproducible.  Purpose: hand the Gate a single "composite astro mood" scalar
    #   to falsify, not to predict anything.
    def _cos_term(a: str, b: str, harmonic: int) -> float:
        sep = _ang_sep_deg(geo_lon[a], geo_lon[b])
        return math.cos(math.radians(harmonic * sep))

    bradley = (
        1.0 * _cos_term("jupiter", "saturn", 1)
        + 0.8 * _cos_term("saturn", "uranus", 1)
        + 0.6 * _cos_term("jupiter", "uranus", 1)
        + 0.5 * _cos_term("mars", "saturn", 2)     # 2nd harmonic → squares weighted in
        + 0.4 * _cos_term("venus", "jupiter", 1)
        + 0.3 * _cos_term("sun", "saturn", 1)
    )
    row["bradley_siderograph"] = bradley

    return row


# ─── Column-group registry ────────────────────────────────────────────────────────────────────
# Built once at import (pure string construction, no ephem calls → zero side effects).

def _build_column_groups() -> tuple[list[str], list[str], list[str], list[str]]:
    body_names = [n for n, _ in _BODIES]

    circular: list[str] = []
    continuous: list[str] = []
    binary: list[str] = []
    categorical: list[str] = []

    # Per-body
    for name in body_names:
        circular.append(f"{name}_lon_deg")          # ecliptic longitude → sin/cos
        continuous.append(f"{name}_speed_deg")
        binary.append(f"{name}_retrograde")
        continuous.append(f"{name}_decl_deg")
        binary.append(f"{name}_out_of_bounds")
        categorical.append(f"{name}_sign")
    for name in _HELIO_BODIES:
        circular.append(f"{name}_helio_lon_deg")

    # Lunar
    # NB: moon_decl_deg is emitted in the per-body loop above (Moon is one of the ten bodies),
    # so it is NOT repeated here.
    continuous += [
        "moon_illum_frac", "moon_synodic_age", "moon_days_to_new", "moon_days_to_full",
        "moon_distance_km", "moon_perigee_apogee_prox",
    ]
    binary += ["moon_near_new", "moon_near_full", "moon_void_of_course"]
    circular += ["moon_node_lon_deg"]

    # Aspects (wide + tight)
    for suffix in ("", "_tight"):
        for aname in _ASPECTS:
            continuous.append(f"aspect_{aname}_count{suffix}")
        continuous += [
            f"hard_aspect_count{suffix}",
            f"soft_aspect_count{suffix}",
            f"aspect_tightness_stress{suffix}",
        ]

    # Harmonics
    for n in _HARMONICS:
        continuous.append(f"harmonic_{n}_count")

    # Eclipses
    continuous.append("days_to_next_eclipse")
    binary.append("eclipse_window")

    # Calendar extras
    categorical += ["sun_element", "sun_modality"]

    # Financial specials
    binary += ["mercury_retrograde_flag", "mars_saturn_hard_aspect", "jupiter_saturn_aspect"]
    continuous.append("bradley_siderograph")

    return continuous, circular, binary, categorical


CONTINUOUS_COLS, CIRCULAR_COLS, BINARY_COLS, CATEGORICAL_COLS = _build_column_groups()

# Canonical full column order (used to lay out the DataFrame).
ALL_COLS: list[str] = []
_seen: set[str] = set()
for _c in CONTINUOUS_COLS + CIRCULAR_COLS + BINARY_COLS + CATEGORICAL_COLS:
    if _c in _seen:  # pragma: no cover — guards against a future copy/paste duplicate
        raise RuntimeError(f"duplicate column in group registry: {_c}")
    _seen.add(_c)
    ALL_COLS.append(_c)


# ─── Public entry point ───────────────────────────────────────────────────────────────────────

def deep_astro_features(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Deterministic pure-astro feature panel, one row per UTC day in `dates`.

    Parameters
    ----------
    dates : pd.DatetimeIndex
        Days to compute.  Tz-aware indices are converted to UTC; tz-naive are assumed UTC.
        Each row is computed for midnight UTC of that calendar day.

    Returns
    -------
    pd.DataFrame
        Indexed by `dates` (preserved verbatim), all-numeric columns in the canonical
        CONTINUOUS+CIRCULAR+BINARY+CATEGORICAL order.  Every value is deterministic geometry
        knowable at the day's start — NO look-ahead, NO fabrication.

    Notes
    -----
    Non-causal control panel.  The sky does not cause prices; this exists for the Gate to falsify.
    The apparent-speed/retrograde columns use a *backward* (previous-day) difference, so they too
    are knowable at the day's midnight UTC.
    """
    if not isinstance(dates, pd.DatetimeIndex):
        dates = pd.DatetimeIndex(dates)

    # Normalise each timestamp to a midnight-UTC datetime for computation.
    if dates.tz is not None:
        compute_dts = dates.tz_convert("UTC").to_pydatetime()
    else:
        compute_dts = [d.replace(tzinfo=UTC) for d in dates.to_pydatetime()]

    rows = [_compute_day(dt) for dt in compute_dts]
    df = pd.DataFrame(rows, index=dates).reindex(columns=ALL_COLS)
    # Geometry never produces NaN; coerce defensively so the contract "no NaN where avoidable" holds.
    return df.astype(float)


# ─── Self-test ────────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Make the engine package importable for the cross-validation import.
    sys.path.insert(0, "/Users/device/cosmu/.claude/worktrees/tender-turing-19c2dd/apps/engine")

    today = pd.Timestamp.utcnow().normalize().tz_localize(None)
    idx = pd.date_range(end=today, periods=400, freq="D")
    df = deep_astro_features(idx)

    print("=" * 78)
    print(f"deep_astro_features — shape = {df.shape}  (rows x cols)")
    print(f"TRANSFORM_VERSION = {TRANSFORM_VERSION}")
    print("=" * 78)

    print(f"\nCONTINUOUS_COLS ({len(CONTINUOUS_COLS)}):")
    for c in CONTINUOUS_COLS:
        print(f"    {c}")
    print(f"\nCIRCULAR_COLS ({len(CIRCULAR_COLS)}):")
    for c in CIRCULAR_COLS:
        print(f"    {c}")
    print(f"\nBINARY_COLS ({len(BINARY_COLS)}):")
    for c in BINARY_COLS:
        print(f"    {c}")
    print(f"\nCATEGORICAL_COLS ({len(CATEGORICAL_COLS)}):")
    for c in CATEGORICAL_COLS:
        print(f"    {c}")

    total = len(CONTINUOUS_COLS) + len(CIRCULAR_COLS) + len(BINARY_COLS) + len(CATEGORICAL_COLS)
    print(f"\ngroup-list total = {total}   df columns = {df.shape[1]}")
    assert total == df.shape[1], "group lists must cover EVERY column exactly once"
    assert set(ALL_COLS) == set(df.columns), "column set mismatch vs registry"

    print("\n--- sample row (last day) ---")
    last = df.iloc[-1]
    print(f"date = {df.index[-1]}")
    for c in ALL_COLS:
        print(f"    {c:34} = {last[c]:.5f}")

    # No column constant; none all-NaN.
    nunique = df.nunique()
    const_cols = [c for c in df.columns if nunique[c] <= 1]
    allnan = [c for c in df.columns if df[c].isna().all()]
    print(f"\nconstant columns over 400d: {const_cols}")
    print(f"all-NaN columns: {allnan}")
    print(f"any NaN anywhere: {bool(df.isna().any().any())}  (count={int(df.isna().sum().sum())})")
    assert not allnan, f"all-NaN columns present: {allnan}"
    # Some binary flags legitimately stay 0 over a 400-day window (e.g. a rare eclipse pattern or
    # an out-of-bounds outer planet); a constant *flag* is honest, not a bug.  We only forbid a
    # constant CONTINUOUS or CIRCULAR column — those should always vary over 400 days.
    bad_const = [c for c in const_cols if c in CONTINUOUS_COLS or c in CIRCULAR_COLS]
    assert not bad_const, f"continuous/circular column is constant over 400d: {bad_const}"
    print(f"(constant flags are allowed; constant continuous/circular cols: {bad_const})")

    # CROSS-VALIDATION vs the engine's existing closed-form lunar illumination.
    from cosmu.data.sources.astro_ephemeris import _jd_from_dt, _lunar_phase_fraction

    sample = idx[::8][:50]  # 50 spread-out days
    diffs = []
    for ts in sample:
        dt = datetime(ts.year, ts.month, ts.day, 0, 0, 0, tzinfo=UTC)
        cf = _lunar_phase_fraction(_jd_from_dt(dt))
        ours = float(df.loc[ts, "moon_illum_frac"])
        diffs.append(abs(cf - ours))
    max_diff = max(diffs)
    print(f"\nlunar illumination cross-check vs astro_ephemeris._lunar_phase_fraction:")
    print(f"    sampled days = {len(sample)}   max abs diff = {max_diff:.5f}")
    assert max_diff < 0.03, f"lunar illumination disagrees by {max_diff:.4f} (> 0.03)"

    print("\nALL SELF-TEST ASSERTIONS PASSED.")
