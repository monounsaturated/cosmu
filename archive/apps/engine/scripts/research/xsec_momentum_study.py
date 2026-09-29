# intent: HONEST cross-sectional momentum study on REAL Binance daily crypto bars (Jegadeesh-Titman / AQR
# "everywhere" style). Rank the liquid crypto universe by trailing {30,60,90}d return each day; trade the spread
# t -> t+1 on info known at t (PIT). Two portfolios:
#   (A) market-neutral: long top tercile / short bottom tercile, dollar-neutral, daily rebalanced;
#   (B) long-only top-decile (spot-friendly, what COSMU can actually trade on Binance spot).
# Costs: net of ~10bps round-trip charged on turnover. Nulls: randomized-rank permutation AND circular block-shift
# of the cross-sectional signal (preserves each asset's autocorrelation). OOS: time split (train<=2022-12-31,
# test after). Deflated Sharpe at the true trial count. Beats buy&hold? "Nothing lucrative" is a valid finding.
#
# NO fabrication: prices are real public Binance klines via real_panel.load_crypto_bars. Survivorship: the universe
# is the set of liquid majors that EXISTED; a delisted symbol (MATIC) naturally drops out of the rank when its bars
# end — we do NOT forward-fill dead assets, and a day's universe is only the assets with a live bar that day.

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "astro_deep"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "astro_strategy_lab"))
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(20260615)

UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "TRXUSDT", "ETCUSDT", "XLMUSDT", "ATOMUSDT",
    "UNIUSDT", "FILUSDT", "NEARUSDT", "AAVEUSDT", "MATICUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
    "INJUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT", "ICPUSDT", "VETUSDT",
]

LOOKBACKS = [30, 60, 90]           # trailing-return formation windows (days)
GAP = 1                            # skip-1-day to avoid 1-day reversal/microstructure bleed
ROUND_TRIP_BPS = 10.0             # 5bps each side -> charged on |Δweight| turnover
TRAIN_END = pd.Timestamp("2022-12-31")
MIN_UNIVERSE = 8                   # need at least this many live assets to form terciles/deciles
N_BOOT = 2000
BLOCK = 21                         # block length for block-bootstrap / circular shift (≈1 trading month)


# ───────────────────────── data ─────────────────────────

def build_close_panel() -> pd.DataFrame:
    bars = RP.load_crypto_bars(UNIVERSE, "1d", days=3650)
    cols = {}
    for s, df in bars.items():
        if len(df) >= 200:
            cols[s] = df["close"].astype(float)
    panel = pd.DataFrame(cols).sort_index()
    # tz-naive daily index already; keep only rows with >=MIN_UNIVERSE live assets
    return panel


# ───────────────────────── portfolio construction ─────────────────────────

