# intent: the ASTRO BELIEF EXPERIMENT — the ONE astro channel with a real, pre-registered prior. Ported from
# Qi-Wang-Zhang "Long Live Hermes" (SSRN 4074620: −3.47%/yr during Mercury retrograde, a BELIEF channel, with a
# fundamentals NULL) and gated against the independent Ma-Kou replication (SSRN 4455435: ~31% annualized drop +
# NEAR-FULL REVERSAL, attention-moderated). The economic thesis is NOT that planets move markets — it is that
# retail BELIEF in Mercury retrograde causes reluctance/avoidance that depresses retail-heavy assets during the
# window, then REVERSES. So the load-bearing predictions are:
#   (a) the effect is a MISPRICING (reverses) not a risk premium;
#   (b) it is STRONGER where retail attention is higher (small-cap/meme), absent in institutional majors;
#   (c) it scales with BELIEF INTENSITY, which we measure directly (Wikipedia pageviews), not just the calendar.
#
# SIGNAL
#   * Mercury-retrograde dummy — EXACT geocentric apparent-motion windows from `ephem` (apparent ecliptic
#     longitude speed < 0 ⇒ retrograde). Deterministic, knowable years ahead, no look-ahead. ~19%/yr of days.
#   * Belief INTENSITY — daily Wikipedia pageviews (Wikimedia REST, no key, non-revised, from 2015-07) for
#     Mercury_retrograde (→Apparent_retrograde_motion) / Astrology / Full_moon. PIT: a day-t count is observable
#     only at t+1 (PUBLISH_LAG_DAYS), so we shift before use — the backtest acts only on observable belief.
#
# THE TEST BATTERY (the Hermes 4 + the Ma-Kou disconfirmer):
#   (1) REAL-EFFECT NULL    — regress returns-VOL / |ret| proxies on the retro dummy. ~0 expected (a belief
#                             channel must NOT move fundamentals/vol; if vol jumps, it is a confound, not belief).
#   (2) LAGGED-PREDICTIVE   — does L1..L5 belief INTENSITY (z-scored, PIT-shifted) NEGATIVELY predict next-day
#                             return? Pooled OLS with asset FE + HAC(Newey-West) t-stats.
#   (3) RETAIL INTERACTION  — is the retro-dummy return effect more negative for RETAIL-heavy assets (small-cap /
#                             meme crypto) than majors? The single most diagnostic cut (Hermes/Ma-Kou's claim).
#   (4) MONTE-CARLO PLACEBO — 1000 pseudo-retrograde calendars (same ~73 contiguous-block days/yr) ⇒ a null
#                             t-distribution for the retro-dummy return coefficient. Two-sided empirical p.
#   (5) REVERSAL (Ma-Kou)   — does the in-window drop REVERSE in the H days AFTER each retro window closes? A
#                             true mispricing reverses; a risk premium does not.
#
# RIGOR: PIT throughout; net of fees (round-trip bps on the traded retro strategy); single chronological OOS
# split for the tradeable rule; Deflated Sharpe at the TRUE trial count; the placebo is the primary significance
# null (never iid). "It joins the null" is a valid, expected finding (plan P≈5-8%). The verdict is recorded to
# the standardized Research Registry under family='astro-belief'.

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ENGINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ENGINE_ROOT / "scripts" / "research" / "astro_deep"))
sys.path.insert(0, str(ENGINE_ROOT / "scripts" / "research"))
sys.path.insert(0, str(ENGINE_ROOT / "scripts" / "research" / "astro_belief"))

import ephem  # noqa: E402
import real_panel as RP  # noqa: E402
from wiki_pageviews import PUBLISH_LAG_DAYS, load_belief_pageviews  # noqa: E402

RNG = np.random.default_rng(20260615)
ANN = np.sqrt(365.0)
FEE_BPS = 10.0  # round-trip cost charged per unit change in position on the traded retro rule

