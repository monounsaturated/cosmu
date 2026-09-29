"""
INFO-THEORETIC astro -> markets study  (wave 1, dimension "info_theoretic").

Question attacked from a NEW dimension: does any deterministic astro STATE carry
NONLINEAR mutual information about a forward market target that single-feature
Spearman IC / AUC would have missed?

Method
------
- Astro STATES = discrete labels (lunar 8-phase, planet signs, retro flags, aspect
  counts, element/modality, eclipse/OOB binaries, declination sign+magnitude bins).
- Targets per asset = forward 1d return, forward |return| (1d vol proxy), forward
  5d realized vol (std of next 5 daily log-rets).  All strictly forward (shift -1),
  so the label at day t is matched to the return earned over (t -> t+1).
- MI estimate = KSG via sklearn.mutual_info_classif(target_2d, label, n_neighbors=4):
  MI between a DISCRETE label and a CONTINUOUS target, capturing nonlinear coupling.
- NULL (PROPER, cardinal rule #2): CIRCULAR SHIFT of the astro label series by a
  random offset, the TARGET (return) series left untouched.  This preserves the full
  autocorrelation of returns AND the marginal/autocorrelation of the astro labels
  (a near-constant slow-planet sign stays near-constant under rotation, so it cannot
  manufacture a regime artifact).  i.i.d. fake-random labels are explicitly NOT used
  (they manufactured the dead lunar-vol false positive last round).
- We use a block-aware minimum shift (>= 20 trading days off either end) so a tiny
  rotation cannot leak the real alignment.

Significance
------------
- Per (asset, state, target): one-sided empirical p = (#null >= obs + 1)/(N+1).
- Effect size: MI_obs - mean(MI_null) in nats, and a z = (obs-mean)/std.
- Multiple testing: Benjamini-Hochberg FDR across the FULL grid (all asset x state x
  target), plus a Bonferroni reference.  Economic relevance is judged separately:
  even a real MI bit is worthless if it is not monotone/tradeable net of ~10bps.

A candidate is reported ONLY if it beats the circular-shift null after BH-FDR.
"Nothing survives" is the expected, honest outcome.
"""
from __future__ import annotations
import sys, os, json, time, argparse
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import astro_features_deep as AF
import real_panel as RP

from sklearn.feature_selection import mutual_info_classif

RNG = np.random.default_rng(20260615)

CRYPTO = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT",
          "AVAXUSDT","LINKUSDT","DOTUSDT","LTCUSDT","BCHUSDT","ATOMUSDT","UNIUSDT",
          "FILUSDT","NEARUSDT","AAVEUSDT"]
EQUITY = ["SPY","QQQ","IWM","GLD","SLV","TLT","XLE","XLF","XLK","USO"]

MIN_SHIFT = 25          # trading days kept off each end of the circular shift
N_NULL = 400            # surrogate draws per (asset,state,target)
N_NEIGHBORS = 4


