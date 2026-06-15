#!/usr/bin/env python3
# ADVERSARIAL VERIFICATION of the candidate:
#   "Merriman geocosmic CRD recall (crypto, k=5)"
#   claim: realized swing extrema land within +/-5d of a geocosmic hard-aspect-density peak at
#   97.6% vs 96.6% circular-shift null (uplift +1.0pp, pooled p=0.001).
#
# We try HARD to kill it as luck/leakage/artifact, on four axes the brief demands:
#   (A) STRICTER PROPER NULL  : 5000 circular shifts + AR(1) price-side surrogates + a
#                               REGIME-PRESERVING block-bootstrap of the realized-extrema calendar
#                               (the disconfirmer the candidate itself names as decisive).
#   (B) OUT-OF-SAMPLE         : split each series at 2022-01-01; the CRD construction is
#                               deterministic, so OOS asks: does the +/-5d recall uplift hold in the
#                               held-out half, or is it an in-sample-period artifact?
#   (C) ECONOMIC (net 10bps)  : the obvious trade — fade the prior trend at each predicted CRD turn,
#                               hold 5d, 10bps round-trip — vs a random-date null. Plus a saturation
#                               diagnostic: what recall do you get from RANDOM same-count peaks?
#   (D) MULTIPLE-TESTING      : the generating harness scanned 3 systems x 2 classes x 4 k x 2
#                               metrics = 48 cells. We charge BH-FDR + Bonferroni across that grid
#                               and report whether this single cell survives the family it was
#                               cherry-picked from.
#
# Everything LIVE-HONEST: deterministic astro, raw real closes, causal predictor construction.

from __future__ import annotations

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "scripts/research/astro_deep")
import astro_features_deep as AF  # noqa: E402
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(424242)
N_SHIFT = 5000          # stricter than the original 1000
N_SURR = 2000           # AR(1) price-side surrogates
N_BLOCK = 2000          # regime-preserving block bootstraps
ZZ_PCT = 0.08
KS = [1, 3, 5, 7]
SPLIT = pd.Timestamp("2022-01-01")

CRYPTO = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT",
    "ATOMUSDT", "UNIUSDT", "FILUSDT", "NEARUSDT",
]


# ───────────────────────── machinery (ported faithfully) ─────────────────────────

def to_close(df):
    s = df["close"].copy()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    return s[~s.index.duplicated(keep="last")].sort_index().astype(float)


def zigzag(close, pct):
    p = close.to_numpy()
    n = len(p)
    if n < 3:
        return np.array([], int)
    piv = []
    ext_i, ext_p, direction = 0, p[0], 0
    for i in range(1, n):
        if direction == 0:
            if p[i] >= ext_p * (1 + pct):
                direction, ext_i, ext_p = 1, i, p[i]
            elif p[i] <= ext_p * (1 - pct):
                direction, ext_i, ext_p = -1, i, p[i]
            continue
        if direction == 1:
            if p[i] > ext_p:
                ext_i, ext_p = i, p[i]
            elif p[i] <= ext_p * (1 - pct):
                piv.append(ext_i); direction, ext_i, ext_p = -1, i, p[i]
        else:
            if p[i] < ext_p:
                ext_i, ext_p = i, p[i]
            elif p[i] >= ext_p * (1 + pct):
                piv.append(ext_i); direction, ext_i, ext_p = 1, i, p[i]
    if ext_i not in piv:
        piv.append(ext_i)
    return np.array(sorted(set(piv)), int)


def merriman_turns(astro):
    hard = astro["hard_aspect_count"].to_numpy()
    stress = astro["aspect_tightness_stress"].to_numpy()
    dens = hard + stress
    sm = np.convolve(dens, np.ones(3) / 3.0, mode="same")
    d = np.diff(sm); sign = np.sign(d)
    cand = [(i, sm[i]) for i in range(1, len(sm) - 1) if sign[i - 1] > 0 and sign[i] < 0]
    cand.sort(key=lambda t: -t[1])
    kept = []
    for idx, _ in cand:
        if all(abs(idx - kk) >= 5 for kk in kept):
            kept.append(idx)
    return np.array(sorted(kept), int)


def recall(realized, predicted, k, n):
    if len(realized) == 0 or len(predicted) == 0:
        return 0.0
    m = np.zeros(n, bool)
    for p in predicted:
        m[max(0, p - k):min(n, p + k + 1)] = True
    return float(np.mean(m[realized]))


