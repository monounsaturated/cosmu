#!/usr/bin/env python3
# intent: ADVERSARIAL verification of the "Gann master-time-factor recall/precision" candidate.
#
# Claim under test: Gann-interval turns projected forward from each series' OWN ZigZag pivots hit
# realized extrema marginally above their circular-shift null across several k (crypto precision@3
# 0.571 vs 0.553 null p=0.001; equity recall@5 0.506 vs 0.425 null p=0.002, max uplift +0.085).
#
# Suspected mechanism (the candidate's own p_real): the Gann predictor is anchored on each series'
# OWN ZigZag pivots, so projected turns are partially co-derived with the price-swing structure
# being scored. The circular-shift null only shifts the interval comb; it does NOT break the
# anchor->realized co-derivation, nor the comb's affinity for periodic swing spacing.
#
# FOUR HARDENING TESTS:
#  (1) STRICTER / PROPER NULL — three nulls, not one:
#        (a) circular-shift of the PREDICTED set (the original; co-derivation NOT broken)
#        (b) ANCHOR-LEAK control: project Gann intervals from RANDOM-but-matched-count anchor dates
#            (drawn with the SAME inter-anchor spacing distribution as the real pivots) — if the
#            uplift persists it is a calendar-comb artifact; if it vanishes it was pivot
#            co-derivation. This is the decisive disconfirmer.
#        (c) CIRCULAR-SHIFT-OF-ANCHORS: shift the anchor positions (preserving their spacing) then
#            re-project the SAME Gann comb — isolates "is it the real pivot LOCATIONS or just the
#            comb geometry?" without changing anchor count or spacing.
#  (2) OUT-OF-SAMPLE — split each series at its temporal midpoint; fit anchors only on the FIRST
#        half, project strictly forward, score realized extrema in the SECOND half. Honest forward
#        use of the predictor (no future pivots).
#  (3) ECONOMIC — net-of-fee reversal-capture PnL: at each projected turn date, take the Merriman-
#        style mean-reversion trade (fade the prior swing) held to the next realized pivot or a
#        horizon, charge 10bps round-trip. Report mean net return per signal + t-stat.
#  (4) MULTIPLE-TESTING CHARGE — the candidate was the best of a (3 systems x 2 classes x 2 metrics
#        x 4 k = 48)-cell scan PLUS this verification adds its own cells; we BH-FDR and Bonferroni
#        over the Gann-only grid actually tested here and report the deflated significance.
#
# LIVE-HONEST: deterministic astro not even needed for Gann (intervals are calendar harmonics);
# anchors are strictly causal pivots; realized extrema from REAL close. The OOS split makes the
# predictor genuinely forward-only.

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

sys.path.insert(0, "scripts/research/astro_deep")
sys.path.insert(0, "scripts/research/astro_strategy_lab")
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(20260615)
N_SURR = 2000  # stricter than the original 1000

_GANN_INTERVALS = [30, 45, 60, 90, 120, 144, 180, 270, 360]
ZZ_PCT = 0.08
GANN_ANCHOR_PCT = 0.15
KS = [1, 3, 5, 7]
FEE_RT = 0.0010  # 10 bps round-trip


# ───────────────────────── price / extrema machinery (verbatim from original) ─────────────────


def _to_daily_close(df: pd.DataFrame) -> pd.Series:
    s = df["close"].copy()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.astype(float)


def zigzag_extrema(close: pd.Series, pct: float) -> np.ndarray:
    p = close.to_numpy()
    n = len(p)
    if n < 3:
        return np.array([], dtype=int)
    pivots: list[int] = []
    ext_i = 0
    ext_p = p[0]
    direction = 0
    for i in range(1, n):
        if direction == 0:
            if p[i] >= ext_p * (1 + pct):
                direction = 1
                ext_i, ext_p = i, p[i]
            elif p[i] <= ext_p * (1 - pct):
                direction = -1
                ext_i, ext_p = i, p[i]
            continue
        if direction == 1:
            if p[i] > ext_p:
                ext_i, ext_p = i, p[i]
            elif p[i] <= ext_p * (1 - pct):
                pivots.append(ext_i)
                direction = -1
                ext_i, ext_p = i, p[i]
        else:
            if p[i] < ext_p:
                ext_i, ext_p = i, p[i]
            elif p[i] >= ext_p * (1 + pct):
                pivots.append(ext_i)
                direction = 1
                ext_i, ext_p = i, p[i]
    if ext_i not in pivots:
        pivots.append(ext_i)
    return np.array(sorted(set(pivots)), dtype=int)


