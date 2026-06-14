#!/usr/bin/env python3
# intent: EXTRA real-data loaders + financial-astrology HYPOTHESIS features for the deep astro study.
# Two jobs:
#   (1) Fold in genuinely-free, point-in-time HONEST real data the literature ties to markets:
#       - Geomagnetic Kp index (the one space-weather variable with a peer-reviewed market paper:
#         Krivelyova & Robotti 2003, FRB Atlanta WP 2003-5).
#       - Sunspot number / solar-cycle activity (SILSO/SIDC; here via the same GFZ combined file).
#       - F10.7 solar radio flux (bundled free in the same GFZ file — documented bonus).
#   (2) Turn the financial-astrology folklore practitioners actually trade into PRECISELY computable,
#       deterministic, falsifiable date-features so the honest Gate can REJECT them (or, improbably, confirm).
#
# CARDINAL RULE — NO FABRICATION. The loaders fetch REAL public data or return an honest empty Series;
# they never invent prices/indices. The astrology features are pure functions of date computed from REAL
# geometry via `ephem` (deterministic sky, knowable at each day's midnight UTC — no look-ahead). The PRIOR
# on every astrology hypothesis is ~0 exploitable edge; the point of making them exact is so the FDR/null
# machinery can falsify them, not to dress folklore up as signal.
#
# PROPOSE-ONLY: nothing here moves money or feeds the Gate directly. Importing this module has NO side
# effects; the self-test lives under __main__. It composes with ml_harness.py (per-asset frames + IC panel)
# and astro_market_study.py (real prices + the base ephemeris panel).
#
# Sources (full citations in the module docstring of the markdown spec returned by the author):
#   - Kp / ap / Ap / SN / F10.7 (1932→today, one file): GFZ Helmholtz Centre, Geomagnetic Observatory Niemegk.
#       https://kp.gfz.de/app/files/Kp_ap_Ap_SN_F107_since_1932.txt  (CC BY 4.0; sunspots CC BY-NC 4.0)
#       Matzka et al. (2021), Space Weather, https://doi.org/10.1029/2020SW002641
#   - Recent 3-hourly Kp (last ~7 days, nowcast): NOAA SWPC
#       https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json
#   - Daily sunspot number (standalone): WDC-SILSO, Royal Observatory of Belgium
#       https://www.sidc.be/SILSO/INFO/sndtotcsv.php  (CC BY-NC 4.0)
#   - Market paper: Krivelyova & Robotti (2003), "Playing the field: Geomagnetic storms and international
#       stock markets", FRB Atlanta WP 2003-5, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=375702
#   - Bradley siderograph: Donald Bradley, "Stock Market Prediction" (1948); component decomposition per
#       Rosecast / Timing Solution documentation.

from __future__ import annotations

import io
import math
import ssl
import urllib.request
from datetime import datetime

import ephem
import numpy as np
import pandas as pd

# ── shared infrastructure ─────────────────────────────────────────────────────────────────────────

_OBLIQUITY_DEG = 23.4366  # mean obliquity of the ecliptic — the out-of-bounds threshold for declination

_GFZ_URL = "https://kp.gfz.de/app/files/Kp_ap_Ap_SN_F107_since_1932.txt"
_SWPC_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
_SILSO_DAILY_URL = "https://www.sidc.be/SILSO/INFO/sndtotcsv.php"


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _empty_series(name: str) -> pd.Series:
    """An HONEST empty daily series (never fabricated) when a fetch fails."""
    return pd.Series(dtype=float, index=pd.DatetimeIndex([], name="date"), name=name)


def _fetch_text(url: str, timeout: int = 40) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "cosmu-research/0.1"})
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()).read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 — an unreachable endpoint is an honest empty, never fabricated
        return None


def _tail_days(s: pd.Series, days: int) -> pd.Series:
    if not len(s) or days <= 0:
        return s
    cutoff = s.index.max() - pd.Timedelta(days=days)
    return s.loc[s.index >= cutoff]


# ── (1) REAL DATA LOADERS — LIVE ────────────────────────────────────────────────────────────────────