# ----------------------------------------------------------------------------- states
def build_astro_states(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Discrete astro STATE labels (integer-coded), one row per day in idx."""
    feat = AF.deep_astro_features(idx)
    S = pd.DataFrame(index=idx)

    # lunar 8-phase from synodic age (0..1)
    age = feat["moon_synodic_age"].to_numpy()
    S["lunar_8phase"] = np.floor(age * 8).astype(int).clip(0, 7)
    # lunar quarter (4-phase)
    S["lunar_4phase"] = np.floor(age * 4).astype(int).clip(0, 3)

    # planet signs (already 0..11 categorical) — keep the ones that actually vary
    for p in ["sun","moon","mercury","venus","mars","jupiter","saturn"]:
        col = f"{p}_sign"
        if col in feat and feat[col].nunique() >= 3:
            S[f"{p}_sign"] = feat[col].astype(int)

    # element / modality of the Sun and Moon
    for c in ["sun_element","sun_modality","moon_sign"]:
        pass
    for c in ["sun_element","sun_modality"]:
        if c in feat:
            S[c] = feat[c].astype(int)
    # moon element/modality if present
    for c in feat.columns:
        if c in ("moon_element","moon_modality") and feat[c].nunique() >= 2:
            S[c] = feat[c].astype(int)

    # retrograde flags (binary) — only the ones that vary
    for p in ["mercury","venus","mars","jupiter","saturn","uranus","neptune","pluto"]:
        col = f"{p}_retrograde"
        if col in feat and feat[col].nunique() == 2:
            S[col] = feat[col].astype(int)
    # composite count of retro planets
    retro_cols = [c for c in feat.columns if c.endswith("_retrograde") and feat[c].nunique()==2]
    if retro_cols:
        S["n_retrograde"] = feat[retro_cols].sum(axis=1).astype(int)

    # out-of-bounds binaries that vary
    for p in ["moon","mercury","venus","mars","pluto"]:
        col = f"{p}_out_of_bounds"
        if col in feat and feat[col].nunique() == 2:
            S[col] = feat[col].astype(int)

    # eclipse / lunar special binaries
    for c in ["moon_near_new","moon_near_full","moon_void_of_course","eclipse_window",
              "mars_saturn_hard_aspect","jupiter_saturn_aspect"]:
        if c in feat and feat[c].nunique() == 2:
            S[c] = feat[c].astype(int)

    # aspect counts (small-cardinality categoricals) — bin to reduce sparsity
    for c in ["hard_aspect_count","soft_aspect_count","aspect_square_count",
              "aspect_conjunction_count","aspect_opposition_count","aspect_trine_count",
              "harmonic_4_count","harmonic_3_count"]:
        if c in feat:
            v = feat[c].astype(int)
            # quantile-bin into <=5 ordinal buckets so MI has support
            try:
                b = pd.qcut(v.rank(method="first"), q=5, labels=False, duplicates="drop")
                S[f"{c}_q5"] = b.astype(int)
            except Exception:
                pass

    # moon declination sign + magnitude bins (geometry, not periodic label per se but a state)
    decl = feat["moon_decl_deg"].to_numpy()
    S["moon_decl_sign"] = (decl >= 0).astype(int)
    S["moon_decl_q4"] = pd.qcut(pd.Series(decl, index=idx).rank(method="first"),
                                q=4, labels=False, duplicates="drop").astype(int)
    # perigee/apogee proximity bins (supermoon state)
    if "moon_perigee_apogee_prox" in feat:
        S["moon_perigee_q4"] = pd.qcut(
            feat["moon_perigee_apogee_prox"].rank(method="first"),
            q=4, labels=False, duplicates="drop").astype(int)

    return S


# ----------------------------------------------------------------------------- targets
def build_targets(close: pd.Series) -> pd.DataFrame:
    """Forward targets aligned so day-t label predicts day-t->t+1 outcomes."""
    logc = np.log(close.astype(float))
    r1 = logc.diff()                      # daily log return realized over (t-1 -> t)
    fwd_r1 = r1.shift(-1)                 # forward 1d return earned t -> t+1
    fwd_abs = fwd_r1.abs()               # forward 1d |return| (vol proxy)
    # forward 5d realized vol = std of next 5 daily log rets (t+1..t+5)
    fwd_vol5 = r1.shift(-1).rolling(5).std().shift(-(5 - 1))
    out = pd.DataFrame({
        "fwd_ret_1d": fwd_r1,
        "fwd_absret_1d": fwd_abs,
        "fwd_vol_5d": fwd_vol5,
    })
    return out


# ----------------------------------------------------------------------------- MI + null
N_TARGET_BINS = 10   # quantile bins for the (continuous) target in the fast plug-in MI


def mi_discrete_vs_continuous(label: np.ndarray, target: np.ndarray) -> float:
    """KSG MI(discrete label ; continuous target) in nats. SLOW; survivor-confirm only."""
    y = target.reshape(-1, 1)
    mi = mutual_info_classif(y, label, discrete_features=False,
                             n_neighbors=N_NEIGHBORS, random_state=0)
    return float(mi[0])


def _bin_target(target: np.ndarray, bins: int = N_TARGET_BINS) -> np.ndarray:
    """Quantile-bin a continuous target into integer codes (computed ONCE)."""
    s = pd.Series(target)
    return pd.qcut(s.rank(method="first"), bins, labels=False, duplicates="drop").to_numpy().astype(int)


def mi_plugin(label: np.ndarray, tbin: np.ndarray) -> float:
    """Fast plug-in MI(discrete label ; binned target) in nats via a vectorized
    contingency table.  ~1000x faster than KSG; captures nonlinear (non-monotone)
    dependence that Spearman/AUC miss because the target is binned, not ranked.
    Positively biased on sparse cells — but the circular-shift null carries the
    SAME bias, so excess and p are bias-robust."""
    n = len(label)
    lu = np.unique(label); fu = np.unique(tbin)
    li = np.searchsorted(lu, label); fi = np.searchsorted(fu, tbin)
    ct = np.zeros((len(lu), len(fu)))
    np.add.at(ct, (li, fi), 1.0)
    p = ct / n
    ps = p.sum(1, keepdims=True); pf = p.sum(0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        term = p * (np.log(p) - np.log(ps) - np.log(pf))
    return float(np.where(p > 0, term, 0.0).sum())


def circular_shift_null(label: np.ndarray, tbin: np.ndarray, n_null: int) -> np.ndarray:
    """Null MI distribution: rotate the LABEL series, keep the (binned) TARGET fixed.

    Preserves return autocorrelation (target untouched) AND label autocorrelation
    (a circular rotation is structure-preserving).  Min shift keeps the real
    alignment out of the null.
    """
    n = len(label)
    lo, hi = MIN_SHIFT, n - MIN_SHIFT
    shifts = RNG.integers(lo, hi, size=n_null)
    out = np.empty(n_null)
    for i, s in enumerate(shifts):
        out[i] = mi_plugin(np.roll(label, s), tbin)
    return out


def bh_fdr(pvals: np.ndarray, alpha: float = 0.05):
    """Benjamini-Hochberg. Returns boolean reject array and the BH threshold."""
    p = np.asarray(pvals)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order]
    thresh = (np.arange(1, m + 1) / m) * alpha
    passed = ranked <= thresh
    if not passed.any():
        return np.zeros(m, bool), 0.0
    kmax = np.max(np.where(passed)[0])
    cut = ranked[kmax]
    reject = np.zeros(m, bool)
    reject[order[: kmax + 1]] = True
    return reject, float(cut)


# ----------------------------------------------------------------------------- worker
def _worker_init():
    # one BLAS/OpenMP thread per worker process — avoid CPU oversubscription
    for k in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS",
              "NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS"):
        os.environ[k] = "1"


def _asset_worker(sym: str, close: pd.Series, n_null: int, partdir: str) -> str:
    """Compute MI + circular-shift null for every (state,target) of one asset.

    Runs in its own process; seeds its own RNG deterministically from the symbol
    so the surrogate draws are reproducible and independent across assets.
    Writes its own partial CSV so a pool crash never loses completed assets.
    Returns the path written (or '' if cached/empty).
    """
    import hashlib
    partp = os.path.join(partdir, f"part_{sym}.csv")
    if os.path.exists(partp):
        return partp  # resume: already computed
    global RNG
    seed = int(hashlib.md5(f"itstudy::{sym}".encode()).hexdigest()[:8], 16)
    RNG = np.random.default_rng(seed)
    idx = close.index
    states = build_astro_states(idx)
    targets = build_targets(close)
    out = []
    for tname in targets.columns:
        tcol = targets[tname]
        for sname in states.columns:
            lab = states[sname]
            m = pd.concat([lab.rename("lab"), tcol.rename("tgt")], axis=1).dropna()
            if len(m) < 400:
                continue
            L = m["lab"].to_numpy().astype(int)
            Y = m["tgt"].to_numpy().astype(float)
            if len(np.unique(L)) < 2:
                continue
            tbin = _bin_target(Y)                 # quantile-binned ONCE
            mi_obs = mi_plugin(L, tbin)
            null = circular_shift_null(L, tbin, n_null)
            nm, ns = float(null.mean()), float(null.std() + 1e-12)
            z = (mi_obs - nm) / ns
            p = (np.sum(null >= mi_obs) + 1) / (n_null + 1)
            out.append(dict(asset=sym, state=sname, target=tname,
                            mi_obs=mi_obs, null_mean=nm, null_std=ns,
                            excess_nats=mi_obs - nm, z=z, p=p, n=len(m),
                            n_states=int(len(np.unique(L)))))
    pd.DataFrame(out).to_csv(partp, index=False)
    return partp


# ----------------------------------------------------------------------------- driver
def run(universe: str, max_assets: int | None, n_null: int, days: int):
    if universe == "crypto":
        syms = CRYPTO[: max_assets] if max_assets else CRYPTO
        bars = RP.load_crypto_bars(syms, "1d", days=days)
    else:
        syms = EQUITY[: max_assets] if max_assets else EQUITY
        bars = RP.load_equity_bars(syms)

    t0 = time.time()
    jobs = [(sym, df["close"].copy()) for sym, df in bars.items()
            if df is not None and not df.empty and "close" in df]

    partdir = os.path.join(os.path.dirname(__file__), f"_itparts_{universe}")
    os.makedirs(partdir, exist_ok=True)

    # SEQUENTIAL by design: the plug-in MI made each asset ~40s, so 17 assets ~12min.
    # ProcessPoolExecutor + macOS/py3.13 'spawn' deadlocked (workers died on the heavy
    # module re-import); sequential + per-asset resumable partials is robust and plenty
    # fast.  Threads are pinned to 1 to keep numpy from oversubscribing.
    _worker_init()
    for sym, close in jobs:
        try:
            p = _asset_worker(sym, close, n_null, partdir)
            print(f"[{sym}] done  ({time.time()-t0:.0f}s -> {p})", file=sys.stderr)
        except Exception as e:
            print(f"[{sym}] FAILED {e!r}", file=sys.stderr)

    # reassemble from ALL partials present (resilient to a partial crash)
    parts = [pd.read_csv(os.path.join(partdir, f)) for f in os.listdir(partdir)
             if f.startswith("part_") and f.endswith(".csv")]
    res = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if res.empty:
        print(json.dumps({"error": "no cells"})); return res

    bonf = 0.05 / len(res)
    res = res.sort_values("p").reset_index(drop=True)
    bh_rej, bh_cut = bh_fdr(res["p"].to_numpy(), 0.05)
    res["bh_reject_0.05"] = bh_rej
    res["bonf_reject_0.05"] = res["p"] < bonf

    summary = dict(
        universe=universe, n_assets=len(bars), n_cells=int(len(res)),
        n_null=n_null, min_shift=MIN_SHIFT, n_neighbors=N_NEIGHBORS,
        bh_threshold=float(bh_cut), bonferroni_threshold=float(bonf),
        n_bh_survive=int(res["bh_reject_0.05"].sum()),
        n_bonf_survive=int(res["bonf_reject_0.05"].sum()),
        n_p_lt_001=int((res["p"] < 0.01).sum()),
        n_p_lt_005_raw=int((res["p"] < 0.05).sum()),
        expected_false_pos_at_005=float(0.05 * len(res)),
        min_p=float(res["p"].min()),
        max_excess_nats=float(res["excess_nats"].max()),
        elapsed_s=round(time.time() - t0, 1),
    )
    print(json.dumps(summary, indent=2))
    # show top 15 by p
    cols = ["asset","state","target","mi_obs","null_mean","excess_nats","z","p",
            "bh_reject_0.05","bonf_reject_0.05","n","n_states"]
    print("\nTOP 15 BY p:")
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(res[cols].head(15).to_string(index=False))

    outp = os.path.join(os.path.dirname(__file__),
                        f"info_theoretic_results_{universe}.csv")
    res.to_csv(outp, index=False)
    print(f"\nsaved -> {outp}", file=sys.stderr)
    return res, summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["crypto","equity"], default="crypto")
    ap.add_argument("--max-assets", type=int, default=None)
    ap.add_argument("--n-null", type=int, default=N_NULL)
    ap.add_argument("--days", type=int, default=3650)
    a = ap.parse_args()
    run(a.universe, a.max_assets, a.n_null, a.days)