def zigzag_signed(close: pd.Series, pct: float) -> list[tuple[int, int]]:
    """Same ZigZag but return (positional idx, +1 high / -1 low) so we can sign reversal trades."""
    p = close.to_numpy()
    n = len(p)
    out: list[tuple[int, int]] = []
    if n < 3:
        return out
    ext_i = 0
    ext_p = p[0]
    direction = 0
    for i in range(1, n):
        if direction == 0:
            if p[i] >= ext_p * (1 + pct):
                direction = 1
                ext_i, ext_p = i, p[i]
            elif p[i] <= ext_p * (1 - pct):
                direction = -1
                ext_i, ext_p = i, p[i]
            continue
        if direction == 1:
            if p[i] > ext_p:
                ext_i, ext_p = i, p[i]
            elif p[i] <= ext_p * (1 - pct):
                out.append((ext_i, +1))  # confirmed a HIGH
                direction = -1
                ext_i, ext_p = i, p[i]
        else:
            if p[i] < ext_p:
                ext_i, ext_p = i, p[i]
            elif p[i] >= ext_p * (1 + pct):
                out.append((ext_i, -1))  # confirmed a LOW
                direction = 1
                ext_i, ext_p = i, p[i]
    return out


# ───────────────────────── Gann projection ─────────────────────────


def project_gann(dates: pd.DatetimeIndex, anchors: np.ndarray) -> np.ndarray:
    """Project the Gann comb forward (calendar days -> nearest trading idx) from given anchors."""
    n = len(dates)
    if len(anchors) == 0:
        return np.array([], dtype=int)
    turns: set[int] = set()
    for a in anchors:
        a_date = dates[a]
        for iv in _GANN_INTERVALS:
            tgt = a_date + pd.Timedelta(days=iv)
            if tgt > dates[-1]:
                continue
            pos = dates.searchsorted(tgt)
            if pos >= n:
                pos = n - 1
            if pos > 0 and abs((dates[pos - 1] - tgt).days) < abs((dates[pos] - tgt).days):
                pos = pos - 1
            if pos > a:
                turns.add(int(pos))
    return np.array(sorted(turns), dtype=int)


def gann_turns(dates: pd.DatetimeIndex, close: pd.Series, anchor_pct: float) -> np.ndarray:
    return project_gann(dates, zigzag_extrema(close, anchor_pct))


# ───────────────────────── scoring ─────────────────────────


def recall_hit_rate(realized: np.ndarray, predicted: np.ndarray, k: int, n: int) -> float:
    if len(realized) == 0 or len(predicted) == 0:
        return 0.0
    pred_mask = np.zeros(n, dtype=bool)
    for p in predicted:
        lo, hi = max(0, p - k), min(n, p + k + 1)
        pred_mask[lo:hi] = True
    return float(np.mean([pred_mask[r] for r in realized]))


def precision_hit_rate(realized: np.ndarray, predicted: np.ndarray, k: int, n: int) -> float:
    if len(realized) == 0 or len(predicted) == 0:
        return 0.0
    real_mask = np.zeros(n, dtype=bool)
    for r in realized:
        lo, hi = max(0, r - k), min(n, r + k + 1)
        real_mask[lo:hi] = True
    return float(np.mean([real_mask[p] for p in predicted]))


METRICS = {"recall": recall_hit_rate, "precision": precision_hit_rate}


# ───────────────────────── nulls ─────────────────────────