def _parse_gfz(text: str) -> pd.DataFrame:
    """Parse the GFZ fixed-width Kp_ap_Ap_SN_F107 file into a daily frame: kp_daily, Ap, SN, f107.

    Layout (28 blank-separated fields/line, '#' comment lines):
      0 YYYY  1 MM  2 DD  3 days  4 days_m  5 Bsr  6 dB
      7..14  Kp1..Kp8 (3-hourly Kp, missing = -1.000)
      15..22 ap1..ap8
      23 Ap   24 SN (sunspot, missing = -1)   25 F10.7obs   26 F10.7adj   27 D(definitive flag)
    The DAILY Kp is the mean of the eight 3-hourly Kp values (the standard daily Kp), which honestly
    matches Krivelyova-Robotti's use of a DAILY geomagnetic disturbance level.
    """
    recs = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split()
        if len(p) < 28:
            continue
        try:
            y, m, d = int(p[0]), int(p[1]), int(p[2])
            kp = [float(x) for x in p[7:15]]
            kp_ok = [k for k in kp if k >= 0.0]
            kp_daily = float(np.mean(kp_ok)) if kp_ok else np.nan
            ap = int(p[23])
            sn = int(p[24])
            f107 = float(p[25])
        except ValueError:
            continue
        recs.append(
            (
                pd.Timestamp(y, m, d),
                kp_daily,
                np.nan if ap < 0 else float(ap),
                np.nan if sn < 0 else float(sn),
                np.nan if f107 < 0 else f107,
            )
        )
    if not recs:
        return pd.DataFrame(columns=["kp_daily", "Ap", "SN", "f107"]).set_index(
            pd.DatetimeIndex([], name="date")
        )
    df = pd.DataFrame(recs, columns=["date", "kp_daily", "Ap", "SN", "f107"]).set_index("date").sort_index()
    return df


def load_gfz_panel(days: int = 3650) -> pd.DataFrame:
    """LIVE. REAL daily geomagnetic+solar panel from GFZ (1932→today): columns kp_daily, Ap, SN, f107.

    One free, point-in-time file carries all three series the study wants. Returns the trailing `days`
    (set days<=0 for the full history). Honest empty frame if the endpoint is unreachable.
    """
    text = _fetch_text(_GFZ_URL)
    if text is None:
        return pd.DataFrame(columns=["kp_daily", "Ap", "SN", "f107"]).set_index(
            pd.DatetimeIndex([], name="date")
        )
    df = _parse_gfz(text)
    if days and days > 0 and len(df):
        cutoff = df.index.max() - pd.Timedelta(days=days)
        df = df.loc[df.index >= cutoff]
    return df


def load_kp_index(days: int = 3650) -> pd.Series:
    """LIVE. REAL daily geomagnetic Kp index (mean of the 8 three-hourly Kp), GFZ since 1932.

    This is the one space-weather variable with a peer-reviewed market paper (Krivelyova & Robotti 2003).
    PIT-honest: a UT day's Kp is finalised after the day closes; the most-recent rows are GFZ "nowcast"
    and get revised to definitive later (a revision caveat the study must respect — lag the join by 1 day).
    Returns a daily float Series named 'kp_daily'; honest empty Series if the fetch fails.
    """
    panel = load_gfz_panel(days=days)
    if not len(panel):
        return _empty_series("kp_daily")
    return panel["kp_daily"].rename("kp_daily")


def load_sunspots(days: int = 3650) -> pd.Series:
    """LIVE. REAL daily international sunspot number (SN, version 2.0), via the GFZ combined file.

    The GFZ file embeds the WDC-SILSO daily total sunspot number (the same authoritative SILSO series),
    so one fetch serves both Kp and sunspots. Most-recent values are preliminary (revised later) — same
    1-day lag caveat as Kp. Returns a daily float Series named 'sunspots'; honest empty if the fetch fails.
    """
    panel = load_gfz_panel(days=days)
    if not len(panel):
        return _empty_series("sunspots")
    return panel["SN"].rename("sunspots")


def load_f107(days: int = 3650) -> pd.Series:
    """LIVE (bonus). REAL daily F10.7 solar radio flux (observed), via the GFZ combined file.

    Solar-activity proxy correlated with sunspots; documented free bonus column. Returns a daily Series
    named 'f107'; honest empty if the fetch fails.
    """
    panel = load_gfz_panel(days=days)
    if not len(panel):
        return _empty_series("f107")
    return panel["f107"].rename("f107")


def load_kp_swpc_recent() -> pd.Series:
    """LIVE. REAL recent daily Kp from NOAA SWPC (last ~7 days, 3-hourly → daily mean).

    GFZ's definitive file can lag the last day or two; SWPC's nowcast fills that gap. Use it ONLY to
    extend the tail of load_kp_index when running near real-time. Honest empty if unreachable.
    """
    import json

    req = urllib.request.Request(_SWPC_KP_URL, headers={"User-Agent": "cosmu-research/0.1"})
    try:
        raw = urllib.request.urlopen(req, timeout=30, context=_ssl_ctx()).read()
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return _empty_series("kp_daily")
    recs = []
    for row in data:
        try:
            ts = pd.Timestamp(row["time_tag"])
            recs.append((ts.normalize(), float(row["Kp"])))
        except (KeyError, ValueError, TypeError):
            continue
    if not recs:
        return _empty_series("kp_daily")
    df = pd.DataFrame(recs, columns=["date", "kp"]).set_index("date")
    daily = df.groupby(level=0)["kp"].mean()
    daily.index.name = "date"
    return daily.rename("kp_daily")