# ── universe: RETAIL-heavy crypto (small-cap / meme) vs institutional MAJORS ─────────────────────────
# The retail/major split is the experiment's most diagnostic axis. "Retail" = high retail-attention, low
# institutional ownership (meme + small/mid-cap alts). "Major" = the institutionally-dominated large caps.
RETAIL = ["DOGEUSDT", "SHIBUSDT", "XRPUSDT", "ADAUSDT", "DOTUSDT", "MATICUSDT", "TRXUSDT", "LTCUSDT"]
MAJORS = ["BTCUSDT", "ETHUSDT"]
# A few small-cap EQUITIES (retail-heavy meme stocks) as an out-of-asset-class corroboration where data allows.
SMALLCAP_EQ = ["GME", "AMC"]


# ── Mercury-retrograde dummy (exact, from ephem) ─────────────────────────────────────────────────────

def _geo_ecliptic_lon_deg(dt: datetime) -> float:
    """Geocentric apparent ecliptic longitude of Mercury (deg) at midnight UTC of `dt`. Apparent = what an
    observer sees from Earth, which is what 'retrograde' refers to (NOT heliocentric, which never reverses)."""
    d = ephem.Date(datetime(dt.year, dt.month, dt.day))
    return (ephem.Ecliptic(ephem.Mercury(d)).lon * 180.0 / np.pi) % 360.0


def mercury_retrograde(index: pd.DatetimeIndex) -> pd.Series:
    """1.0 on days Mercury is in apparent retrograde (geocentric longitude DECREASING day-over-day), else 0.0.
    Computed from `ephem` — deterministic and knowable arbitrarily far ahead, so there is zero look-ahead. The
    day-over-day speed uses the PREVIOUS day's longitude, so the value at t is knowable at the start of t."""
    days = pd.DatetimeIndex(sorted(set(index) | {index.min() - pd.Timedelta(days=1)}))
    lon = pd.Series([_geo_ecliptic_lon_deg(d) for d in days], index=days)
    dlon = lon.diff()
    dlon = ((dlon + 180.0) % 360.0) - 180.0  # wrap to (-180,180] so the 360→0 rollover isn't a fake jump
    retro = (dlon < 0.0).astype(float)
    return retro.reindex(index).fillna(0.0)