def _matched_random_anchors(real_anchors: np.ndarray, n: int) -> np.ndarray:
    """Random anchors with the SAME count and (approx) inter-anchor SPACING distribution.

    We resample the gaps between real anchors, lay them down from a random start, wrap if needed.
    Preserves how often Gann fires (count) and the spacing structure, but destroys the real pivot
    LOCATIONS (so any genuine pivot->realized co-derivation is broken)."""
    m = len(real_anchors)
    if m == 0:
        return np.array([], dtype=int)
    if m == 1:
        return np.array([RNG.integers(0, max(1, n - 360))], dtype=int)
    gaps = np.diff(np.sort(real_anchors))
    gaps = gaps[gaps > 0]
    if len(gaps) == 0:
        return np.sort(RNG.choice(n, size=m, replace=False))
    perm = RNG.permutation(gaps)
    start = int(RNG.integers(0, n))
    pos = start
    out = [pos % n]
    for g in perm:
        pos = pos + int(g)
        out.append(pos % n)
    out = sorted(set(int(x) for x in out if 0 <= x < n))
    # keep count matched as closely as possible
    if len(out) > m:
        out = sorted(RNG.choice(out, size=m, replace=False))
    return np.array(out, dtype=int)


@dataclass
class Cell:
    asset_class: str
    metric: str
    k: int
    n_assets: int
    n_pred_mean: float
    observed: float
    # null (a) circular shift of predictions
    nullA_mean: float
    nullA_p: float
    upliftA: float
    # null (b) random matched-count/spacing anchors -> re-projected comb (anchor-leak control)
    nullB_mean: float
    nullB_p: float
    upliftB: float
    # null (c) circular-shift of anchors -> re-projected comb
    nullC_mean: float
    nullC_p: float
    upliftC: float


def bh_fdr(pvals, q=0.05):
    m = len(pvals)
    if m == 0:
        return []
    order = np.argsort(pvals)
    sorted_p = np.array(pvals)[order]
    thresh = q * (np.arange(1, m + 1) / m)
    passed = sorted_p <= thresh
    if not passed.any():
        return [False] * m
    kmax = np.max(np.where(passed)[0])
    cut = sorted_p[kmax]
    return [p <= cut for p in pvals]


# ───────────────────────── per-asset evaluation ─────────────────────────


def eval_asset_full(dates, close, n):
    """Full-sample observed + the three nulls for every (metric,k). Returns nested dict."""
    real_anchors = zigzag_extrema(close, GANN_ANCHOR_PCT)
    realized = zigzag_extrema(close, ZZ_PCT)
    predicted = project_gann(dates, real_anchors)
    if len(realized) == 0 or len(predicted) == 0 or len(real_anchors) == 0:
        return None

    out = {}
    for mname, mfn in METRICS.items():
        for k in KS:
            obs = mfn(realized, predicted, k, n)
            # null A: circular shift of predictions
            nullA = np.empty(N_SURR)
            # null C: circular shift of anchors, re-project
            nullC = np.empty(N_SURR)
            # null B: random matched anchors, re-project
            nullB = np.empty(N_SURR)
            for s in range(N_SURR):
                shp = (predicted + RNG.integers(1, n)) % n
                nullA[s] = mfn(realized, np.sort(shp), k, n)

                sha = (real_anchors + RNG.integers(1, n)) % n
                predC = project_gann(dates, np.sort(sha))
                nullC[s] = mfn(realized, predC, k, n) if len(predC) else 0.0

                ra = _matched_random_anchors(real_anchors, n)
                predB = project_gann(dates, ra)
                nullB[s] = mfn(realized, predB, k, n) if len(predB) else 0.0
            out[(mname, k)] = dict(
                obs=obs, n_pred=len(predicted),
                nullA=nullA, nullB=nullB, nullC=nullC,
            )
    return out