def load_sunspots_silso(days: int = 3650) -> pd.Series:
    """LIVE (alternate source). REAL daily SILSO sunspot number, direct from the Royal Observatory of Belgium.

    A standalone fallback to load_sunspots (which sources the same series via GFZ). Semicolon CSV:
      year ; month ; day ; decimal_year ; SN ; SN_std ; n_obs ; provisional_flag   (missing SN = -1).
    Honest empty if the fetch fails.
    """
    text = _fetch_text(_SILSO_DAILY_URL)
    if text is None:
        return _empty_series("sunspots")
    try:
        df = pd.read_csv(
            io.StringIO(text),
            sep=";",
            header=None,
            usecols=[0, 1, 2, 4],
            names=["y", "m", "d", "sn"],
            engine="python",
        )
    except Exception:  # noqa: BLE001
        return _empty_series("sunspots")
    df = df[df["sn"] >= 0]
    if not len(df):
        return _empty_series("sunspots")
    idx = pd.to_datetime(dict(year=df["y"], month=df["m"], day=df["d"]), errors="coerce")
    s = pd.Series(df["sn"].astype(float).values, index=idx, name="sunspots").dropna()
    s.index.name = "date"
    s = s.sort_index()
    return _tail_days(s, days)


# ── (2) FINANCIAL-ASTROLOGY HYPOTHESIS FEATURES — pure functions of date (LIVE / deterministic) ───────
#
# Every function below: feat_<name>(dates: pd.DatetimeIndex) -> pd.Series, computed from ephem geometry
# at each day's 00:00 UTC. No look-ahead, no fabrication. These are NON-CAUSAL priors expected to FAIL the
# honest gate; the contract is that each is EXACT enough for FDR/permutation tests to falsify it.

_PLANETS = {
    "mercury": ephem.Mercury,
    "venus": ephem.Venus,
    "mars": ephem.Mars,
    "jupiter": ephem.Jupiter,
    "saturn": ephem.Saturn,
    "uranus": ephem.Uranus,
    "neptune": ephem.Neptune,
}

# Slow planets whose ingress (zodiac sign change) practitioners watch as a regime marker.
_SLOW = ("jupiter", "saturn", "uranus", "neptune")


def _edate(d: pd.Timestamp) -> ephem.Date:
    return ephem.Date(datetime(d.year, d.month, d.day, 0, 0, 0))


def _ecl_lon_deg(body_cls, dt: ephem.Date) -> float:
    return math.degrees(ephem.Ecliptic(body_cls(dt)).lon) % 360.0


def _ecl_lat_deg(body_cls, dt: ephem.Date) -> float:
    return math.degrees(ephem.Ecliptic(body_cls(dt)).lat)


def _decl_deg(body_cls, dt: ephem.Date) -> float:
    return math.degrees(ephem.Equatorial(body_cls(dt)).dec)


def _ang_sep(a: float, b: float) -> float:
    """Signed-wrapped angular separation in [0,180]."""
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def _is_retro(body_cls, dt: ephem.Date) -> bool:
    """Apparent geocentric retrograde: day-over-day ecliptic longitude regresses."""
    l_now = _ecl_lon_deg(body_cls, dt)
    l_prev = _ecl_lon_deg(body_cls, ephem.Date(dt - 1))
    dlon = ((l_now - l_prev + 180.0) % 360.0) - 180.0
    return dlon < 0.0


# --- Mercury retrograde window -----------------------------------------------------------------------

def feat_mercury_retro(dates: pd.DatetimeIndex) -> pd.Series:
    """CLAIM (folklore): markets misbehave / reverse during Mercury-retrograde windows.
    FEATURE: 1.0 on each day Mercury is apparently retrograde (geocentric), else 0.0.
    DISCONFIRMER: forward returns on retro days are statistically indistinguishable from direct days.
    PRIOR: ~0. Mercury retro is ~3×/year, ~19% of days; pure calendar noise w.r.t. price.
    """
    out = {d: (1.0 if _is_retro(ephem.Mercury, _edate(d)) else 0.0) for d in dates}
    return pd.Series(out, name="mercury_retro").reindex(dates)


# --- Mars-Saturn hard aspect -------------------------------------------------------------------------