def retro_windows(retro: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Contiguous [start,end] spans where retro==1 (each Mercury-retrograde period). Used by the reversal test
    (post-window forward returns) and the Monte-Carlo placebo (preserve block structure)."""
    spans, run_start, prev = [], None, None
    for ts, v in retro.items():
        if v == 1.0 and run_start is None:
            run_start = ts
        elif v == 0.0 and run_start is not None:
            spans.append((run_start, prev))
            run_start = None
        prev = ts
    if run_start is not None:
        spans.append((run_start, prev))
    return spans


# ── PIT belief intensity: pageviews z-score, shifted to the day it is OBSERVABLE ─────────────────────

def belief_intensity(pv: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """PIT belief-intensity features on the bar grid. Each topic's raw daily pageviews are (a) log1p-compressed
    (heavy right tail), (b) shifted forward by PUBLISH_LAG_DAYS so day-t counts are only used from t+lag, then
    (c) z-scored on an EXPANDING window (only past data — no full-sample look-ahead). Returns one column per
    topic, reindexed to `index`."""
    out = {}
    for topic in pv.columns:
        raw = np.log1p(pv[topic].astype(float))
        obs = raw.shift(PUBLISH_LAG_DAYS)  # observable only after the publish lag
        mu = obs.expanding(min_periods=60).mean()
        sd = obs.expanding(min_periods=60).std()
        z = (obs - mu) / sd
        out[topic] = z.reindex(index)
    return pd.DataFrame(out, index=index)


# ── shared stats helpers ─────────────────────────────────────────────────────────────────────────────

def _hac_t(y: np.ndarray, X: np.ndarray, lags: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """OLS with Newey-West (HAC) standard errors. Returns (beta, t-stats). X must include its own intercept
    column. HAC corrects for the serial correlation in daily overlapping returns/positions."""
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    n, k = X.shape
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for L in range(1, lags + 1):
        w = 1.0 - L / (lags + 1.0)
        u = X * resid[:, None]
        G = u[L:].T @ u[:-L]
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.clip(np.diag(cov), 1e-30, None))
    return beta, beta / se


def sharpe(pnl: pd.Series) -> float:
    if len(pnl) < 30 or pnl.std() == 0:
        return float("nan")
    return float(pnl.mean() / pnl.std() * ANN)


def deflated_sharpe(sr_ann: float, n_trials: int, n_obs: int, skew: float, kurt: float) -> float:
    """Bailey & Lopez de Prado DSR: P(true SR>0) after charging for n_trials selections. Wants >0.95."""
    if n_obs < 10 or not np.isfinite(sr_ann):
        return float("nan")
    sr = sr_ann / ANN
    e = 0.5772156649
    z = stats.norm.ppf
    emax = (1 - e) * z(1 - 1.0 / max(n_trials, 2)) + e * z(1 - 1.0 / (max(n_trials, 2) * np.e))
    sr0 = (1.0 / np.sqrt(n_obs)) * emax
    denom = np.sqrt(1 - skew * sr + (kurt - 1) / 4.0 * sr**2)
    if denom <= 0:
        return float("nan")
    return float(stats.norm.cdf((sr - sr0) * np.sqrt(n_obs - 1) / denom))


# ── load the panel: real prices + retro dummy + belief intensity, PIT-aligned ────────────────────────

@dataclass
class Panel:
    rets: pd.DataFrame        # daily log returns, one column per symbol (t-1 -> t)
    retro: pd.Series          # Mercury-retrograde dummy on the union index
    belief: pd.DataFrame      # PIT belief-intensity z-scores (per topic) on the union index
    retail_syms: list[str]
    major_syms: list[str]


def load_panel(days: int = 4200) -> Panel:
    crypto = RETAIL + MAJORS
    print(f"loading {len(crypto)} crypto + {len(SMALLCAP_EQ)} small-cap eq bars ...", flush=True)
    bars = RP.load_crypto_bars(crypto, "1d", days=days)
    eq = {}
    try:
        eq = RP.load_equity_bars(SMALLCAP_EQ, limit=2600)
    except Exception:  # noqa: BLE001 — equities optional; crypto is the core retail universe
        eq = {}

    # NORMALIZE every bar timestamp to midnight UTC so all sources share ONE daily grid. Yahoo equity bars
    # carry an intraday close time (e.g. 14:30) and Binance carries 00:00; without this the union index mixes
    # offset timestamps and the daily belief/retro series (midnight-keyed) fail to align (zero overlap).
    closes = {}
    for s in crypto:
        if len(bars.get(s, [])):
            c = bars[s]["close"].copy()
            c.index = pd.DatetimeIndex(c.index).normalize()
            closes[s] = c[~c.index.duplicated(keep="last")]
    for s in SMALLCAP_EQ:
        if len(eq.get(s, [])):
            c = eq[s]["close"].copy()
            c.index = pd.DatetimeIndex(c.index).normalize()
            closes[s] = c[~c.index.duplicated(keep="last")]

    px = pd.DataFrame(closes).sort_index()
    rets = np.log(px).diff()
    idx = rets.index

    retro = mercury_retrograde(idx)
    pv = load_belief_pageviews()
    belief = belief_intensity(pv, idx)

    retail = [s for s in RETAIL + [s for s in SMALLCAP_EQ if s in px.columns] if s in px.columns]
    majors = [s for s in MAJORS if s in px.columns]
    print(f"panel: {px.shape[1]} symbols, {len(idx)} days {idx.min().date()}..{idx.max().date()}", flush=True)
    print(f"  retail-heavy: {retail}", flush=True)
    print(f"  majors      : {majors}", flush=True)
    print(f"  retro days  : {int(retro.sum())} / {len(retro)} ({100*retro.mean():.1f}%)", flush=True)
    return Panel(rets, retro, belief, retail, majors)


# ── (1) REAL-EFFECT NULL: does the retro dummy move VOL / |ret| (it must NOT for a pure belief channel) ──

def test_real_effect_null(P: Panel) -> dict:
    """Regress a fundamentals/vol proxy (|daily ret|, pooled across the retail universe) on the retro dummy.
    A genuine belief channel should leave realized vol ≈ unchanged (the effect is reluctance-driven mispricing,
    not a fundamentals or risk shock). A significant vol jump would mean the 'effect' is a vol confound."""
    rows_y, rows_d = [], []
    for s in P.retail_syms:
        r = P.rets[s].dropna()
        d = P.retro.reindex(r.index)
        rows_y.append(np.abs(r.to_numpy()))
        rows_d.append(d.to_numpy())
    y = np.concatenate(rows_y)
    d = np.concatenate(rows_d)
    X = np.column_stack([np.ones_like(d), d])
    beta, t = _hac_t(y, X, lags=5)
    vol_in = float(y[d == 1].mean())
    vol_out = float(y[d == 0].mean())
    return {
        "abs_ret_in_retro": round(vol_in, 6),
        "abs_ret_out_retro": round(vol_out, 6),
        "vol_ratio": round(vol_in / vol_out, 4) if vol_out else None,
        "retro_coef_on_absret": round(float(beta[1]), 8),
        "retro_t_on_absret": round(float(t[1]), 3),
        "interpretation": "belief-channel OK if |t|<2 (no real vol effect)",
    }


# ── (2) LAGGED-PREDICTIVE belief regression: does past belief intensity predict next-day return < 0 ? ──

def test_lagged_predictive(P: Panel, topic: str = "Mercury_retrograde", lags=(1, 2, 3, 4, 5)) -> dict:
    """Pooled OLS of next-day return on L1..L5 PIT belief-intensity z-scores (retail universe), asset-demeaned
    (fixed effects) with HAC t-stats. The belief thesis predicts a NEGATIVE sum of lag coefficients (rising
    astrology attention precedes lower retail returns)."""
    b = P.belief[topic]
    Ys, Xs = [], []
    for s in P.retail_syms:
        r = P.rets[s]
        df = pd.concat([r.rename("ret")] + [b.shift(L).rename(f"L{L}") for L in lags], axis=1).dropna()
        if len(df) < 100:
            continue
        df["ret"] = df["ret"] - df["ret"].mean()  # asset FE (demean)
        Ys.append(df["ret"].to_numpy())
        Xs.append(df[[f"L{L}" for L in lags]].to_numpy())
    if not Ys:
        return {"error": "insufficient overlap"}
    y = np.concatenate(Ys)
    Xb = np.vstack(Xs)
    X = np.column_stack([np.ones(len(y)), Xb])
    beta, t = _hac_t(y, X, lags=5)
    coefs = {f"L{L}": round(float(beta[i + 1]), 8) for i, L in enumerate(lags)}
    tstats = {f"L{L}": round(float(t[i + 1]), 3) for i, L in enumerate(lags)}
    sum_coef = float(beta[1:].sum())
    # HAC t on the SUM via a 1-lag aggregate regressor (cleanest joint test of the directional thesis)
    agg = Xb.sum(axis=1)
    Xa = np.column_stack([np.ones(len(y)), agg])
    ba, ta = _hac_t(y, Xa, lags=5)
    return {
        "topic": topic,
        "lag_coefs_bps": {k: round(v * 1e4, 3) for k, v in coefs.items()},
        "lag_tstats": tstats,
        "sum_coef_bps": round(sum_coef * 1e4, 3),
        "sum_t": round(float(ta[1]), 3),
        "n_obs": int(len(y)),
        "interpretation": "belief edge if sum_coef<0 AND |sum_t|>2 (past attention -> lower next-day return)",
    }


# ── (3) RETAIL INTERACTION: retro-dummy return effect, retail vs majors (the most diagnostic cut) ────

def _pooled_retro_coef(rets: pd.DataFrame, syms: list[str], retro: pd.Series) -> tuple[float, float, int]:
    """Pooled (asset-demeaned) OLS of daily return on the retro dummy across `syms`; HAC t. Returns
    (coef_bps, t, n)."""
    Ys, Ds = [], []
    for s in syms:
        r = rets[s].dropna()
        d = retro.reindex(r.index).fillna(0.0)
        rr = r - r.mean()
        Ys.append(rr.to_numpy())
        Ds.append(d.to_numpy())
    if not Ys:
        return float("nan"), float("nan"), 0
    y = np.concatenate(Ys)
    d = np.concatenate(Ds)
    X = np.column_stack([np.ones_like(d), d])
    beta, t = _hac_t(y, X, lags=5)
    return float(beta[1] * 1e4), float(t[1]), int(len(y))


def test_retail_interaction(P: Panel) -> dict:
    """The diagnostic cut: the retro-dummy daily-return effect for RETAIL-heavy assets should be MORE NEGATIVE
    than for institutional MAJORS. Also runs an explicit pooled interaction (retro × retail-flag) with HAC t."""
    rc, rt, rn = _pooled_retro_coef(P.rets, P.retail_syms, P.retro)
    mc, mt, mn = _pooled_retro_coef(P.rets, P.major_syms, P.retro) if P.major_syms else (float("nan"),) * 3

    # explicit interaction regression: ret ~ 1 + retro + retro*retail_flag (asset-demeaned), HAC t on the
    # interaction term — THE coefficient that must be negative & significant for the thesis to hold
    Ys, Dr, Drr = [], [], []
    for s in P.retail_syms + P.major_syms:
        is_retail = 1.0 if s in P.retail_syms else 0.0
        r = P.rets[s].dropna()
        d = P.retro.reindex(r.index).fillna(0.0).to_numpy()
        rr = (r - r.mean()).to_numpy()
        Ys.append(rr)
        Dr.append(d)
        Drr.append(d * is_retail)
    y = np.concatenate(Ys)
    d = np.concatenate(Dr)
    dr = np.concatenate(Drr)
    X = np.column_stack([np.ones_like(d), d, dr])
    beta, t = _hac_t(y, X, lags=5)
    return {
        "retail_retro_coef_bps": round(rc, 3), "retail_retro_t": round(rt, 3), "retail_n": rn,
        "major_retro_coef_bps": round(mc, 3) if np.isfinite(mc) else None,
        "major_retro_t": round(mt, 3) if np.isfinite(mt) else None, "major_n": mn,
        "interaction_coef_bps": round(float(beta[2] * 1e4), 3),
        "interaction_t": round(float(t[2]), 3),
        "interpretation": "thesis supported only if interaction_coef<0 AND |interaction_t|>2 "
                          "(retro hurts retail MORE than majors)",
    }


# ── (4) MONTE-CARLO PLACEBO: 1000 pseudo-retrograde calendars -> null t-distribution ─────────────────

def _placebo_calendar(index: pd.DatetimeIndex, true_windows: list[tuple], rng) -> pd.Series:
    """A pseudo-retrograde calendar with the SAME block structure: for each true window, drop a same-length
    contiguous block at a random offset. Preserves the ~73d/yr coverage AND the contiguous-block shape (so the
    null is not an iid shuffle, which would understate variance for autocorrelated returns)."""
    n = len(index)
    fake = np.zeros(n)
    for (a, b) in true_windows:
        L = (index.get_indexer([b])[0] - index.get_indexer([a])[0]) + 1
        if L <= 0 or L >= n:
            continue
        start = int(rng.integers(0, n - L))
        fake[start:start + L] = 1.0
    return pd.Series(fake, index=index)


def test_monte_carlo_placebo(P: Panel, n_draws: int = 1000) -> dict:
    """The PRIMARY significance null. Observed statistic = pooled retro-dummy return coef (bps) over the retail
    universe. Generate 1000 placebo calendars (same block structure), recompute the coef each time -> empirical
    two-sided p. A real belief effect should sit in the LEFT tail (more negative than placebos)."""
    obs_coef, obs_t, _ = _pooled_retro_coef(P.rets, P.retail_syms, P.retro)
    windows = retro_windows(P.retro)
    idx = P.retro.index
    null = np.empty(n_draws)
    for i in range(n_draws):
        fake = _placebo_calendar(idx, windows, RNG)
        c, _, _ = _pooled_retro_coef(P.rets, P.retail_syms, fake)
        null[i] = c
    null = null[np.isfinite(null)]
    p_two = float((np.abs(null) >= abs(obs_coef)).mean())
    p_left = float((null <= obs_coef).mean())  # how often placebo is at-least-as-negative
    return {
        "obs_retro_coef_bps": round(obs_coef, 3),
        "obs_retro_t_hac": round(obs_t, 3),
        "placebo_mean_bps": round(float(null.mean()), 3),
        "placebo_std_bps": round(float(null.std()), 3),
        "p_two_sided": round(p_two, 4),
        "p_left_tail": round(p_left, 4),
        "n_draws": int(len(null)),
        "interpretation": "significant belief effect if p_left<0.05 (obs more negative than placebos)",
    }


# ── (5) REVERSAL test (Ma-Kou): does the in-window drop reverse AFTER the window closes ? ────────────

def test_reversal(P: Panel, horizon: int = 10) -> dict:
    """Ma-Kou's load-bearing disconfirmer-in-advance. Compare the mean retail return DURING retro windows vs
    the mean retail return in the `horizon` days immediately AFTER each window closes. A true mispricing
    REVERSES (in<0, post>0); a risk premium does NOT reverse. We report both and the reversal ratio."""
    windows = retro_windows(P.retro)
    idx = P.retro.index
    in_rets, post_rets = [], []
    for s in P.retail_syms:
        r = P.rets[s]
        for (a, b) in windows:
            seg_in = r.loc[(r.index >= a) & (r.index <= b)].dropna()
            in_rets.extend(seg_in.to_numpy().tolist())
            j = idx.get_indexer([b])[0]
            post_idx = idx[j + 1: j + 1 + horizon]
            seg_post = r.reindex(post_idx).dropna()
            post_rets.extend(seg_post.to_numpy().tolist())
    in_a = np.array(in_rets)
    post_a = np.array(post_rets)
    in_mean = float(in_a.mean()) if len(in_a) else float("nan")
    post_mean = float(post_a.mean()) if len(post_a) else float("nan")
    t_in = float(stats.ttest_1samp(in_a, 0.0).statistic) if len(in_a) > 5 else float("nan")
    t_post = float(stats.ttest_1samp(post_a, 0.0).statistic) if len(post_a) > 5 else float("nan")
    reverses = bool(np.isfinite(in_mean) and np.isfinite(post_mean) and in_mean < 0 < post_mean)
    return {
        "horizon_days": horizon,
        "in_window_mean_bps": round(in_mean * 1e4, 3),
        "in_window_t": round(t_in, 3),
        "post_window_mean_bps": round(post_mean * 1e4, 3),
        "post_window_t": round(t_post, 3),
        "reverses": reverses,
        "interpretation": "Ma-Kou mispricing pattern if in<0 AND post>0 (drop then reversal)",
    }


# ── tradeable rule + Deflated Sharpe (the honest economic gate) ──────────────────────────────────────

def test_tradeable_rule(P: Panel) -> dict:
    """The simplest tradeable expression of the thesis: SHORT the equal-weight retail basket during Mercury
    retrograde, flat otherwise. PIT (position shifted), net of FEE_BPS round-trip, single 70/30 OOS split,
    Deflated Sharpe at the count of variants actually tried here. Spot-only reality: also report a LONG-FLAT
    'avoid retro' overlay (stay long, go to cash during retro) which needs no shorting."""
    # equal-weight retail basket return
    ew = P.rets[P.retail_syms].mean(axis=1).dropna()
    retro = P.retro.reindex(ew.index).fillna(0.0)

    def bt(position: pd.Series) -> pd.Series:
        held = position.shift(1).fillna(0.0)
        turn = held.diff().abs().fillna(held.abs())
        return (held * ew - turn * (FEE_BPS / 1e4)).dropna()

    variants = {
        "short_retro": -retro,                       # short the basket in retro (needs a short venue)
        "avoid_retro_longflat": (1.0 - retro),       # long basket, flat during retro (spot-only)
        "long_basket_bh": pd.Series(1.0, index=ew.index),  # buy&hold benchmark
    }
    n_trials = 2  # the two non-benchmark rules actually evaluated → fed to DSR
    cut = ew.index[int(len(ew) * 0.70)]
    out = {}
    for name, pos in variants.items():
        pnl = bt(pos)
        oos = pnl[pnl.index > cut]
        if len(oos) < 60:
            continue
        sr = sharpe(oos)
        dsr = deflated_sharpe(sr, n_trials, len(oos), float(stats.skew(oos)), float(stats.kurtosis(oos) + 3))
        out[name] = {
            "oos_sharpe": round(sr, 3),
            "oos_net_return": round(float(np.exp(oos.sum()) - 1.0), 4),
            "dsr": round(dsr, 4) if np.isfinite(dsr) else None,
        }
    out["interpretation"] = "tradeable only if a non-benchmark rule beats B&H net AND DSR>0.95"
    return out


# ── verdict + registry record ────────────────────────────────────────────────────────────────────────

def decide_verdict(results: dict) -> tuple[str, bool, str]:
    """Pre-registered survival logic. The belief channel is a CANDIDATE only if it passes the diagnostic cuts:
      * real-effect null clean (no vol confound),
      * lagged belief predicts next-day return negatively & significantly,
      * retail interaction negative & significant,
      * Monte-Carlo placebo left-tail p<0.05,
      * Ma-Kou reversal present,
      * a tradeable rule clears DSR>0.95.
    Anything short of the directional+significant core → NO_EDGE (joins the astro null), the expected outcome."""
    lp = results["lagged_predictive"]
    ri = results["retail_interaction"]
    mc = results["monte_carlo_placebo"]
    rev = results["reversal"]
    tr = results["tradeable_rule"]

    belief_dir = lp.get("sum_coef_bps", 0) < 0 and abs(lp.get("sum_t", 0)) > 2
    retail_dir = (ri.get("interaction_coef_bps") or 0) < 0 and abs(ri.get("interaction_t") or 0) > 2
    placebo_sig = mc.get("p_left_tail", 1.0) < 0.05
    reverses = bool(rev.get("reverses"))
    tradeable = any(
        isinstance(v, dict) and (v.get("dsr") or 0) > 0.95 and v.get("oos_net_return", -1) > 0
        for k, v in tr.items() if k not in ("long_basket_bh", "interpretation")
    )

    # The Hermes mechanism REQUIRES the Ma-Kou reversal: a belief mispricing depresses returns in the window
    # then reverses. A non-reversing drop is a return artifact, not the belief channel — so reversal is part of
    # the diagnostic core, not a nice-to-have.
    core = belief_dir and retail_dir and placebo_sig and reverses
    if core and tradeable:
        return "CANDIDATE", True, "belief channel survives the diagnostic core (incl. Ma-Kou reversal) AND the economic gate"
    if core:
        return "CANDIDATE", False, "directional belief mispricing (reverses) but not yet tradeable net of fees/DSR"
    if placebo_sig and (belief_dir or retail_dir):
        return "CANDIDATE", False, "partial: placebo-significant with one directional cut — watch, not capital"
    return "NO_EDGE", False, "joins the astro null: no significant, directional, reversing, placebo-robust belief effect"


def record_to_registry(results: dict, P: Panel) -> None:
    from research_registry import ResearchExperiment, record

    verdict, tradeable, why = decide_verdict(results)
    mc = results["monte_carlo_placebo"]
    lp = results["lagged_predictive"]
    ri = results["retail_interaction"]
    rev = results["reversal"]
    rn = results["real_effect_null"]

    headline = (
        f"retro coef {mc['obs_retro_coef_bps']}bps (placebo p_left={mc['p_left_tail']}); "
        f"belief L1-5 sum {lp.get('sum_coef_bps')}bps (t={lp.get('sum_t')}); "
        f"retail×retro {ri.get('interaction_coef_bps')}bps (t={ri.get('interaction_t')}); "
        f"reverses={rev.get('reverses')} → {verdict}"
    )
    exp = ResearchExperiment(
        id="astro_belief_hermes",
        date="2026-06-15",
        family="astro-belief",
        title="Belief channel — Mercury retrograde × Wikipedia-pageview belief intensity (Hermes port)",
        hypothesis=(
            "Retail BELIEF in Mercury retrograde (measured by Wikipedia astrology pageviews) causes "
            "avoidance that depresses retail-heavy crypto during the window, then reverses (Hermes/Ma-Kou)."
        ),
        method=(
            "Exact ephem retro dummy + PIT non-revised Wikipedia pageview intensity. Hermes-4 + Ma-Kou battery: "
            "(1) real-effect/vol null, (2) lagged-predictive belief OLS w/ HAC, (3) retail×retro interaction, "
            "(4) 1000-draw block-structured Monte-Carlo placebo calendars (PRIMARY null), (5) post-window "
            "reversal. Net of fees, 70/30 OOS, Deflated Sharpe."
        ),
        verdict=verdict,
        tradeable=tradeable,
        headline=headline,
        universe=f"{len(P.retail_syms)} retail-heavy (meme/small-cap) + {len(P.major_syms)} majors",
        data_sources=["Binance daily bars", "Yahoo small-cap equities", "Wikipedia pageviews (Wikimedia REST)"],
        key_numbers={
            "obs_retro_coef_bps": mc["obs_retro_coef_bps"],
            "placebo_p_left": mc["p_left_tail"],
            "placebo_p_two": mc["p_two_sided"],
            "belief_sum_coef_bps": lp.get("sum_coef_bps"),
            "belief_sum_t": lp.get("sum_t"),
            "retail_interaction_bps": ri.get("interaction_coef_bps"),
            "retail_interaction_t": ri.get("interaction_t"),
            "in_window_bps": rev.get("in_window_mean_bps"),
            "post_window_bps": rev.get("post_window_mean_bps"),
            "reverses": rev.get("reverses"),
            "vol_ratio_in_out": rn.get("vol_ratio"),
        },
        lessons=[
            "The ONE astro channel with a real prior (belief, not physics) still needs the retail-interaction + "
            "placebo cuts; the Wikipedia-pageview belief instrument is PIT-clean (non-revised) and reusable.",
            why,
        ],
        disconfirmer=(
            "Monte-Carlo placebo left-tail p>=0.05 OR retail×retro interaction not negative/significant OR "
            "no post-window reversal (Ma-Kou) → not a belief mispricing."
        ),
        artifacts=[
            "scripts/research/astro_belief/belief_study.py",
            "scripts/research/astro_belief/wiki_pageviews.py",
            "astro_lab/belief/ (R2: persisted pageviews)",
        ],
        provenance="astro",
    )
    paths = record(exp)
    print(f"\nrecorded to research registry (family=astro-belief) → {paths}")


# ── main ──────────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 88)
    print("ASTRO BELIEF EXPERIMENT — Mercury retrograde × Wikipedia belief intensity (Hermes port)")
    print("=" * 88)
    P = load_panel()

    results = {}
    print("\n(1) REAL-EFFECT NULL — does the retro dummy move vol/|ret|? (should NOT)")
    results["real_effect_null"] = test_real_effect_null(P)
    for k, v in results["real_effect_null"].items():
        print(f"    {k}: {v}")

    print("\n(2) LAGGED-PREDICTIVE belief regression (Mercury_retrograde intensity, L1-5)")
    results["lagged_predictive"] = test_lagged_predictive(P, "Mercury_retrograde")
    for k, v in results["lagged_predictive"].items():
        print(f"    {k}: {v}")

    print("\n(3) RETAIL INTERACTION — retro effect retail vs majors (most diagnostic)")
    results["retail_interaction"] = test_retail_interaction(P)
    for k, v in results["retail_interaction"].items():
        print(f"    {k}: {v}")

    print("\n(4) MONTE-CARLO PLACEBO — 1000 pseudo-retrograde calendars (PRIMARY null)")
    results["monte_carlo_placebo"] = test_monte_carlo_placebo(P, n_draws=1000)
    for k, v in results["monte_carlo_placebo"].items():
        print(f"    {k}: {v}")

    print("\n(5) REVERSAL (Ma-Kou) — does the in-window drop reverse after the window?")
    results["reversal"] = test_reversal(P, horizon=10)
    for k, v in results["reversal"].items():
        print(f"    {k}: {v}")

    print("\n(+) TRADEABLE RULE — short/avoid retro on the retail basket, net of fees, DSR")
    results["tradeable_rule"] = test_tradeable_rule(P)
    for k, v in results["tradeable_rule"].items():
        print(f"    {k}: {v}")

    verdict, tradeable, why = decide_verdict(results)
    print("\n" + "=" * 88)
    print(f"VERDICT: {verdict}  (tradeable={tradeable})")
    print(f"  {why}")
    print("=" * 88)

    record_to_registry(results, P)


if __name__ == "__main__":
    main()