def daily_returns(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.pct_change(fill_method=None)


def formation_signal(panel: pd.DataFrame, lookback: int, gap: int) -> pd.DataFrame:
    """Trailing return over [t-gap-lookback, t-gap]. Known at t (uses closes up to t-gap)."""
    shifted = panel.shift(gap)
    return shifted / shifted.shift(lookback) - 1.0


def cross_sectional_weights(signal_row: pd.Series, mode: str) -> pd.Series:
    """Given one day's formation signal across the live universe, return target weights for NEXT day.

    mode='neutral'   -> long top tercile (+), short bottom tercile (-), dollar-neutral, gross=1 each side.
    mode='longdecile'-> long top decile equal-weight, gross=1, long-only (spot-friendly).
    """
    s = signal_row.dropna()
    n = len(s)
    if n < MIN_UNIVERSE:
        return pd.Series(0.0, index=signal_row.index)
    ranks = s.rank(method="first")
    w = pd.Series(0.0, index=signal_row.index)
    if mode == "neutral":
        k = max(1, n // 3)
        top = ranks.nlargest(k).index
        bot = ranks.nsmallest(k).index
        w[top] = 0.5 / k          # +0.5 gross long
        w[bot] = -0.5 / k         # -0.5 gross short  -> dollar-neutral, total gross=1
    elif mode == "longdecile":
        k = max(1, n // 10)
        top = ranks.nlargest(k).index
        w[top] = 1.0 / k          # fully invested long-only
    return w


def weights_from_signal_matrix(sig: np.ndarray, mode: str) -> np.ndarray:
    """VECTORIZED weight matrix from a (T x N) signal array. NaN = asset not live that day.

    Identical rule to cross_sectional_weights but computed row-wise with numpy so nulls run fast.
    Ties broken by original column order (argsort is stable -> matches rank(method='first')).
    """
    T, N = sig.shape
    W = np.zeros((T, N), dtype=float)
    live_mask = ~np.isnan(sig)
    n_live = live_mask.sum(axis=1)
    # rank within each row over live assets only: replace NaN with -inf so they sort first, then
    # compute the dense position among live assets.
    filled = np.where(live_mask, sig, -np.inf)
    order = np.argsort(filled, axis=1, kind="stable")          # ascending; NaNs (-inf) at the front
    rank_pos = np.empty_like(order)
    rows = np.arange(T)[:, None]
    rank_pos[rows, order] = np.arange(N)[None, :]               # 0..N-1 position in ascending order
    for t in range(T):
        n = int(n_live[t])
        if n < MIN_UNIVERSE:
            continue
        live = live_mask[t]
        # position among LIVE assets: live ranks occupy the top-n positions (N-n .. N-1)
        pos = rank_pos[t] - (N - n)                              # 0..n-1 for live, negative for dead
        if mode == "neutral":
            k = max(1, n // 3)
            top = live & (pos >= n - k)
            bot = live & (pos < k)
            W[t, top] = 0.5 / k
            W[t, bot] = -0.5 / k
        elif mode == "longdecile":
            k = max(1, n // 10)
            top = live & (pos >= n - k)
            W[t, top] = 1.0 / k
    return W


def backtest_fast(panel: pd.DataFrame, rets_arr: np.ndarray, W: np.ndarray,
                  round_trip_bps: float = ROUND_TRIP_BPS) -> pd.Series:
    """PIT backtest from a precomputed (T x N) weight matrix. rets_arr aligned to panel columns/index."""
    W_held = np.vstack([np.zeros((1, W.shape[1])), W[:-1]])
    gross = np.nansum(W_held * rets_arr, axis=1)
    dW = np.vstack([np.zeros((1, W.shape[1])), np.abs(np.diff(W, axis=0))]).sum(axis=1)
    cost = np.concatenate([[0.0], dW[:-1]]) * (round_trip_bps / 1e4)
    net = gross - cost
    return pd.Series(net, index=panel.index).dropna()


def backtest(panel: pd.DataFrame, rets: pd.DataFrame, signal: pd.DataFrame,
             mode: str, round_trip_bps: float = ROUND_TRIP_BPS,
             weights_override: pd.DataFrame | None = None) -> pd.Series:
    """PIT backtest: weights formed from signal at day t are HELD over day t->t+1 (applied to rets at t+1).

    Returns a daily net-return series. Turnover cost = round_trip_bps * 0.5(=per-side already baked) ... we charge
    round_trip_bps on the SUM of |Δweight| across the rebalance (Δweight of 1 unit of gross = full round trip).
    """
    idx = panel.index
    dates = idx[idx.notnull()]
    # precompute weight matrix (target weights decided at each formation day)
    if weights_override is not None:
        W = weights_override.reindex(index=dates, columns=panel.columns).fillna(0.0)
    else:
        W = pd.DataFrame(0.0, index=dates, columns=panel.columns)
        for t in dates:
            row = signal.loc[t] if t in signal.index else pd.Series(dtype=float)
            if len(row):
                W.loc[t] = cross_sectional_weights(row, mode).reindex(panel.columns).fillna(0.0)
    # weights decided at t apply to next-day return -> shift forward by 1
    W_held = W.shift(1).fillna(0.0)
    gross = (W_held * rets.reindex(columns=panel.columns)).sum(axis=1)
    # turnover: |W_t - W_{t-1}| summed; cost charged on the day the new weights take effect
    turnover = (W - W.shift(1).fillna(0.0)).abs().sum(axis=1)
    cost = turnover.shift(1).fillna(0.0) * (round_trip_bps / 1e4)
    net = gross - cost
    return net.dropna()


# ───────────────────────── stats ─────────────────────────

def ann_sharpe(daily: pd.Series) -> float:
    d = daily.dropna()
    if len(d) < 30 or d.std(ddof=1) == 0:
        return 0.0
    return float(d.mean() / d.std(ddof=1) * np.sqrt(365))


def ann_return(daily: pd.Series) -> float:
    d = daily.dropna()
    if not len(d):
        return 0.0
    return float((1 + d).prod() ** (365 / len(d)) - 1)


def max_drawdown(daily: pd.Series) -> float:
    eq = (1 + daily.dropna()).cumprod()
    return float((eq / eq.cummax() - 1).min())


def deflated_sharpe(sr_ann: float, n_obs: int, n_trials: int, skew: float, kurt: float) -> float:
    """Bailey & Lopez de Prado Deflated Sharpe Ratio: P(true SR>0) after deflating for n_trials of selection.

    Works in DAILY (per-observation) Sharpe units throughout. The benchmark SR0 is the expected maximum of
    n_trials draws of a sample Sharpe under the null (each ~Normal(0, 1/sqrt(n_obs))). The candidate's SR is
    compared to that benchmark with the non-normal (skew/kurtosis) standard error of the Sharpe estimator.
    """
    from math import erf, log, sqrt
    if n_obs < 30:
        return float("nan")
    sr = sr_ann / sqrt(365.0)                      # daily Sharpe
    se_null = 1.0 / sqrt(n_obs)                     # std of a sample Sharpe under SR=0
    if n_trials > 1:
        emc = 0.5772156649
        z1 = sqrt(2 * log(n_trials))
        e_max_z = z1 - (emc + log(log(n_trials))) / (2 * z1)   # E[max] of n_trials std-normals (in z units)
        sr0 = se_null * e_max_z                    # benchmark daily Sharpe to beat
    else:
        sr0 = 0.0
    se = sqrt((1 - skew * sr + (kurt - 1) / 4.0 * sr**2) / (n_obs - 1))
    if se <= 0:
        return float("nan")
    z = (sr - sr0) / se
    return float(0.5 * (1 + erf(z / sqrt(2))))


# ───────────────────────── nulls ─────────────────────────

def perm_rank_null(panel: pd.DataFrame, rets_arr: np.ndarray, sig_arr: np.ndarray, mode: str,
                   n: int = N_BOOT) -> np.ndarray:
    """Randomized-rank null: each day, shuffle the cross-sectional signal across the LIVE assets (destroys the
    momentum->return mapping, preserves #long/#short and the realised return cross-section). Vectorized."""
    T, N = sig_arr.shape
    live = ~np.isnan(sig_arr)
    out = np.empty(n)
    for b in range(n):
        perm = sig_arr.copy()
        for t in range(T):
            idx = np.where(live[t])[0]
            if len(idx) >= MIN_UNIVERSE:
                perm[t, idx] = sig_arr[t, RNG.permutation(idx)]
        W = weights_from_signal_matrix(perm, mode)
        out[b] = ann_sharpe(backtest_fast(panel, rets_arr, W))
    return out


def circular_shift_null(panel: pd.DataFrame, rets_arr: np.ndarray, sig_arr: np.ndarray, mode: str,
                        n: int = N_BOOT) -> np.ndarray:
    """Circular block-shift null: roll each asset's signal column by a random offset (preserves each asset's
    OWN autocorrelation but breaks alignment with realised returns). The strongest null for a near-trending
    signal. Vectorized."""
    T, N = sig_arr.shape
    out = np.empty(n)
    lo = BLOCK if T > 2 * BLOCK else 1
    hi = (T - BLOCK) if T > 2 * BLOCK else max(2, T)
    for b in range(n):
        offs = RNG.integers(lo, hi, size=N)
        shifted = np.empty_like(sig_arr)
        for c in range(N):
            shifted[:, c] = np.roll(sig_arr[:, c], int(offs[c]))
        W = weights_from_signal_matrix(shifted, mode)
        out[b] = ann_sharpe(backtest_fast(panel, rets_arr, W))
    return out


# ───────────────────────── main ─────────────────────────

def run() -> None:
    panel = build_close_panel()
    live_count = panel.notna().sum(axis=1)
    panel = panel[live_count >= MIN_UNIVERSE]
    rets = daily_returns(panel)
    print(f"panel: {panel.shape[1]} assets, {len(panel)} days, "
          f"{panel.index.min().date()}..{panel.index.max().date()}, "
          f"median live/day={int(live_count[live_count>=MIN_UNIVERSE].median())}")

    # buy & hold benchmark = equal-weight live universe, daily rebalanced, net of fees on entry drift only
    bh = (rets.mean(axis=1)).dropna()
    print(f"\nEQUAL-WEIGHT BUY&HOLD: ann_ret={ann_return(bh):+.1%}  sharpe={ann_sharpe(bh):.2f}  "
          f"maxDD={max_drawdown(bh):.1%}")
    btc = rets["BTCUSDT"].dropna()
    print(f"BTC BUY&HOLD:          ann_ret={ann_return(btc):+.1%}  sharpe={ann_sharpe(btc):.2f}  "
          f"maxDD={max_drawdown(btc):.1%}")

    n_trials = len(LOOKBACKS) * 2  # 3 lookbacks x 2 modes = the honest trial count for deflation
    print(f"\n=== STRATEGIES (true trial count for deflation = {n_trials}) ===")
    print(f"{'mode':<11}{'lb':>4}{'sharpe':>8}{'annret':>9}{'maxDD':>8}{'net+':>6}"
          f"{'turnPD':>8}{'vsBH':>7}")

    results = []
    for mode in ("neutral", "longdecile"):
        for lb in LOOKBACKS:
            sig = formation_signal(panel, lb, GAP)
            net = backtest(panel, rets, sig, mode)
            # turnover/day (informational)
            W = pd.DataFrame(0.0, index=panel.index, columns=panel.columns)
            for t in panel.index:
                row = sig.loc[t] if t in sig.index else None
                if row is not None and len(row.dropna()) >= MIN_UNIVERSE:
                    W.loc[t] = cross_sectional_weights(row, mode).reindex(panel.columns).fillna(0.0)
            turn_pd = float((W - W.shift(1).fillna(0.0)).abs().sum(axis=1).mean())
            sr = ann_sharpe(net)
            ar = ann_return(net)
            beats_bh = ar > ann_return(bh) and sr > ann_sharpe(bh)
            print(f"{mode:<11}{lb:>4}{sr:>8.2f}{ar:>+9.1%}{max_drawdown(net):>8.1%}"
                  f"{str(net.mean()>0):>6}{turn_pd:>8.2f}{str(beats_bh):>7}")
            results.append({"mode": mode, "lb": lb, "net": net, "sig": sig,
                            "sharpe": sr, "annret": ar, "beats_bh": beats_bh})

    # OOS: pick the BEST in-sample (train) config per mode, then evaluate frozen on test
    print("\n=== OOS (train<=2022-12-31, test after) — freeze best-train config per mode ===")
    print(f"{'mode':<11}{'lb*':>5}{'trSR':>7}{'teSR':>7}{'teRet':>9}{'teDD':>8}{'net+':>6}")
    oos_records = []
    for mode in ("neutral", "longdecile"):
        cands = [r for r in results if r["mode"] == mode]
        best, best_tr = None, -1e9
        for r in cands:
            tr = r["net"][r["net"].index <= TRAIN_END]
            s = ann_sharpe(tr)
            if s > best_tr:
                best_tr, best = s, r
        te = best["net"][best["net"].index > TRAIN_END]
        oos_records.append({"mode": mode, "lb": best["lb"], "train_sr": best_tr,
                            "test_sr": ann_sharpe(te), "test_ret": ann_return(te),
                            "test_dd": max_drawdown(te), "test_net_pos": bool(te.mean() > 0),
                            "net_full": best["net"], "test": te, "sig": best["sig"]})
        print(f"{mode:<11}{best['lb']:>5}{best_tr:>7.2f}{ann_sharpe(te):>7.2f}"
              f"{ann_return(te):>+9.1%}{max_drawdown(te):>8.1%}{str(te.mean()>0):>6}")

    # NULLS + deflated sharpe on the OOS-frozen configs (FULL-sample SR vs null, then DSR)
    print("\n=== NULLS (full-sample, on the OOS-frozen config) + DEFLATED SHARPE ===")
    rets_arr = rets.reindex(columns=panel.columns).values
    for rec in oos_records:
        mode, lb = rec["mode"], rec["lb"]
        net = rec["net_full"]
        sr = ann_sharpe(net)
        sig_arr = rec["sig"].reindex(columns=panel.columns).values
        perm = perm_rank_null(panel, rets_arr, sig_arr, mode)
        shift = circular_shift_null(panel, rets_arr, sig_arr, mode)
        p_perm = float((perm >= sr).mean())
        p_shift = float((shift >= sr).mean())
        sk = float(pd.Series(net).skew())
        ku = float(pd.Series(net).kurt()) + 3.0  # pandas kurt is excess
        dsr = deflated_sharpe(sr, len(net), len(LOOKBACKS) * 2, sk, ku)
        print(f"{mode:<11} lb={lb:<3} fullSR={sr:.2f}  "
              f"perm_null:  mean={perm.mean():.2f} p={p_perm:.3f}  |  "
              f"shift_null: mean={shift.mean():.2f} p={p_shift:.3f}  |  DSR_p(SR>0)={dsr:.3f}")
        rec["p_perm"] = p_perm
        rec["p_shift"] = p_shift
        rec["dsr"] = dsr
        rec["full_sr"] = sr

    # decision summary — the HONEST gate adds the two checks the naive version misses:
    #   (1) OOS economic significance: test-period mean-return t-stat (not just full-sample null rejection,
    #       which a rich early period can carry while the live edge is dead);
    #   (2) beta-neutrality + beat-BTC: a long-only book with beta≈1 to crypto is leveraged beta, not alpha,
    #       so it must (a) be near market-neutral OR (b) beat a plain BTC buy&hold on OOS Sharpe.
    print("\n=== VERDICT (honest gate: OOS t-stat + beta/beat-BTC, not just full-sample null) ===")
    bh = (rets.mean(axis=1)).dropna()
    btc = rets["BTCUSDT"].dropna()
    btc_oos_sr = ann_sharpe(btc[btc.index > TRAIN_END])
    for rec in oos_records:
        te = rec["test"]
        teBH = bh[bh.index > TRAIN_END]
        df = pd.concat([te.rename("L"), teBH.rename("BH")], axis=1).dropna()
        beta = float(np.cov(df["L"], df["BH"])[0, 1] / np.var(df["BH"])) if len(df) > 2 else float("nan")
        t_mean = float(te.mean() / te.std() * np.sqrt(len(te))) if te.std() > 0 else 0.0
        net_of_fee_pos = rec["test_net_pos"]
        beats_null = max(rec["p_perm"], rec["p_shift"]) < 0.05         # FULL-sample only
        oos_significant = t_mean > 2.0                                  # OOS premium real, not noise
        is_neutral = abs(beta) < 0.3
        beats_btc = rec["test_sr"] > btc_oos_sr
        not_just_beta = is_neutral or beats_btc
        tradeable = net_of_fee_pos and oos_significant and not_just_beta
        print(f"{rec['mode']:<11} lb={rec['lb']:<3} "
              f"OOS_SR={rec['test_sr']:.2f} t(OOSmean)={t_mean:.2f} beta={beta:+.2f} "
              f"(BTC_OOS_SR={btc_oos_sr:.2f}) net+={net_of_fee_pos} fullnull_p<.05={beats_null} "
              f"OOSsig={oos_significant} not_just_beta={not_just_beta} -> TRADEABLE={tradeable}")


if __name__ == "__main__":
    run()