def eval_asset_oos(dates, close, n):
    """OOS: anchors from FIRST half only, project forward, score realized extrema in SECOND half."""
    mid = n // 2
    close_first = close.iloc[:mid]
    real_anchors = zigzag_extrema(close_first, GANN_ANCHOR_PCT)  # train-half pivots only
    realized_all = zigzag_extrema(close, ZZ_PCT)
    realized_oos = realized_all[realized_all >= mid]
    predicted = project_gann(dates, real_anchors)
    predicted_oos = predicted[predicted >= mid]
    if len(realized_oos) == 0 or len(predicted_oos) == 0:
        return None
    out = {}
    for mname, mfn in METRICS.items():
        for k in KS:
            # restrict scoring to the second-half window [mid, n)
            obs = mfn(realized_oos, predicted_oos, k, n)
            nullA = np.empty(N_SURR)
            for s in range(N_SURR):
                # shift only within the OOS window to keep the null honest to that region
                sh = RNG.integers(1, n - mid)
                shifted = mid + ((predicted_oos - mid + sh) % (n - mid))
                nullA[s] = mfn(realized_oos, np.sort(shifted), k, n)
            out[(mname, k)] = dict(obs=obs, n_pred=len(predicted_oos), nullA=nullA)
    return out


# ───────────────────────── economic test ─────────────────────────


def economic_reversal_pnl(dates, close, hold_max=10):
    """Net-of-fee reversal-capture PnL at Gann-projected turn dates.

    Trade rule (Merriman-style fade): at a projected turn date t, infer the prevailing swing from
    the most recent confirmed pivot before t; FADE it (if last pivot was a low -> price has been
    rising into t -> SHORT for a top; if last pivot was a high -> LONG for a bottom). Hold until the
    next realized pivot or hold_max days, whichever first. Net of 10bps round-trip.
    Returns array of per-trade net returns."""
    p = close.to_numpy()
    n = len(p)
    anchors = zigzag_extrema(close, GANN_ANCHOR_PCT)
    predicted = project_gann(dates, anchors)
    signed = zigzag_signed(close, ZZ_PCT)
    pivot_idx = np.array([i for i, _ in signed])
    pivot_dir = np.array([d for _, d in signed])
    rets = []
    for t in predicted:
        if t >= n - 1:
            continue
        # last confirmed pivot strictly before t
        prior = pivot_idx[pivot_idx < t]
        if len(prior) == 0:
            continue
        last_dir = pivot_dir[pivot_idx < t][-1]
        # last pivot was a LOW (-1) -> price rising into t -> expect a TOP -> SHORT (-1)
        # last pivot was a HIGH (+1) -> price falling into t -> expect a BOTTOM -> LONG (+1)
        side = -1 if last_dir == -1 else +1
        # exit at next realized pivot after t, capped at hold_max
        nxt = pivot_idx[pivot_idx > t]
        exit_i = min(int(nxt[0]) if len(nxt) else t + hold_max, t + hold_max, n - 1)
        if exit_i <= t:
            continue
        gross = side * (p[exit_i] / p[t] - 1.0)
        rets.append(gross - FEE_RT)
    return np.array(rets)


# ───────────────────────── main driver ─────────────────────────


