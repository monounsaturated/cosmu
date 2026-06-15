"""
TRANSFER-ENTROPY / CONDITIONAL-MI astro -> markets study (wave 1, deeper cut).

Goes BEYOND plain MI(state; fwd_ret): asks whether the astro STATE adds information
about the forward outcome BEYOND what the market's OWN recent past already tells us.
That is the transfer-entropy formulation:

    TE_astro->ret  ~  CMI( astro_state ; fwd_ret_bin | past_ret_bin )
                    = I(state ; future | past)

If astro carries genuine *incremental* predictive content, CMI > 0 above a null that
destroys only the astro alignment.  If the only apparent signal was riding on return
autocorrelation/regime, conditioning on the past return kills it.

Estimator
---------
Fully discrete plug-in CMI (all three variables binned), in nats:
    CMI = sum p(s,f,c) * log[ p(f,s|c) / (p(f|c) p(s|c)) ]
    grouped by the conditioning bin c (past-return tercile).
Plug-in CMI is positively biased for sparse cells; we do NOT compare to 0 — we compare
to the CIRCULAR-SHIFT surrogate of the astro label, which carries the identical bias,
so the excess (obs - null_mean) and the empirical p are bias-robust.

Targets binned: fwd_ret sign/tercile, fwd |ret| tercile (vol).
Conditioning: past 1d return tercile (the market's own momentum/mean-reversion state).
Null: circular shift of the astro label only (return & past-return structure preserved).
Multiple testing: BH-FDR across the full asset x state x target grid.
"""
from __future__ import annotations
import sys, os, json, time, argparse, hashlib
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import astro_features_deep as AF
import real_panel as RP
from info_theoretic_study import (CRYPTO, EQUITY, build_astro_states, bh_fdr,
                                  MIN_SHIFT)

N_NULL = 400
RNG = np.random.default_rng(7)


def _terciles(x: np.ndarray) -> np.ndarray:
    """Map to 0/1/2 by terciles (rank-based, ties -> first)."""
    s = pd.Series(x)
    return pd.qcut(s.rank(method="first"), 3, labels=False).to_numpy().astype(int)


def discrete_cmi(s: np.ndarray, f: np.ndarray, c: np.ndarray) -> float:
    """Plug-in conditional MI  I(s ; f | c) in nats, all inputs integer-coded."""
    n = len(s)
    total = 0.0
    for cv in np.unique(c):
        mask = c == cv
        pc = mask.mean()
        sf = np.stack([s[mask], f[mask]], axis=1)
        # joint p(s,f|c)
        ssub, fsub = sf[:, 0], sf[:, 1]
        nsub = len(ssub)
        if nsub < 5:
            continue
        # build contingency
        su = np.unique(ssub); fu = np.unique(fsub)
        if len(su) < 2 or len(fu) < 2:
            continue
        si = {v: i for i, v in enumerate(su)}
        fi = {v: i for i, v in enumerate(fu)}
        joint = np.zeros((len(su), len(fu)))
        for a, b in zip(ssub, fsub):
            joint[si[a], fi[b]] += 1
        joint /= nsub
        ps = joint.sum(1, keepdims=True)
        pf = joint.sum(0, keepdims=True)
        with np.errstate(divide="ignore", invalid="ignore"):
            term = joint * (np.log(joint) - np.log(ps) - np.log(pf))
        term = np.where(joint > 0, term, 0.0)
        total += pc * term.sum()
    return float(total)


def circular_shift_cmi_null(s: np.ndarray, f: np.ndarray, c: np.ndarray,
                            n_null: int) -> np.ndarray:
    n = len(s)
    lo, hi = MIN_SHIFT, n - MIN_SHIFT
    shifts = RNG.integers(lo, hi, size=n_null)
    out = np.empty(n_null)
    for i, sh in enumerate(shifts):
        out[i] = discrete_cmi(np.roll(s, sh), f, c)
    return out


def _worker_init():
    for k in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS",
              "NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS"):
        os.environ[k] = "1"