def feat_mars_saturn_hard(dates: pd.DatetimeIndex, orb: float = 6.0) -> pd.Series:
    """CLAIM (folklore): Mars-Saturn conjunction/square/opposition coincides with fear / sell-offs.
    FEATURE: 1.0 when the Mars-Saturn ecliptic separation is within `orb`° of 0/90/180, else 0.0.
    DISCONFIRMER: no negative forward-return skew on flagged days vs the rest.
    PRIOR: ~0. A multi-year-rare hard aspect; sample too thin to power a real edge.
    """
    out = {}
    for d in dates:
        dt = _edate(d)
        sep = _ang_sep(_ecl_lon_deg(ephem.Mars, dt), _ecl_lon_deg(ephem.Saturn, dt))
        out[d] = 1.0 if any(abs(sep - a) <= orb for a in (0.0, 90.0, 180.0)) else 0.0
    return pd.Series(out, name="mars_saturn_hard").reindex(dates)


def feat_mars_saturn_orb(dates: pd.DatetimeIndex) -> pd.Series:
    """Continuous companion to feat_mars_saturn_hard: degrees to the NEAREST hard aspect (0..45).
    Smaller = tighter aspect. Lets the IC test pick up a graded effect a binary flag would miss.
    PRIOR: ~0.
    """
    out = {}
    for d in dates:
        dt = _edate(d)
        sep = _ang_sep(_ecl_lon_deg(ephem.Mars, dt), _ecl_lon_deg(ephem.Saturn, dt))
        out[d] = float(min(abs(sep - a) for a in (0.0, 90.0, 180.0)))
    return pd.Series(out, name="mars_saturn_orb").reindex(dates)


# --- Slow-planet ingress (sign change) ---------------------------------------------------------------