def run():
    crypto = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
        "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT",
        "ATOMUSDT", "UNIUSDT", "FILUSDT", "NEARUSDT",
    ]
    equity = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "USO"]

    print("Loading REAL price panels ...", flush=True)
    cbars = RP.load_crypto_bars(crypto, "1d", days=3650)
    ebars = RP.load_equity_bars(equity)
    panels = {"crypto": {}, "equity": {}}
    for s, df in cbars.items():
        if len(df) >= 400:
            panels["crypto"][s] = _to_daily_close(df)
    for s, df in ebars.items():
        if len(df) >= 400:
            panels["equity"][s] = _to_daily_close(df)
    print(f"  crypto usable={len(panels['crypto'])}  equity usable={len(panels['equity'])}", flush=True)

    # ── precompute per-asset full + oos eval ──
    full = {"crypto": {}, "equity": {}}
    oos = {"crypto": {}, "equity": {}}
    econ = {"crypto": [], "equity": []}
    for ac in ("crypto", "equity"):
        for sym, close in panels[ac].items():
            dates = pd.DatetimeIndex(close.index)
            n = len(dates)
            fr = eval_asset_full(dates, close, n)
            if fr is not None:
                full[ac][sym] = fr
            orr = eval_asset_oos(dates, close, n)
            if orr is not None:
                oos[ac][sym] = orr
            econ[ac].append(economic_reversal_pnl(dates, close))
            print(f"  done {ac} {sym}", flush=True)

    # ── aggregate full-sample cells (pool across assets) ──
    cells: list[Cell] = []
    for ac in ("crypto", "equity"):
        assets = full[ac]
        if not assets:
            continue
        for mname in METRICS:
            for k in KS:
                obs_l, npred_l = [], []
                nA = np.zeros(N_SURR); nB = np.zeros(N_SURR); nC = np.zeros(N_SURR)
                va = 0
                for sym, res in assets.items():
                    cell = res[(mname, k)]
                    obs_l.append(cell["obs"]); npred_l.append(cell["n_pred"])
                    nA += cell["nullA"]; nB += cell["nullB"]; nC += cell["nullC"]
                    va += 1
                nA /= va; nB /= va; nC /= va
                obs = float(np.mean(obs_l))
                pA = float((np.sum(nA >= obs) + 1) / (N_SURR + 1))
                pB = float((np.sum(nB >= obs) + 1) / (N_SURR + 1))
                pC = float((np.sum(nC >= obs) + 1) / (N_SURR + 1))
                cells.append(Cell(
                    asset_class=ac, metric=mname, k=k, n_assets=va,
                    n_pred_mean=float(np.mean(npred_l)),
                    observed=obs,
                    nullA_mean=float(np.mean(nA)), nullA_p=pA, upliftA=obs - float(np.mean(nA)),
                    nullB_mean=float(np.mean(nB)), nullB_p=pB, upliftB=obs - float(np.mean(nB)),
                    nullC_mean=float(np.mean(nC)), nullC_p=pC, upliftC=obs - float(np.mean(nC)),
                ))

    cdf = pd.DataFrame([asdict(c) for c in cells])
    # multiple-testing across the cells we actually scored here (16 = 2 class x 2 metric x 4 k)
    cdf["bhB_reject"] = bh_fdr(cdf["nullB_p"].tolist(), q=0.05)
    cdf["bonfB_reject"] = cdf["nullB_p"] < (0.05 / len(cdf))
    cdf["bhA_reject"] = bh_fdr(cdf["nullA_p"].tolist(), q=0.05)

    pd.set_option("display.width", 240)
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.float_format", lambda x: f"{x:.4f}")
    print("\n" + "=" * 130)
    print(f"GANN ADVERSARIAL VERIFY — {len(cdf)} cells, {N_SURR} surrogates each, 3 nulls")
    print("  nullA = circ-shift predictions (orig)  |  nullB = RANDOM matched anchors (anchor-leak control)  |  nullC = circ-shift anchors")
    print("=" * 130)
    show = ["asset_class", "metric", "k", "n_pred_mean", "observed",
            "nullA_mean", "upliftA", "nullA_p",
            "nullB_mean", "upliftB", "nullB_p", "bhB_reject",
            "nullC_mean", "upliftC", "nullC_p"]
    print(cdf[show].to_string(index=False))

    # ── the two headline cells from the candidate ──
    def grab(ac, metric, k):
        r = cdf[(cdf.asset_class == ac) & (cdf.metric == metric) & (cdf.k == k)]
        return r.iloc[0] if len(r) else None
    head1 = grab("crypto", "precision", 3)
    head2 = grab("equity", "recall", 5)
    print("\n── HEADLINE CELLS (the candidate's two flagged numbers) ──")
    for nm, r in [("crypto precision@3", head1), ("equity recall@5", head2)]:
        if r is None:
            continue
        print(f"  {nm}: obs={r.observed:.4f}  "
              f"[A] null={r.nullA_mean:.4f} up={r.upliftA:+.4f} p={r.nullA_p:.4f}  "
              f"[B] null={r.nullB_mean:.4f} up={r.upliftB:+.4f} p={r.nullB_p:.4f}  "
              f"[C] null={r.nullC_mean:.4f} up={r.upliftC:+.4f} p={r.nullC_p:.4f}")

    # ── OOS aggregate ──
    print("\n── OUT-OF-SAMPLE (train-half anchors → score 2nd-half extrema) ──")
    oos_rows = []
    for ac in ("crypto", "equity"):
        assets = oos[ac]
        if not assets:
            continue
        for mname in METRICS:
            for k in KS:
                obs_l = []; nA = np.zeros(N_SURR); va = 0
                for sym, res in assets.items():
                    if (mname, k) not in res:
                        continue
                    obs_l.append(res[(mname, k)]["obs"]); nA += res[(mname, k)]["nullA"]; va += 1
                if va == 0:
                    continue
                nA /= va; obs = float(np.mean(obs_l))
                p = float((np.sum(nA >= obs) + 1) / (N_SURR + 1))
                oos_rows.append(dict(asset_class=ac, metric=mname, k=k, n_assets=va,
                                     observed=obs, nullA_mean=float(np.mean(nA)),
                                     uplift=obs - float(np.mean(nA)), p=p))
    odf = pd.DataFrame(oos_rows)
    odf["bh_reject"] = bh_fdr(odf["p"].tolist(), q=0.05)
    print(odf.to_string(index=False))
    oos_head = odf[((odf.asset_class == "crypto") & (odf.metric == "precision") & (odf.k == 3)) |
                   ((odf.asset_class == "equity") & (odf.metric == "recall") & (odf.k == 5))]
    print("OOS headline cells:")
    print(oos_head.to_string(index=False))

    # ── economic ──
    print("\n── ECONOMIC (net-of-10bps reversal-capture PnL at projected turns) ──")
    econ_rows = []
    for ac in ("crypto", "equity"):
        allr = np.concatenate([r for r in econ[ac] if len(r)]) if any(len(r) for r in econ[ac]) else np.array([])
        if len(allr) == 0:
            continue
        mu = float(np.mean(allr)); sd = float(np.std(allr, ddof=1))
        t = mu / (sd / np.sqrt(len(allr))) if sd > 0 else 0.0
        wr = float(np.mean(allr > 0))
        econ_rows.append(dict(asset_class=ac, n_trades=len(allr),
                              mean_net=mu, t_stat=t, win_rate=wr,
                              total_net=float(np.sum(allr))))
    edf = pd.DataFrame(econ_rows)
    print(edf.to_string(index=False))

    # ── VERDICT ──
    # survives(null) = the anchor-leak control (B) still beats observed AND survives BH.
    headB_p = [r.nullB_p for r in [head1, head2] if r is not None]
    headB_up = [r.upliftB for r in [head1, head2] if r is not None]
    headA_up = [r.upliftA for r in [head1, head2] if r is not None]
    survives_null = bool(cdf["bhB_reject"].any())  # ANY cell beats the proper anchor-leak null
    # OOS holds = headline OOS cells significant after BH
    oos_holds = bool(oos_head["bh_reject"].any()) if len(oos_head) else False
    # economic = mean net per trade > 0 with t>2 in at least one class
    economic = bool((edf["mean_net"] > 0).any() and (edf["t_stat"] > 2).any()) if len(edf) else False

    survives = survives_null and oos_holds and economic

    verdict = dict(
        name="Gann master-time-factor recall/precision (crypto+equity, k=3-7)",
        survives=survives,
        survives_anchor_leak_null=survives_null,
        oos_holds=oos_holds,
        economic=economic,
        headline_upliftA=headA_up,           # vs original (weak) null
        headline_upliftB=headB_up,           # vs proper anchor-leak null
        headline_nullB_p=headB_p,
        econ=edf.to_dict("records") if len(edf) else [],
    )
    print("\n" + "=" * 130)
    print("VERDICT_JSON " + json.dumps(verdict))
    return verdict


if __name__ == "__main__":
    run()