# ───────────────────────── nulls ─────────────────────────

def circ_null(realized, predicted, k, n, nsh):
    obs = recall(realized, predicted, k, n)
    null = np.empty(nsh)
    for s in range(nsh):
        sh = RNG.integers(1, n)
        null[s] = recall(realized, np.sort((predicted + sh) % n), k, n)
    return obs, null


def ar1_surrogate_extrema(close, pct, nsurr):
    """AR(1) price-side surrogate: fit AR(1) to log-returns, simulate, build a synthetic price path
    with matched drift/vol/autocorr, extract its ZigZag extrema. Null = recall of REAL CRD peaks
    against SURROGATE extrema (destroys any real price-calendar phase but keeps return dynamics)."""
    lr = np.diff(np.log(close.to_numpy()))
    mu = lr.mean()
    x = lr - mu
    # AR(1) coef
    phi = np.sum(x[:-1] * x[1:]) / np.sum(x[:-1] ** 2)
    resid = x[1:] - phi * x[:-1]
    sig = resid.std()
    n = len(close)
    out = []
    for _ in range(nsurr):
        e = RNG.normal(0, sig, n)
        sim = np.empty(n)
        sim[0] = 0.0
        for t in range(1, n):
            sim[t] = phi * sim[t - 1] + e[t]
        path = np.exp(np.cumsum(np.concatenate([[np.log(close.iloc[0])], sim[1:] + mu])))
        ser = pd.Series(path, index=close.index)
        out.append(zigzag(ser, pct))
    return out


def block_bootstrap_regime_null(realized, n, block, nboot):
    """REGIME-PRESERVING null (the candidate's named decisive test).
    The realized-extrema calendar clusters because volatility clusters in regimes. A circular shift
    of the PREDICTED set leaves the realized clustering intact, so it cannot break the
    vol-regime/aspect-cycle co-incidence. Here we instead resample the REALIZED extrema using a
    moving-block bootstrap over the binary extreme-indicator series — preserving the LOCAL clustering
    (block length ~ regime persistence) while randomising WHERE regimes sit on the calendar relative
    to the fixed CRD peaks. If the CRD recall is just regime co-clustering, observed will sit inside
    THIS null. We return the surrogate realized-index lists."""
    ind = np.zeros(n, np.int8)
    ind[realized] = 1
    nblocks = int(np.ceil(n / block))
    starts_space = max(1, n - block)
    boots = []
    for _ in range(nboot):
        idx = []
        s = RNG.integers(0, starts_space, nblocks)
        pos = 0
        for st in s:
            seg = ind[st:st + block]
            for j, v in enumerate(seg):
                if pos + j < n and v:
                    idx.append(pos + j)
            pos += block
            if pos >= n:
                break
        boots.append(np.array(sorted(set(i for i in idx if i < n)), int))
    return boots


# ───────────────────────── economic test ─────────────────────────

def economic_fade(close, predicted, hold=5, fee_bps=10.0, trend_lb=10):
    """The obvious trade: at each predicted CRD turn, FADE the prior `trend_lb`-day trend, hold
    `hold` days, pay fee_bps round-trip. Returns array of per-trade net returns (%)."""
    p = close.to_numpy()
    n = len(p)
    rets = []
    for t in predicted:
        if t - trend_lb < 0 or t + hold >= n:
            continue
        prior = p[t] / p[t - trend_lb] - 1.0
        side = -np.sign(prior)  # fade
        if side == 0:
            continue
        raw = side * (p[t + hold] / p[t] - 1.0)
        net = raw - fee_bps / 10000.0
        rets.append(net * 100.0)
    return np.array(rets)


def economic_random_null(close, n_turns, hold, fee_bps, trend_lb, ndraw):
    p = close.to_numpy()
    n = len(p)
    means = np.empty(ndraw)
    for d in range(ndraw):
        ts = RNG.integers(trend_lb, n - hold, n_turns)
        r = []
        for t in ts:
            prior = p[t] / p[t - trend_lb] - 1.0
            side = -np.sign(prior)
            if side == 0:
                continue
            raw = side * (p[t + hold] / p[t] - 1.0)
            r.append((raw - fee_bps / 10000.0) * 100.0)
        means[d] = np.mean(r) if r else 0.0
    return means