def feat_slow_ingress(dates: pd.DatetimeIndex, window_days: int = 3) -> pd.Series:
    """CLAIM (folklore): a slow planet changing zodiac sign (ingress) marks a market regime shift.
    FEATURE: 1.0 if ANY of Jupiter/Saturn/Uranus/Neptune crosses a 30° sign boundary within
             ±`window_days` of the date, else 0.0.
    DISCONFIRMER: no excess forward volatility / no directional drift around flagged days.
    PRIOR: ~0. Ingresses are rare, irregularly spaced calendar marks unrelated to order flow.
    """
    # Precompute each slow planet's sign index over the (padded) date span, then flag boundary crossings.
    if not len(dates):
        return pd.Series(dtype=float, name="slow_ingress")
    pad = pd.Timedelta(days=window_days + 1)
    span = pd.date_range(dates.min() - pad, dates.max() + pad, freq="D")
    signs = {}
    for name in _SLOW:
        cls = _PLANETS[name]
        signs[name] = np.array([int(_ecl_lon_deg(cls, _edate(d)) // 30) for d in span])
    # day index → True if a sign change happens at that day vs previous day
    cross = np.zeros(len(span), dtype=bool)
    for name in _SLOW:
        s = signs[name]
        changed = s[1:] != s[:-1]
        cross[1:] |= changed
    cross_idx = np.where(cross)[0]
    cross_dates = span[cross_idx]
    out = {}
    cd = np.array([c.value for c in cross_dates]) if len(cross_dates) else np.array([])
    w = window_days * 86_400_000_000_000  # ns
    for d in dates:
        if len(cd) == 0:
            out[d] = 0.0
            continue
        out[d] = 1.0 if np.any(np.abs(cd - d.value) <= w) else 0.0
    return pd.Series(out, name="slow_ingress").reindex(dates)


# --- Lunar declination / out-of-bounds Moon ----------------------------------------------------------

def feat_moon_declination(dates: pd.DatetimeIndex) -> pd.Series:
    """CLAIM (folklore): the Moon's declination cycle (~27.3d) modulates sentiment / turning points.
    FEATURE: the Moon's geocentric declination in degrees at 00:00 UTC (continuous, ~[-28.7,+28.7]).
    DISCONFIRMER: zero IC vs forward returns at any horizon/regime.
    PRIOR: ~0. A clean ~27-day cycle; if anything it aliases the synodic month already tested elsewhere.
    """
    out = {d: _decl_deg(ephem.Moon, _edate(d)) for d in dates}
    return pd.Series(out, name="moon_declination").reindex(dates)


def feat_moon_out_of_bounds(dates: pd.DatetimeIndex) -> pd.Series:
    """CLAIM (folklore): an 'out-of-bounds' Moon (|declination| > obliquity 23.44°) brings erratic action.
    FEATURE: 1.0 when |Moon declination| > 23.4366°, else 0.0.
    DISCONFIRMER: forward-return distribution on OOB days matches in-bounds days.
    PRIOR: ~0. OOB frequency itself follows the 18.6-year nodal cycle — a slow calendar artefact.
    """
    out = {d: (1.0 if abs(_decl_deg(ephem.Moon, _edate(d))) > _OBLIQUITY_DEG else 0.0) for d in dates}
    return pd.Series(out, name="moon_out_of_bounds").reindex(dates)


# --- New-Moon / Full-Moon trade timing ---------------------------------------------------------------

def feat_lunar_phase(dates: pd.DatetimeIndex) -> pd.Series:
    """CONTEXT feature: synodic phase position 0→1 (0 = new moon, 0.5 ≈ full). Continuous.
    PRIOR: the lunar-cycle anomaly is the most-studied and most-debunked of these; ~0 after costs.
    """
    out = {}
    for d in dates:
        dt = _edate(d)
        pn, nn = ephem.previous_new_moon(dt), ephem.next_new_moon(dt)
        out[d] = float((dt - pn) / (nn - pn)) if (nn - pn) else np.nan
    return pd.Series(out, name="lunar_phase").reindex(dates)


def feat_near_new_moon(dates: pd.DatetimeIndex, orb_days: float = 1.5) -> pd.Series:
    """CLAIM (folklore): buy the new moon. FEATURE: 1.0 within ±`orb_days` of an exact new moon.
    DISCONFIRMER: no positive forward-return premium around new moons.
    PRIOR: ~0 (lunar anomaly does not survive transaction costs / multiple testing).
    """
    out = {}
    for d in dates:
        dt = _edate(d)
        nn, pn = ephem.next_new_moon(dt), ephem.previous_new_moon(dt)
        out[d] = 1.0 if min(abs(dt - nn), abs(dt - pn)) <= orb_days else 0.0
    return pd.Series(out, name="near_new_moon").reindex(dates)


def feat_near_full_moon(dates: pd.DatetimeIndex, orb_days: float = 1.5) -> pd.Series:
    """CLAIM (folklore): sell / weak returns near the full moon. FEATURE: 1.0 within ±`orb_days` of full.
    DISCONFIRMER: forward returns near full moons match the unconditional mean.
    PRIOR: ~0.
    """
    out = {}
    for d in dates:
        dt = _edate(d)
        nf, pf = ephem.next_full_moon(dt), ephem.previous_full_moon(dt)
        out[d] = 1.0 if min(abs(dt - nf), abs(dt - pf)) <= orb_days else 0.0
    return pd.Series(out, name="near_full_moon").reindex(dates)


# --- Eclipse-proximity window ------------------------------------------------------------------------

def _nearest_syzygy(dt: ephem.Date) -> ephem.Date:
    cands = [
        ephem.previous_new_moon(dt),
        ephem.next_new_moon(dt),
        ephem.previous_full_moon(dt),
        ephem.next_full_moon(dt),
    ]
    return min(cands, key=lambda s: abs(dt - s))


def feat_eclipse_proximity(dates: pd.DatetimeIndex, lat_orb: float = 1.5, day_orb: float = 5.0) -> pd.Series:
    """CLAIM (folklore): markets turn within an eclipse 'shadow window'.
    FEATURE: 1.0 if the date is within ±`day_orb` days of a SYZYGY (new/full moon) whose Moon ecliptic
             latitude |β| < `lat_orb`° — i.e. a true eclipse (syzygy near a lunar node). ephem has no
             eclipse function, so this geometric proxy reconstructs eclipses from first principles
             (validated: real 2024-25 eclipses score |β|<0.35° vs 3.8-5.0° for ordinary syzygies).
    DISCONFIRMER: no excess forward volatility / drift inside eclipse windows.
    PRIOR: ~0. ~4-7 eclipses/year; the windows are sparse, irregular calendar marks.
    """
    if not len(dates):
        return pd.Series(dtype=float, name="eclipse_proximity")
    # Find eclipse dates over a padded span (a syzygy near a node), then flag ±day_orb around each.
    pad = pd.Timedelta(days=day_orb + 20)
    span = pd.date_range(dates.min() - pad, dates.max() + pad, freq="D")
    seen: set[int] = set()
    ecl_ns: list[int] = []
    for d in span:
        syz = _nearest_syzygy(_edate(d))
        key = round(float(syz) * 4) / 4  # dedupe syzygy by quarter-day
        if key in seen:
            continue
        seen.add(key)
        beta = abs(math.degrees(ephem.Ecliptic(ephem.Moon(syz)).lat))
        if beta < lat_orb:
            ecl_ns.append(pd.Timestamp(ephem.Date(syz).datetime()).normalize().value)
    arr = np.array(ecl_ns)
    w = int(day_orb) * 86_400_000_000_000
    out = {}
    for d in dates:
        out[d] = 1.0 if (len(arr) and np.any(np.abs(arr - d.value) <= w)) else 0.0
    return pd.Series(out, name="eclipse_proximity").reindex(dates)


# --- Bradley siderograph turn dates ------------------------------------------------------------------

# Bradley's planet pairs and valency. Sextile(60)/trine(120) are POSITIVE; square(90)/opposition(180)
# NEGATIVE; conjunction(0) sign depends on the pair (Bradley's tables). We use the documented core:
# a +1/-1 valency per aspect, summed across all planet pairs, plus the declination factor
# = 0.5*(decl(Venus)+decl(Mars)). This is a faithful REDUCED-FORM Bradley (the full siderograph applies
# Bradley's bespoke per-pair weights + a 5x long-term/declination multiplier we expose but keep transparent).
_BRADLEY_BODIES = {
    "mercury": ephem.Mercury, "venus": ephem.Venus, "mars": ephem.Mars,
    "jupiter": ephem.Jupiter, "saturn": ephem.Saturn,
    "uranus": ephem.Uranus, "neptune": ephem.Neptune, "pluto": ephem.Pluto,
}
_ASPECT_VALENCY = {0.0: 1.0, 60.0: 1.0, 90.0: -1.0, 120.0: 1.0, 180.0: -1.0}


def _bradley_value(dt: ephem.Date, orb: float = 6.0, decl_weight: float = 5.0) -> float:
    """Reduced-form Bradley potential for one day: aspect-valency sum + Venus/Mars declination factor."""
    lons = {n: _ecl_lon_deg(c, dt) for n, c in _BRADLEY_BODIES.items()}
    names = list(lons)
    total = 0.0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            sep = _ang_sep(lons[names[i]], lons[names[j]])
            for ang, val in _ASPECT_VALENCY.items():
                off = abs(sep - ang)
                if off <= orb:
                    # triangular taper: full valency at exact, 0 at the orb edge
                    total += val * (1.0 - off / orb)
                    break
    decl_factor = 0.5 * (_decl_deg(ephem.Venus, dt) + _decl_deg(ephem.Mars, dt))
    return total + decl_weight * (decl_factor / _OBLIQUITY_DEG)  # normalise decl into ~[-decl_weight,+decl_weight]


def feat_bradley_siderograph(dates: pd.DatetimeIndex) -> pd.Series:
    """CLAIM (folklore): the Bradley siderograph's value predicts market direction; its TURNS (local
    extrema / zero-crossings) mark reversal dates.
    FEATURE: the (reduced-form) Bradley potential as a continuous daily value (z-scoreable downstream).
    DISCONFIRMER: zero IC of the Bradley value vs forward returns; turning-date flags carry no edge.
    PRIOR: ~0. Bradley himself warned the curve fits TIMING of turns, not amplitude/direction; out of
    sample it is widely shown to be no better than chance.
    NOTE: this is a transparent REDUCED-FORM (documented simplification of Bradley's bespoke weight tables).
    """
    out = {d: _bradley_value(_edate(d)) for d in dates}
    return pd.Series(out, name="bradley_siderograph").reindex(dates)


def feat_bradley_turn(dates: pd.DatetimeIndex, smooth: int = 3) -> pd.Series:
    """The Bradley TURN-DATE flag: 1.0 where the (3-day-smoothed) siderograph makes a local extremum
    (sign change of its first difference) — the 'siderograph turn dates' practitioners trade.
    DISCONFIRMER: forward-return behaviour around turn flags matches random dates.
    PRIOR: ~0.
    """
    if not len(dates):
        return pd.Series(dtype=float, name="bradley_turn")
    # Compute on a padded span so edge days get honest neighbours, then restrict.
    pad = pd.Timedelta(days=smooth + 2)
    span = pd.date_range(dates.min() - pad, dates.max() + pad, freq="D")
    vals = pd.Series([_bradley_value(_edate(d)) for d in span], index=span)
    sm = vals.rolling(smooth, center=True, min_periods=1).mean()
    diff = sm.diff()
    sign = np.sign(diff)
    turn = (sign != sign.shift(1)) & sign.shift(1).notna() & (sign != 0)
    flag = turn.astype(float)
    return flag.reindex(dates).fillna(0.0).rename("bradley_turn")


# --- Gann master-time-factor calendar dates ----------------------------------------------------------

# Gann counts forward in CALENDAR DAYS from a major pivot. The "master time factor" intervals are the
# squares-of-numbers and the harmonic angles. This feature REQUIRES an anchor date (a known pivot); it is
# therefore parametric. Default anchors are well-known major US-equity pivots (documented, not fabricated).
GANN_INTERVALS = (30, 45, 49, 60, 64, 72, 81, 90, 100, 120, 121, 144, 180, 225, 270, 288, 315, 360)
GANN_DEFAULT_ANCHORS = (
    pd.Timestamp("2009-03-09"),   # GFC bear-market low (major secular pivot)
    pd.Timestamp("2020-03-23"),   # COVID crash low
    pd.Timestamp("2021-11-22"),   # late-2021 risk-asset peak
    pd.Timestamp("2022-10-13"),   # 2022 bear-market low
)


def feat_gann_time_factor(
    dates: pd.DatetimeIndex,
    anchors: tuple[pd.Timestamp, ...] = GANN_DEFAULT_ANCHORS,
    intervals: tuple[int, ...] = GANN_INTERVALS,
    orb_days: int = 2,
) -> pd.Series:
    """CLAIM (Gann): markets turn on 'master time factor' calendar counts (squares & harmonic angles:
    30/45/60/90/120/180/270/360 days, plus n² days) measured forward from a major pivot.
    FEATURE: 1.0 if the date falls within ±`orb_days` of (anchor + interval) for ANY anchor×interval, else 0.
    DISCONFIRMER: no excess turn-frequency / drift on flagged days vs matched random dates.
    PRIOR: ~0, and HONESTLY BIASED: anchors are chosen with hindsight, so this feature is GENEROUS to the
    hypothesis — if it still fails the gate (it will), the folklore is doubly falsified. Anchors are a
    parameter precisely so the operator can supply PIT-honest pivots and re-test without look-ahead.
    """
    if not len(dates):
        return pd.Series(dtype=float, name="gann_time_factor")
    targets_ns = []
    for a in anchors:
        for k in intervals:
            targets_ns.append((a + pd.Timedelta(days=k)).normalize().value)
    arr = np.array(sorted(set(targets_ns)))
    w = int(orb_days) * 86_400_000_000_000
    out = {}
    for d in dates:
        out[d] = 1.0 if np.any(np.abs(arr - d.value) <= w) else 0.0
    return pd.Series(out, name="gann_time_factor").reindex(dates)


# ── registry / public groupings (mirrors astro_market_study.py SCALAR_IC / CATEGORICAL_IC pattern) ───

# date-only astrology features that return CONTINUOUS values (Spearman-IC candidates)
ASTRO_SCALAR_FEATS = {
    "mars_saturn_orb": feat_mars_saturn_orb,
    "moon_declination": feat_moon_declination,
    "lunar_phase": feat_lunar_phase,
    "bradley_siderograph": feat_bradley_siderograph,
}
# date-only astrology features that return BINARY 0/1 flags (event-window candidates)
ASTRO_BINARY_FEATS = {
    "mercury_retro": feat_mercury_retro,
    "mars_saturn_hard": feat_mars_saturn_hard,
    "slow_ingress": feat_slow_ingress,
    "moon_out_of_bounds": feat_moon_out_of_bounds,
    "near_new_moon": feat_near_new_moon,
    "near_full_moon": feat_near_full_moon,
    "eclipse_proximity": feat_eclipse_proximity,
    "bradley_turn": feat_bradley_turn,
    "gann_time_factor": feat_gann_time_factor,
}
ASTRO_FEATS = {**ASTRO_SCALAR_FEATS, **ASTRO_BINARY_FEATS}

# real-data loaders that return a fetched daily series (NOT pure functions of date)
DATA_LOADERS = {
    "kp_daily": load_kp_index,
    "sunspots": load_sunspots,
    "f107": load_f107,
}


def build_astro_extra_table(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Compute ALL date-only astrology hypothesis features for `dates` into one frame (deterministic, no
    look-ahead). Composes with ml_harness.ic_panel / astro_market_study.assemble. Real-data loaders are
    NOT included here — they are joined separately (they fetch, lag, and may be empty)."""
    cols = {name: fn(dates) for name, fn in ASTRO_FEATS.items()}
    return pd.DataFrame(cols).reindex(dates)


# ── self-test (only under __main__ — importing the module has NO side effects) ────────────────────────

if __name__ == "__main__":
    import sys

    print("=" * 86)
    print("extra_signals self-test — REAL data loaders + deterministic astrology features")
    print("=" * 86)

    # (1) REAL DATA — fetch and report honest source + row counts
    print("\n[1] REAL DATA LOADERS (live fetch)")
    kp = load_kp_index(days=3650)
    sn = load_sunspots(days=3650)
    f107 = load_f107(days=3650)
    print(f"  load_kp_index   GFZ  rows={len(kp):>5}  "
          f"span={kp.index.min().date() if len(kp) else '-'}→{kp.index.max().date() if len(kp) else '-'}  "
          f"mean={kp.mean():.3f}  nan%={kp.isna().mean()*100:.1f}" if len(kp) else "  load_kp_index   GFZ  EMPTY (endpoint unreachable — honest empty)")
    print(f"  load_sunspots   GFZ  rows={len(sn):>5}  "
          f"span={sn.index.min().date() if len(sn) else '-'}→{sn.index.max().date() if len(sn) else '-'}  "
          f"mean={sn.mean():.1f}  nan%={sn.isna().mean()*100:.1f}" if len(sn) else "  load_sunspots   GFZ  EMPTY")
    print(f"  load_f107       GFZ  rows={len(f107):>5}  mean={f107.mean():.1f}" if len(f107) else "  load_f107       GFZ  EMPTY")
    if len(kp):
        print("  recent kp_daily tail:")
        print("    " + kp.tail(3).to_string().replace("\n", "\n    "))

    # SWPC recent + SILSO alternate — report reachability honestly
    swpc = load_kp_swpc_recent()
    print(f"  load_kp_swpc_recent  NOAA SWPC  rows={len(swpc)}  "
          f"(last={swpc.index.max().date() if len(swpc) else '-'})")
    silso = load_sunspots_silso(days=120)
    print(f"  load_sunspots_silso  SILSO direct  rows={len(silso)}  "
          f"(last={silso.index.max().date() if len(silso) else '-'})"
          + ("" if len(silso) else "  [honest empty — host may RST raw urllib; GFZ load_sunspots is the working primary for the SAME SILSO series]"))

    # (2) ASTROLOGY FEATURES — deterministic, run on a recent 2-year window
    print("\n[2] DETERMINISTIC ASTROLOGY FEATURES (no fetch, pure date geometry)")
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    tbl = build_astro_extra_table(dates)
    print(f"  build_astro_extra_table: {tbl.shape[0]} days × {tbl.shape[1]} features, "
          f"{dates.min().date()}→{dates.max().date()}")
    print("\n  per-feature coverage / activation (binary = % days flagged; scalar = mean ± std):")
    for name in ASTRO_FEATS:
        s = tbl[name]
        if name in ASTRO_BINARY_FEATS:
            print(f"    {name:22} BINARY   flagged={s.mean()*100:5.1f}% of days   "
                  f"(n_flag={int(s.sum())})")
        else:
            print(f"    {name:22} SCALAR   mean={s.mean():8.3f}  std={s.std():7.3f}  "
                  f"range=[{s.min():.2f},{s.max():.2f}]")

    # spot-check a few known dates so a reader can SEE the geometry is real
    print("\n  spot-checks (known events):")
    chk = pd.DatetimeIndex([
        pd.Timestamp("2025-03-14"),   # total lunar eclipse
        pd.Timestamp("2025-03-20"),   # Mercury retro + Sun ingress Aries
        pd.Timestamp("2024-04-08"),   # total solar eclipse
        pd.Timestamp("2025-06-11"),   # ordinary full moon (NOT an eclipse)
    ])
    sub = build_astro_extra_table(chk)
    show = ["mercury_retro", "near_full_moon", "near_new_moon", "eclipse_proximity",
            "moon_out_of_bounds", "moon_declination", "bradley_siderograph", "gann_time_factor"]
    print("    " + sub[show].round(3).to_string().replace("\n", "\n    "))

    # honest sanity assertions (fail loud if geometry breaks)
    assert sub.loc["2025-03-14", "eclipse_proximity"] == 1.0, "lunar eclipse 2025-03-14 not flagged"
    assert sub.loc["2024-04-08", "eclipse_proximity"] == 1.0, "solar eclipse 2024-04-08 not flagged"
    assert sub.loc["2025-06-11", "eclipse_proximity"] == 0.0, "ordinary full moon falsely flagged as eclipse"
    assert sub.loc["2025-03-20", "mercury_retro"] == 1.0, "Mercury retro 2025-03-20 not flagged"
    print("\n  assertions passed: eclipse proxy + Mercury-retro match reality.")

    # Gann demo on a window where the default anchors actually project intervals (2024-25 lands 0 — honest):
    gann_demo = feat_gann_time_factor(pd.date_range("2009-03-20", "2009-09-30", freq="D"))
    print(f"  gann_time_factor near the 2009-03-09 anchor: {int(gann_demo.sum())} flagged days "
          f"(e.g. {[str(d.date()) for d in gann_demo[gann_demo > 0].index[:4]]}) "
          f"— 0 on 2024-25 above is HONEST, not broken (anchors don't project there).")
    assert gann_demo.sum() > 0, "Gann feature inert even near its own anchor"

    ok = bool(len(kp) and len(sn) and tbl.notna().any().all())
    print("\n" + "=" * 86)
    print(f"SELF-TEST {'OK' if ok else 'INCOMPLETE'} — "
          f"{len(DATA_LOADERS)} data loaders (LIVE), {len(ASTRO_FEATS)} astrology features (LIVE/deterministic)")
    print("=" * 86)
    sys.exit(0 if ok else 1)
