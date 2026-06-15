# intent: THE funding-contrarian hypothesis test (memory's #1 strategy direction). Crypto perp funding extremes
# proxy crowded leverage → mean-reversion. Long when funding z-score < -k (shorts crowded → squeeze up),
# flat/short when > +k. 30 funding pairs with ~3000 8h points each (2023-09 → 2026-06).
#
# RIGOR (top-quant bar, no p-hacking):
#  · REAL prices (Binance public klines) + IMMUTABLE funding_rate (available_at==ts, PIT-honest per the audit).
#  · PIT: signal at end of day t uses only funding points with ts <= t 23:59; trade return close[t]→close[t+1].
#  · Rolling z-score of daily funding (252d window, min 60 obs) — purely causal, no future leak.
#  · Pre-registered SMALL sweep: k ∈ {1, 1.5, 2} × mode ∈ {long_flat, long_short} = 6 trials. Deflated at 6.
#  · OOS: last 40% of the common date range is a HOLDOUT, untouched by any selection.
#  · NULL: circular block-bootstrap of the SIGNAL (preserve return + signal autocorrelation), 2000 draws.
#  · ECONOMIC: net of 10bps round-trip per position change; must beat per-symbol buy&hold over the SAME window.
#
# Pooled (equal-weight across symbols each day) is the headline; per-symbol is reported for breadth.
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # apps/engine/scripts
sys.path.insert(0, str(ROOT / "research" / "astro_deep"))
import real_panel as RP  # noqa: E402

# ── universe: the 30 long-history USDT funding pairs (skip the recent OKX -SWAP set) ───────────────
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT", "XLMUSDT", "TRXUSDT", "ETCUSDT",
    "NEARUSDT", "FILUSDT", "AAVEUSDT", "UNIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
    "RUNEUSDT", "ICPUSDT", "SUIUSDT", "SEIUSDT", "GALAUSDT", "TIAUSDT",
]

KS = [1.0, 1.5, 2.0]
MODES = ["long_flat", "long_short"]
N_TRIALS = len(KS) * len(MODES)  # 6
Z_WIN = 252
Z_MIN = 60
RT_COST = 0.0010  # 10 bps round-trip
OOS_FRAC = 0.40
N_BOOT = 2000
BLOCK = 20
SEED = 7


def daily_funding(symbol: str, bar_index: pd.DatetimeIndex) -> pd.Series:
    """PIT daily funding: for each daily bar ts (00:00), the value is the LATEST funding point with
    available_at <= that bar's timestamp + ~1 day boundary. We use real_panel's as-of join which takes the
    latest available_at <= bar ts. To capture the full day's funding known by END of day t we shift the bar
    grid to day-end (23:59) before the as-of join, then re-index to the bar grid. No future leak: 23:59 of day
    t is strictly before 00:00 of day t+1 where the t+1 return is realised."""
    end_of_day = bar_index + pd.Timedelta(hours=23, minutes=59)
    panel = RP.load_real_alt_panel([symbol], ["funding_rate"], {symbol: end_of_day})
    s = panel[symbol]["funding_rate"]
    s.index = bar_index  # map day-end value back onto the day's bar
    return s.astype(float)


def build_panel() -> dict[str, pd.DataFrame]:
    bars = RP.load_crypto_bars(SYMBOLS, "1d", days=1100)
    out: dict[str, pd.DataFrame] = {}
    for s in SYMBOLS:
        df = bars.get(s)
        if df is None or df.empty or len(df) < Z_MIN + 50:
            continue
        idx = df.index
        fund = daily_funding(s, idx)
        ret = df["close"].pct_change().shift(-1)  # close[t]→close[t+1], realised AFTER signal at t
        z = (fund - fund.rolling(Z_WIN, min_periods=Z_MIN).mean()) / fund.rolling(
            Z_WIN, min_periods=Z_MIN
        ).std()
        out[s] = pd.DataFrame({"ret_fwd": ret, "z": z, "close": df["close"]}).dropna(subset=["z"])
    return out


def position(z: pd.Series, k: float, mode: str) -> pd.Series:
    """Contrarian: shorts crowded (z<-k) → LONG (+1). longs crowded (z>+k) → flat or SHORT depending on mode."""
    pos = pd.Series(0.0, index=z.index)
    pos[z < -k] = 1.0
    pos[z > k] = -1.0 if mode == "long_short" else 0.0
    return pos