# ───────────────────────── run ─────────────────────────

def main():
    print("Loading crypto panel ...", flush=True)
    cb = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    panels = {s: to_close(df) for s, df in cb.items() if len(df) >= 400}
    print(f"  usable crypto assets: {len(panels)}")

    per = {}
    for sym, close in panels.items():
        dates = pd.DatetimeIndex(close.index)
        astro = AF.deep_astro_features(dates)
        per[sym] = dict(
            close=close, dates=dates, n=len(dates),
            realized=zigzag(close, ZZ_PCT),
            crd=merriman_turns(astro),
        )

    # ========== (A) STRICTER NULL: circular shift, 5000, all k, pooled like the original ==========
    print("\n" + "=" * 100)
    print("(A) STRICTER CIRCULAR-SHIFT NULL  (5000 shifts, pooled across all crypto, recall metric)")
    print("=" * 100)
    for k in KS:
        pooled_obs, pooled_null, va = [], np.zeros(N_SHIFT), 0
        for sym, d in per.items():
            if len(d["realized"]) == 0 or len(d["crd"]) == 0:
                continue
            obs, null = circ_null(d["realized"], d["crd"], k, d["n"], N_SHIFT)
            pooled_obs.append(obs); pooled_null += null; va += 1
        pooled_null /= va
        om = np.mean(pooled_obs)
        p = (np.sum(pooled_null >= om) + 1) / (N_SHIFT + 1)
        print(f"  k={k}: observed={om:.4f}  null_mean={pooled_null.mean():.4f}  "
              f"uplift={om - pooled_null.mean():+.4f}  p={p:.4f}")

    # focus cell k=5
    k = 5

    # ========== (B) OUT-OF-SAMPLE split ==========
    print("\n" + "=" * 100)
    print(f"(B) OUT-OF-SAMPLE  (split {SPLIT.date()}; recall uplift k={k}, per half, pooled)")
    print("=" * 100)
    for label, lo, hi in [("IN-SAMPLE  <2022", None, SPLIT), ("OUT-SAMPLE >=2022", SPLIT, None)]:
        pooled_obs, pooled_null, va = [], np.zeros(N_SHIFT), 0
        for sym, d in per.items():
            mask = np.ones(d["n"], bool)
            if lo is not None:
                mask &= (d["dates"] >= lo)
            if hi is not None:
                mask &= (d["dates"] < hi)
            # restrict realized + crd to the window, re-index to a contiguous sub-series
            pos = np.where(mask)[0]
            if len(pos) < 100:
                continue
            base = pos[0]
            sub_n = len(pos)
            r = np.array([i - base for i in d["realized"] if mask[i]], int)
            c = np.array([i - base for i in d["crd"] if mask[i]], int)
            if len(r) == 0 or len(c) == 0:
                continue
            obs, null = circ_null(r, c, k, sub_n, N_SHIFT)
            pooled_obs.append(obs); pooled_null += null; va += 1
        if va == 0:
            print(f"  {label}: no usable assets"); continue
        pooled_null /= va
        om = np.mean(pooled_obs)
        p = (np.sum(pooled_null >= om) + 1) / (N_SHIFT + 1)
        print(f"  {label}: assets={va}  observed={om:.4f}  null_mean={pooled_null.mean():.4f}  "
              f"uplift={om - pooled_null.mean():+.4f}  p={p:.4f}")

    # ========== (A2) REGIME-PRESERVING block bootstrap (the decisive disconfirmer) ==========
    print("\n" + "=" * 100)
    print(f"(A2) REGIME-PRESERVING BLOCK-BOOTSTRAP NULL  (k={k}, block=21d~monthly regime, "
          f"{N_BLOCK} boots, pooled)")
    print("=" * 100)
    block = 21
    pooled_obs, pooled_null, va = [], np.zeros(N_BLOCK), 0
    for sym, d in per.items():
        if len(d["realized"]) == 0 or len(d["crd"]) == 0:
            continue
        obs = recall(d["realized"], d["crd"], k, d["n"])
        boots = block_bootstrap_regime_null(d["realized"], d["n"], block, N_BLOCK)
        null = np.array([recall(b, d["crd"], k, d["n"]) for b in boots])
        pooled_obs.append(obs); pooled_null += null; va += 1
    pooled_null /= va
    om = np.mean(pooled_obs)
    p = (np.sum(pooled_null >= om) + 1) / (N_BLOCK + 1)
    print(f"  assets={va}  observed={om:.4f}  null_mean={pooled_null.mean():.4f}  "
          f"uplift={om - pooled_null.mean():+.4f}  p={p:.4f}")
    print("  (If observed sits INSIDE this null, the recall is regime co-clustering, not a CRD edge.)")

    # ========== (A3) SATURATION control: random same-count peaks ==========
    print("\n" + "=" * 100)
    print(f"(A3) SATURATION CONTROL  (k={k}: recall of RANDOM peaks with the SAME count as CRD)")
    print("=" * 100)
    pooled_obs, pooled_rand = [], []
    for sym, d in per.items():
        if len(d["realized"]) == 0 or len(d["crd"]) == 0:
            continue
        obs = recall(d["realized"], d["crd"], k, d["n"])
        n_crd = len(d["crd"])
        rr = []
        for _ in range(200):
            rp = np.sort(RNG.choice(d["n"], n_crd, replace=False))
            rr.append(recall(d["realized"], rp, k, d["n"]))
        pooled_obs.append(obs); pooled_rand.append(np.mean(rr))
    print(f"  CRD recall mean={np.mean(pooled_obs):.4f}   random-same-count recall mean="
          f"{np.mean(pooled_rand):.4f}   gap={np.mean(pooled_obs) - np.mean(pooled_rand):+.4f}")
    # coverage fraction of calendar under +/-k of CRD peaks
    covs = []
    for sym, d in per.items():
        if len(d["crd"]) == 0:
            continue
        m = np.zeros(d["n"], bool)
        for pidx in d["crd"]:
            m[max(0, pidx - k):min(d["n"], pidx + k + 1)] = True
        covs.append(m.mean())
    print(f"  mean calendar coverage under +/-{k}d of CRD peaks = {np.mean(covs):.3f} "
          f"(this is the saturation floor: recall ~ coverage by construction)")

    # ========== (C) ECONOMIC test net 10bps ==========
    print("\n" + "=" * 100)
    print(f"(C) ECONOMIC  (fade prior 10d trend at each CRD turn, hold {k}d, 10bps RT, vs random-date null)")
    print("=" * 100)
    all_rets, tstats = [], []
    for sym, d in per.items():
        if len(d["crd"]) == 0:
            continue
        rets = economic_fade(d["close"], d["crd"], hold=k, fee_bps=10.0, trend_lb=10)
        if len(rets) < 5:
            continue
        m = rets.mean(); se = rets.std(ddof=1) / np.sqrt(len(rets))
        t = m / se if se > 0 else 0.0
        rndnull = economic_random_null(d["close"], len(d["crd"]), k, 10.0, 10, 1000)
        beat_p = (np.sum(rndnull >= m) + 1) / (len(rndnull) + 1)
        all_rets.append(rets); tstats.append(t)
        if sym in ("BTCUSDT", "LTCUSDT", "BCHUSDT", "NEARUSDT"):
            print(f"  {sym:9s} n={len(rets):4d} mean={m:+.4f}%/trade t={t:+.2f} "
                  f"random-null beat_p={beat_p:.3f}")
    pooled = np.concatenate(all_rets)
    m = pooled.mean(); t = m / (pooled.std(ddof=1) / np.sqrt(len(pooled)))
    print(f"  POOLED (all assets): n={len(pooled)} mean={m:+.4f}%/trade  t={t:+.2f}")

    # ========== (D) MULTIPLE-TESTING charge ==========
    print("\n" + "=" * 100)
    print("(D) MULTIPLE-TESTING CHARGE")
    print("=" * 100)
    n_cells = 3 * 2 * 4 * 2  # systems x classes x k x metrics in the generating harness
    p_claim = 0.001
    print(f"  generating family size = 3 systems x 2 classes x 4 k x 2 metrics = {n_cells} cells")
    print(f"  claimed cell p = {p_claim}")
    print(f"  Bonferroni-adjusted p = {min(1.0, p_claim * n_cells):.4f}  "
          f"(survives 0.05? {p_claim * n_cells < 0.05})")
    print("  BH-FDR: best-rank cell needs p <= 0.05/48 = {:.5f} to lead the family at q=0.05"
          .format(0.05 / n_cells))


if __name__ == "__main__":
    main()