def _asset_worker(sym: str, close: pd.Series, n_null: int, partdir: str) -> str:
    partp = os.path.join(partdir, f"te_{sym}.csv")
    if os.path.exists(partp):
        return partp
    global RNG
    RNG = np.random.default_rng(int(hashlib.md5(f"te::{sym}".encode()).hexdigest()[:8], 16))
    idx = close.index
    states = build_astro_states(idx)

    logc = np.log(close.astype(float))
    r1 = logc.diff()
    fwd = r1.shift(-1)
    past = r1                      # return realized up to & including t (known at t)
    fwd_sign_terc = _terciles_safe(fwd)
    fwd_abs_terc = _terciles_safe(fwd.abs())
    past_terc = _terciles_safe(past)

    targets = {"fwd_ret_terc": fwd_sign_terc, "fwd_absret_terc": fwd_abs_terc}
    out = []
    base = pd.DataFrame({"past": past_terc}, index=idx)
    for tname, tser in targets.items():
        for sname in states.columns:
            df = pd.concat([states[sname].rename("s"),
                            pd.Series(tser, index=idx, name="f"),
                            base["past"].rename("c")], axis=1).dropna()
            if len(df) < 400:
                continue
            s = df["s"].to_numpy().astype(int)
            f = df["f"].to_numpy().astype(int)
            c = df["c"].to_numpy().astype(int)
            if len(np.unique(s)) < 2 or len(np.unique(f)) < 2:
                continue
            cmi = discrete_cmi(s, f, c)
            null = circular_shift_cmi_null(s, f, c, n_null)
            nm, ns = float(null.mean()), float(null.std() + 1e-12)
            z = (cmi - nm) / ns
            p = (np.sum(null >= cmi) + 1) / (n_null + 1)
            out.append(dict(asset=sym, state=sname, target=tname,
                            cmi_obs=cmi, null_mean=nm, null_std=ns,
                            excess_nats=cmi - nm, z=z, p=p, n=len(df),
                            n_states=int(len(np.unique(s)))))
    pd.DataFrame(out).to_csv(partp, index=False)
    return partp


def _terciles_safe(ser: pd.Series) -> np.ndarray:
    out = np.full(len(ser), np.nan)
    v = ser.to_numpy()
    ok = ~np.isnan(v)
    if ok.sum() >= 9:
        out[ok] = _terciles(v[ok])
    return out


def run(universe: str, max_assets, n_null: int, days: int):
    if universe == "crypto":
        syms = CRYPTO[:max_assets] if max_assets else CRYPTO
        bars = RP.load_crypto_bars(syms, "1d", days=days)
    else:
        syms = EQUITY[:max_assets] if max_assets else EQUITY
        bars = RP.load_equity_bars(syms)

    t0 = time.time()
    jobs = [(s, df["close"].copy()) for s, df in bars.items()
            if df is not None and not df.empty and "close" in df]
    partdir = os.path.join(os.path.dirname(__file__), f"_teparts_{universe}")
    os.makedirs(partdir, exist_ok=True)

    # SEQUENTIAL (see info_theoretic_study: pool deadlocked on macOS/py3.13 spawn).
    _worker_init()
    for s, c in jobs:
        try:
            _asset_worker(s, c, n_null, partdir)
            print(f"[{s}] done ({time.time()-t0:.0f}s)", file=sys.stderr)
        except Exception as e:
            print(f"[{s}] FAILED {e!r}", file=sys.stderr)

    parts = [pd.read_csv(os.path.join(partdir, f)) for f in os.listdir(partdir)
             if f.startswith("te_") and f.endswith(".csv")]
    res = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if res.empty:
        print(json.dumps({"error": "no cells"})); return res
    bonf = 0.05 / len(res)
    res = res.sort_values("p").reset_index(drop=True)
    bh_rej, bh_cut = bh_fdr(res["p"].to_numpy(), 0.05)
    res["bh_reject_0.05"] = bh_rej
    res["bonf_reject_0.05"] = res["p"] < bonf

    summary = dict(
        universe=universe, kind="transfer_entropy_CMI", n_cells=int(len(res)),
        n_null=n_null, bh_threshold=float(bh_cut), bonferroni_threshold=float(bonf),
        n_bh_survive=int(res["bh_reject_0.05"].sum()),
        n_bonf_survive=int(res["bonf_reject_0.05"].sum()),
        n_p_lt_001=int((res["p"] < 0.01).sum()),
        n_p_lt_005_raw=int((res["p"] < 0.05).sum()),
        expected_false_pos_at_005=float(0.05 * len(res)),
        min_p=float(res["p"].min()), max_excess_nats=float(res["excess_nats"].max()),
        elapsed_s=round(time.time() - t0, 1))
    print(json.dumps(summary, indent=2))
    cols = ["asset","state","target","cmi_obs","null_mean","excess_nats","z","p",
            "bh_reject_0.05","bonf_reject_0.05","n","n_states"]
    print("\nTOP 15 BY p:")
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(res[cols].head(15).to_string(index=False))
    outp = os.path.join(os.path.dirname(__file__), f"transfer_entropy_results_{universe}.csv")
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