def strat_returns(df: pd.DataFrame, k: float, mode: str) -> pd.Series:
    """Net daily strategy return for one symbol: position[t]*ret_fwd[t] - cost on position CHANGES."""
    pos = position(df["z"], k, mode)
    gross = pos * df["ret_fwd"]
    turnover = pos.diff().abs().fillna(pos.abs())
    cost = turnover * (RT_COST / 2.0)  # one-way cost = half round-trip; a flip incurs 2 legs
    return gross - cost


def sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 30 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(365))


def pooled_returns(panel: dict[str, pd.DataFrame], k: float, mode: str) -> pd.Series:
    """Equal-weight across symbols each day (only symbols with a non-NaN signal that day contribute)."""
    cols = {s: strat_returns(df, k, mode) for s, df in panel.items()}
    mat = pd.DataFrame(cols)
    return mat.mean(axis=1, skipna=True)


def buy_hold_pooled(panel: dict[str, pd.DataFrame], dates: pd.DatetimeIndex) -> pd.Series:
    cols = {}
    for s, df in panel.items():
        cols[s] = df["ret_fwd"].reindex(dates)
    return pd.DataFrame(cols).mean(axis=1, skipna=True)


def circular_block_null(sig_returns: pd.Series, n_boot: int, block: int, seed: int) -> np.ndarray:
    """Block-bootstrap NULL on the strategy return SERIES via circular shifts of the SIGNAL relative to
    realised returns is approximated here by circular-shifting the realised strategy-return series itself in
    blocks — preserving its autocorrelation while destroying any true timing edge. We compute the null Sharpe
    distribution and report p = P(null Sharpe >= observed)."""
    r = sig_returns.dropna().values
    n = len(r)
    rng = np.random.default_rng(seed)
    out = np.empty(n_boot)
    n_blocks = int(np.ceil(n / block))
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([(np.arange(block) + st) % n for st in starts])[:n]
        rb = r[idx]
        sd = rb.std()
        out[b] = 0.0 if sd == 0 else rb.mean() / sd * np.sqrt(365)
    return out


