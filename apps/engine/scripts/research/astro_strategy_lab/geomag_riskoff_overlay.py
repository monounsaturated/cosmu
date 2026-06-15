#!/usr/bin/env python3
"""GEOMAG RISK-OFF OVERLAY — is the −25bps post-storm effect a TRADEABLE risk-off rule, net of fees?

LENS "combo_and_geomag" (second half). Prior work (geomag_kr_study, geomag_kr_adversarial_verify) found the
−25bps post-storm contrast has the RIGHT sign and a real mechanism but p_circ≈0.11 and decays. Here we test it as
the actual STRATEGY the operator would run: an EW-crypto long position that goes FLAT (reduces exposure) on
"stormy" days, vs always-long buy&hold. The question is purely economic + honest-null:

  position_t = 0 on a storm day (last `TRAIL` days had a >=`PCTL`-pctl Kp), else 1.  (risk-OFF overlay)
  daily strat ret = position_t * fwd_ret_t  −  cost on each position change (10bps round-trip).

PIT: Kp lagged 1 trading day (GFZ nowcasts revise); storm label knowable at the open of the next day.
OOS: chronological 65/35 holdout. PROPER null: circular-shift of the storm-label series vs returns (preserves
the 27-day-rotation clustering of Kp AND the autocorrelation of returns; destroys only their alignment).
ECONOMIC: net of 10bps, must BEAT always-long buy&hold on the SAME (OOS) window. Pre-registered single cell
(h=1, pctl=90, trail=6) — the one the prior study surfaced — so the trial count is 1 (no fresh search/deflation).
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "scripts/research/astro_deep")
sys.path.insert(0, "scripts/research/astro_strategy_lab")
import extra_signals as ES  # noqa: E402
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(20260615)

CRYPTO = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
          "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT"]
PCTL = 90          # pre-registered storm threshold (the prior candidate cell)
TRAIL = 6          # trailing window for "last week was stormy"
RT_COST_BPS = 10.0
OOS_FRAC = 0.35
N_NULL = 5000
TRADING_DAYS = 365


def ew_logret(panel: dict) -> pd.Series:
    """Equal-weight daily log-return index across the crypto universe (the thing the overlay trades)."""
    rets = []
    for s, b in panel.items():
        if len(b) < 200:
            continue
        lr = np.log(b["close"].astype(float)).diff().rename(s)
        rets.append(lr)
    df = pd.concat(rets, axis=1)
    return df.mean(axis=1).dropna().rename("ew")


def storm_label(kp: pd.Series, pctl: float, trail: int) -> pd.Series:
    thr = np.nanpercentile(kp.to_numpy(float), pctl)
    hot = (kp >= thr).astype(float)
    return hot.rolling(trail, min_periods=1).max().rename("storm")


def sharpe(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if len(x) < 30 or x.std(ddof=0) == 0:
        return 0.0
    return float(x.mean() / x.std(ddof=0) * np.sqrt(TRADING_DAYS))


def ann_ret(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if not len(x):
        return 0.0
    return float(np.expm1(x.sum() * TRADING_DAYS / len(x)))   # x are log-returns


def overlay_strat(storm: np.ndarray, fwd_log: np.ndarray, cost_bps: float) -> np.ndarray:
    """position = 1 - storm (flat on storm days). Net of cost on each |Δposition|."""
    pos = 1.0 - storm
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    return pos * fwd_log - turn * (cost_bps / 1e4)


def circshift_null(storm: np.ndarray, fwd_log: np.ndarray, n: int) -> tuple[np.ndarray, float]:
    N = len(storm)
    obs = sharpe(overlay_strat(storm, fwd_log, RT_COST_BPS))
    out = np.empty(n)
    lo, hi = TRAIL + 2, N - (TRAIL + 2)
    for i in range(n):
        k = int(RNG.integers(lo, hi))
        out[i] = sharpe(overlay_strat(np.roll(storm, k), fwd_log, RT_COST_BPS))
    return out, obs


def main():
    print("[1/3] loading REAL prices + REAL GFZ Kp …", flush=True)
    panel = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    ew = ew_logret(panel)
    kp_raw = ES.load_kp_index(days=4200)
    kp_raw = pd.Series(np.asarray(kp_raw, float), index=pd.DatetimeIndex(kp_raw.index)).sort_index().shift(1)  # PIT 1d lag
    kp = kp_raw.reindex(ew.index, method="ffill")
    print(f"      EW index n={len(ew)}  {ew.index.min().date()}..{ew.index.max().date()}  "
          f"Kp coverage={kp.notna().mean():.2f}", flush=True)

    storm = storm_label(kp, PCTL, TRAIL)
    # forward log-return bar_t -> bar_{t+1}, aligned to decision bar t
    fwd = ew.shift(-1)
    df = pd.concat([storm.rename("storm"), fwd.rename("fwd")], axis=1).dropna()
    s = df["storm"].to_numpy(float); r = df["fwd"].to_numpy(float)
    print(f"      storm days = {int((s>0.5).sum())} / {len(s)} ({(s>0.5).mean()*100:.1f}%)", flush=True)

    print("[2/3] overlay backtest (full + OOS) + always-long buy&hold benchmark …", flush=True)
    strat_full = overlay_strat(s, r, RT_COST_BPS)
    bh_full = r.copy()                                   # always-long EW (no cost, the passive benchmark)
    n = len(r); cut = int(n * (1 - OOS_FRAC))
    rows = []
    for name, sl in [("full", slice(0, n)), ("train", slice(0, cut)), ("oos", slice(cut, n))]:
        st = overlay_strat(s[sl], r[sl], RT_COST_BPS)
        bh = r[sl]
        rows.append(dict(window=name, n=int(sl.stop - sl.start if sl.start else sl.stop),
                         sharpe_overlay=round(sharpe(st), 3), sharpe_bh=round(sharpe(bh), 3),
                         ann_overlay_pct=round(ann_ret(st) * 100, 2), ann_bh_pct=round(ann_ret(bh) * 100, 2),
                         edge_pp=round((ann_ret(st) - ann_ret(bh)) * 100, 2)))
    rep = pd.DataFrame(rows)
    pd.set_option("display.width", 200, "display.max_columns", 30)
    print(rep.to_string(index=False))

    print("\n[3/3] proper circular-shift null (full + OOS) + economic verdict …", flush=True)
    null_full, obs_full = circshift_null(s, r, N_NULL)
    p_full = float((np.abs(null_full) >= abs(obs_full)).mean())
    # OOS-only null
    null_oos, obs_oos = circshift_null(s[cut:], r[cut:], N_NULL)
    p_oos = float((np.abs(null_oos) >= abs(obs_oos)).mean())

    print(f"  FULL : overlay Sharpe={obs_full:.3f}  null_mean={null_full.mean():.3f} sd={null_full.std():.3f}  "
          f"p_null(2s)={p_full:.4f}")
    print(f"  OOS  : overlay Sharpe={obs_oos:.3f}  null_mean={null_oos.mean():.3f} sd={null_oos.std():.3f}  "
          f"p_null(2s)={p_oos:.4f}")

    # bootstrap the OOS edge (overlay ann − bh ann) CI to see if it's distinguishable from zero
    st_oos = overlay_strat(s[cut:], r[cut:], RT_COST_BPS); bh_oos = r[cut:]
    diff = st_oos - bh_oos
    bs = np.array([ann_ret(diff[RNG.integers(0, len(diff), len(diff))]) for _ in range(2000)]) * 100
    ci = (np.percentile(bs, 2.5), np.percentile(bs, 97.5))
    edge_oos = (ann_ret(st_oos) - ann_ret(bh_oos)) * 100

    oos_row = rep[rep.window == "oos"].iloc[0]
    beats_bh_oos = oos_row.edge_pp > 0
    beats_null_oos = p_oos < 0.05
    ci_excl_zero = ci[0] > 0
    verdict = "CANDIDATE" if (beats_bh_oos and beats_null_oos and ci_excl_zero) else "NO_EDGE"
    print(f"\n--- VERDICT ---")
    print(f"  OOS edge vs always-long B&H = {edge_oos:.2f}pp/yr  bootstrap 95% CI=[{ci[0]:.2f},{ci[1]:.2f}]pp")
    print(f"  beats_bh_oos={beats_bh_oos}  beats_null_oos(p<.05)={beats_null_oos}  CI_excludes_zero={ci_excl_zero}")
    print(f"  -> {verdict}")

    out_csv = "scripts/research/astro_strategy_lab/geomag_riskoff_overlay_results.csv"
    rep.to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}\nDONE")


if __name__ == "__main__":
    main()