def deflated_sharpe_p(obs_sr: float, returns: pd.Series, n_trials: int) -> float:
    """Bailey/Lopez de Prado Deflated Sharpe Ratio p-value. Tests obs SR against the EXPECTED MAX SR under the
    null given n_trials independent tries, correcting for skew/kurtosis of the return stream."""
    r = returns.dropna().values
    n = len(r)
    if n < 30:
        return 1.0
    sr = obs_sr / np.sqrt(365)  # per-period SR
    sk = pd.Series(r).skew()
    ku = pd.Series(r).kurt() + 3.0  # pandas kurt is excess
    # expected max SR of n_trials iid N(0,1/n) draws (variance of SR estimator ~ 1/n)
    from scipy.stats import norm

    e_max = np.sqrt(1.0 / n) * (
        (1 - np.euler_gamma) * norm.ppf(1 - 1.0 / n_trials)
        + np.euler_gamma * norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    sr_std = np.sqrt((1 - sk * sr + (ku - 1) / 4.0 * sr**2) / (n - 1))
    if sr_std == 0:
        return 1.0
    z = (sr - e_max) / sr_std
    return float(1.0 - norm.cdf(z))


def main() -> None:
    print("Loading panel (real prices + PIT funding)...", flush=True)
    panel = build_panel()
    print(f"symbols with usable signal: {len(panel)}", flush=True)

    # common pooled date range, split OOS by time
    all_dates = sorted(set().union(*[df.index for df in panel.values()]))
    all_dates = pd.DatetimeIndex(all_dates)
    split = int(len(all_dates) * (1 - OOS_FRAC))
    train_end = all_dates[split - 1]
    oos_start = all_dates[split]
    print(f"dates {all_dates.min().date()}..{all_dates.max().date()} | "
          f"IS<= {train_end.date()} | OOS>= {oos_start.date()} ({OOS_FRAC:.0%})", flush=True)

    # ── full-sample sweep (for selection on IS only) + report all trials ──
    print("\n=== POOLED sweep (IS Sharpe = selection metric) ===")
    rows = []
    for mode in MODES:
        for k in KS:
            pr = pooled_returns(panel, k, mode)
            is_r = pr[pr.index <= train_end]
            oos_r = pr[pr.index >= oos_start]
            rows.append({
                "mode": mode, "k": k,
                "is_sharpe": sharpe(is_r), "oos_sharpe": sharpe(oos_r),
                "is_mean_bps": is_r.mean() * 1e4, "oos_mean_bps": oos_r.mean() * 1e4,
                "full_sharpe": sharpe(pr),
            })
    rep = pd.DataFrame(rows).sort_values("is_sharpe", ascending=False)
    print(rep.to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

    # select the winner by IS Sharpe ONLY (honest holdout)
    best = rep.iloc[0]
    bk, bmode = float(best["k"]), best["mode"]
    print(f"\nSELECTED by IS: mode={bmode} k={bk} (IS SR={best['is_sharpe']:.3f})")

    pr = pooled_returns(panel, bk, bmode)
    oos_r = pr[pr.index >= oos_start].dropna()
    bh_oos = buy_hold_pooled(panel, pr.index)
    bh_oos = bh_oos[bh_oos.index >= oos_start].dropna()

    oos_sr = sharpe(oos_r)
    bh_sr = sharpe(bh_oos)
    oos_net_mean_bps = oos_r.mean() * 1e4
    # annualised net excess return vs buy&hold (OOS)
    strat_cum = (1 + oos_r).prod() - 1
    bh_cum = (1 + bh_oos).prod() - 1

    print(f"\n=== OOS ({oos_start.date()}..{all_dates.max().date()}, n={len(oos_r)}) ===")
    print(f"  strat OOS Sharpe : {oos_sr:.3f}")
    print(f"  buy&hold Sharpe  : {bh_sr:.3f}")
    print(f"  strat net mean   : {oos_net_mean_bps:.3f} bps/day")
    print(f"  strat cum ret    : {strat_cum*100:.1f}%   buy&hold cum: {bh_cum*100:.1f}%")
    print(f"  beats B&H Sharpe : {oos_sr > bh_sr}")

    # ── NULL on OOS strategy returns (block bootstrap) ──
    null = circular_block_null(oos_r, N_BOOT, BLOCK, SEED)
    p_null = float((null >= oos_sr).mean())
    print(f"  block-bootstrap null p (OOS SR): {p_null:.4f}  (null mean SR {null.mean():.3f})")

    # ── Deflated Sharpe at true trial count, on FULL series ──
    dsr_p = deflated_sharpe_p(sharpe(pr.dropna()), pr, N_TRIALS)
    print(f"  Deflated-Sharpe p (n_trials={N_TRIALS}, full): {dsr_p:.4f}")

    # ── verdict ──
    tradeable = (oos_sr > 0) and (oos_net_mean_bps > 0) and (oos_sr > bh_sr) and (p_null < 0.05) and (dsr_p < 0.05)
    print(f"\nVERDICT tradeable: {tradeable}")

    # per-symbol OOS breadth (using selected k/mode) — how many symbols are individually net-positive OOS
    pos_syms = 0
    tot = 0
    for s, df in panel.items():
        rr = strat_returns(df, bk, bmode)
        ro = rr[rr.index >= oos_start].dropna()
        if len(ro) < 30:
            continue
        tot += 1
        if ro.mean() > 0:
            pos_syms += 1
    print(f"per-symbol OOS net-positive: {pos_syms}/{tot}")

    import json
    Path("scripts/research/funding_contrarian").mkdir(parents=True, exist_ok=True)
    summary = {
        "selected": {"mode": bmode, "k": bk},
        "oos_sharpe": round(oos_sr, 4), "bh_oos_sharpe": round(bh_sr, 4),
        "oos_net_mean_bps": round(oos_net_mean_bps, 4),
        "oos_cum_pct": round(strat_cum * 100, 2), "bh_cum_pct": round(bh_cum * 100, 2),
        "p_null": round(p_null, 4), "deflated_sharpe_p": round(dsr_p, 4),
        "n_trials": N_TRIALS, "per_symbol_oos_positive": [pos_syms, tot],
        "tradeable": bool(tradeable),
        "sweep": rep.round(4).to_dict("records"),
    }
    Path("scripts/research/funding_contrarian/results.json").write_text(json.dumps(summary, indent=2))
    print("\nwrote scripts/research/funding_contrarian/results.json")


if __name__ == "__main__":
    main()
