#!/usr/bin/env python3
"""LIVE-HONEST COMPOSITE — do {funding_z, fear_greed_z, vix_z, 60d-momentum} COMBINE into an edge none has alone?

LENS "combo_and_geomag" (COSMU lucrative-edge hunt, astro CLOSED).

PRE-REGISTERED (no fitting, no p-hacking — declared BEFORE looking at returns):
  Signals, each z-scored on a TRAILING 252d window (knowable at t, no look-ahead):
    funding_z       : daily-mean Binance perp funding_rate, z(252).  HIGH funding = crowded longs = BEARISH next day → enters with sign -1
    fear_greed_z    : alternative.me Fear&Greed (0-100), z(252).     LOW fear (extreme fear) = contrarian BULLISH → sign -1 (we buy fear) ... see SIGN block
    vix_z           : CBOE VIX level, z(252).                        HIGH vix = risk-off = BEARISH → sign -1
    mom60           : sign of 60d log-return (trend).                POSITIVE trend = BULLISH → sign +1
  COMPOSITE = EQUAL-WEIGHT mean of the four DIRECTIONAL components (each mapped to its pre-declared bullish/bearish
  sign, then averaged). Range ~[-1,+1]. This is the ONLY composite we score (one pre-registered trial per rule family).

  TWO pre-registered rules on the SAME composite (declared up front; counted in the trial budget / deflation):
    R1 long/flat  : position_t = 1 if composite_t > 0 else 0      (spot-only honest; the live venue is Binance SPOT)
    R2 long/short : position_t = sign(composite_t)                (the theoretical version; perp-style, for reference)

  Trade at t→t+1 on the value KNOWN at t (PIT): signals built from available_at<=bar_t, position taken at bar_t close,
  return realised bar_t→bar_{t+1}. Net of RT_COST_BPS per position CHANGE (round-trip).

ECONOMIC GATE (cardinal rule #3): net of ~10bps round-trip cost, must BEAT BUY&HOLD on the SAME window, OOS.

PROPER NULL (cardinal rule #2): block-bootstrap / circular-shift of the position series vs returns (preserves the
  autocorrelation of BOTH; destroys only their alignment). iid shuffle is too lenient for autocorrelated daily series.

OOS: chronological 65/35 split. The composite is built ENTIRELY from trailing windows so there is NOTHING fitted on
  train — train is only "the regime where we first looked"; the 35% holdout is the honest test. Deflated Sharpe at the
  true trial count (rules x universe-portfolio = small, declared) is reported.

DATA: real Binance spot prices (RP), real funding/F&G/VIX from the R2 cold lake (full PIT history, available_at join).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "scripts/research/astro_deep")
sys.path.insert(0, "scripts/research/astro_strategy_lab")
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(20260615)

# Spot-tradeable Binance universe (the live venue). Equal-weight portfolio of these (each gets the composite rule).
CRYPTO = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
          "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT"]

RT_COST_BPS = 10.0          # round-trip cost floor (per position change)
Z_WIN = 252                 # trailing z-score window (1y), knowable at t
MOM_WIN = 60                # trend lookback
OOS_FRAC = 0.35             # chronological holdout fraction
N_NULL = 2000               # circular-shift / block-bootstrap iterations
TRADING_DAYS = 365          # crypto trades every calendar day

# ── R2 cold-lake reader (full PIT alt history with available_at) ────────────────────────────────────


def _r2_con():
    import duckdb

    con = duckdb.connect(":memory:")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(
        "CREATE OR REPLACE SECRET r2 (TYPE r2, KEY_ID ?, SECRET ?, ACCOUNT_ID ?)",
        [os.environ["R2_ACCESS_KEY_ID"], os.environ["R2_SECRET_ACCESS_KEY"], os.environ["R2_ACCOUNT_ID"]],
    )
    return con


def _lake_glob(provider: str, metric: str) -> str:
    b = os.environ["R2_BUCKET"]
    return f"r2://{b}/alt_lake/main/alt_data/provider={provider}/metric={metric}/*.parquet"


def load_lake_metric(con, provider: str, metric: str, symbol: str | None = None) -> pd.DataFrame:
    """(available_at, value) rows for one metric, sorted by available_at — the PIT-join input. If `symbol` is
    given, filter to it; else assume MARKET-wide. Returns tz-naive available_at."""
    g = _lake_glob(provider, metric)
    where = "" if symbol is None else f" WHERE symbol = '{symbol}'"
    df = con.execute(
        f"SELECT available_at, value FROM read_parquet('{g}'){where} ORDER BY available_at"
    ).df()
    df["available_at"] = pd.to_datetime(df["available_at"], utc=True, format="ISO8601").dt.tz_localize(None)
    df["value"] = df["value"].astype(float)
    return df


def asof_join(points: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """PIT as-of: each bar ts gets the LATEST value whose available_at <= ts. merge_asof, backward."""
    if not len(points):
        return pd.Series(index=index, dtype=float)
    left = pd.DataFrame({"ts": index}).sort_values("ts")
    pts = points.rename(columns={"available_at": "ts"}).sort_values("ts")
    merged = pd.merge_asof(left, pts, on="ts", direction="backward")
    return pd.Series(merged["value"].to_numpy(), index=merged["ts"]).reindex(index)


# ── signals ─────────────────────────────────────────────────────────────────────────────────────


def trailing_z(s: pd.Series, win: int) -> pd.Series:
    """z-score on a TRAILING window: (x - rollmean) / rollstd, both shifted-inclusive of t only (no future)."""
    mu = s.rolling(win, min_periods=max(20, win // 4)).mean()
    sd = s.rolling(win, min_periods=max(20, win // 4)).std(ddof=0)
    return (s - mu) / sd.replace(0, np.nan)


def build_composite(close: pd.Series, funding: pd.Series, fng: pd.Series, vix: pd.Series) -> pd.DataFrame:
    """Equal-weight composite of the four pre-declared DIRECTIONAL components. Each is mapped to its
    pre-registered bullish(+)/bearish(-) sign, then averaged. NaN-tolerant: average over the components that exist
    at t (so a missing market-wide macro day doesn't blank the whole composite)."""
    logc = np.log(close)
    # components (each in 'expected forward-return direction' units)
    funding_z = trailing_z(funding, Z_WIN)
    fng_z = trailing_z(fng, Z_WIN)
    vix_z = trailing_z(vix, Z_WIN)
    mom60 = np.sign(logc - logc.shift(MOM_WIN))

    # PRE-REGISTERED SIGNS (declared by mechanism, NOT fit):
    #   high funding  -> crowded longs -> bearish next-day      => component = -funding_z
    #   high F&G      -> greed/euphoria -> mean-revert bearish   => component = -fng_z   (contrarian: fade greed, buy fear)
    #   high vix      -> risk-off       -> bearish               => component = -vix_z
    #   positive 60d trend -> momentum  -> bullish               => component = +mom60
    comp = pd.DataFrame({
        "c_funding": -funding_z,
        "c_fng": -fng_z,
        "c_vix": -vix_z,
        "c_mom": mom60,
    }, index=close.index)
    # clip the z-components to +-3 so one outlier day can't dominate the equal-weight mean
    for col in ("c_funding", "c_fng", "c_vix"):
        comp[col] = comp[col].clip(-3, 3) / 3.0  # scale to ~[-1,1] like the sign component
    # HONEST composite: only defined where ALL FOUR pre-registered components exist (no partial-composite that
    # silently degrades to momentum-only on the long pre-2023 history where F&G/funding/vix are absent).
    comp["composite"] = comp[["c_funding", "c_fng", "c_vix", "c_mom"]].mean(axis=1, skipna=False)
    # baselines for the disconfirmer: does the COMBO beat its parts?
    comp["mom_only"] = comp["c_mom"]                                   # trend alone
    comp["macro_only"] = comp[["c_funding", "c_fng", "c_vix"]].mean(axis=1, skipna=False)  # the 3 live signals, no trend
    return comp


# ── backtest one position series ────────────────────────────────────────────────────────────────


def run_positions(pos: pd.Series, fwd_ret: pd.Series, cost_bps: float) -> dict:
    """Strategy daily returns = pos_t * fwd_ret_t  minus cost on each position CHANGE. fwd_ret is the simple
    bar_t->bar_{t+1} return aligned to t (the decision bar)."""
    df = pd.concat([pos.rename("pos"), fwd_ret.rename("ret")], axis=1).dropna()
    if len(df) < 60:
        return {}
    p = df["pos"].to_numpy(float)
    r = df["ret"].to_numpy(float)
    turn = np.abs(np.diff(np.concatenate([[0.0], p])))     # |Δposition|, incl. initial entry
    cost = turn * (cost_bps / 1e4)
    strat = p * r - cost
    return {"index": df.index, "strat": strat, "ret": r, "pos": p, "turn": turn}


def sharpe(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if len(x) < 30 or x.std(ddof=0) == 0:
        return 0.0
    return float(x.mean() / x.std(ddof=0) * np.sqrt(TRADING_DAYS))


def ann_ret(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if not len(x):
        return 0.0
    return float(np.expm1(np.log1p(x).sum() * TRADING_DAYS / len(x)))


def circshift_null_sharpe(strat_pos: np.ndarray, ret: np.ndarray, n: int) -> tuple[np.ndarray, float]:
    """Circular-shift the POSITION series vs returns; recompute net Sharpe each shift. Preserves the
    autocorrelation of both series, destroys only alignment — the sharp 'positions are unrelated to returns' null."""
    N = len(ret)
    obs = sharpe(strat_pos * ret - np.abs(np.diff(np.concatenate([[0.0], strat_pos]))) * (RT_COST_BPS / 1e4))
    out = np.empty(n)
    lo, hi = MOM_WIN + 2, N - (MOM_WIN + 2)
    for i in range(n):
        k = int(RNG.integers(lo, hi))
        pr = np.roll(strat_pos, k)
        out[i] = sharpe(pr * ret - np.abs(np.diff(np.concatenate([[0.0], pr]))) * (RT_COST_BPS / 1e4))
    return out, obs


def deflated_sharpe(sr: float, n_obs: int, n_trials: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """Bailey & López de Prado DSR: probability the observed Sharpe is > 0 after accounting for the number of
    trials (the expected max of N null Sharpes) and the non-normality of returns. Returns P(SR>0 | selection)."""
    from math import log, sqrt
    from statistics import NormalDist

    nd = NormalDist()
    if n_trials < 1:
        n_trials = 1
    # expected max of n_trials standard normals (Bailey-LdP approximation)
    emc = 0.5772156649
    e_max = (1 - emc) * nd.inv_cdf(1 - 1.0 / n_trials) + emc * nd.inv_cdf(1 - 1.0 / (n_trials * np.e))
    sr0 = e_max / sqrt(n_obs - 1) if n_obs > 1 else 0.0  # benchmark threshold from trials, per-bar units
    sr_bar = sr / sqrt(TRADING_DAYS)                      # back to per-bar Sharpe
    denom = sqrt(max(1e-12, 1 - skew * sr_bar + (kurt - 1) / 4.0 * sr_bar**2))
    z = (sr_bar - sr0) * sqrt(n_obs - 1) / denom
    return float(nd.cdf(z))


# the signal variants tested. The COMBO is the pre-registered headline; mom_only / macro_only are DISCONFIRMERS:
# if the combo's net OOS edge is not materially above mom_only, the live signals add nothing and there is no combo edge.
SIGNAL_COLS = ["composite", "mom_only", "macro_only"]
RULES = [("R1_long_flat", lambda c: (c > 0).astype(float)),
         ("R2_long_short", lambda c: np.sign(np.where(np.isnan(c), np.nan, np.sign(c))))]
# honest trial count for deflation: 3 signal variants x 2 rules = 6 configs we look at.
N_TRIALS = len(SIGNAL_COLS) * len(RULES)


def _portfolio(per_asset: dict, col: str, posfun, common_start, cost_bps=RT_COST_BPS):
    """Equal-weight portfolio of per-asset (position->next-return) strat series on the all-four window.
    Returns (port_strat, port_bh, list_of_(pos,ret) per asset for the null)."""
    strat_frames, bh_frames, raw = [], [], []
    for s, d in per_asset.items():
        sig = d[col]
        pos = pd.Series(posfun(sig.to_numpy()), index=sig.index)
        df = pd.concat([pos.rename("pos"), d["fwd"].rename("ret")], axis=1).dropna()
        if common_start is not None:
            df = df.loc[df.index >= common_start]
        if len(df) < 60:
            continue
        p = df["pos"].to_numpy(float); r = df["ret"].to_numpy(float)
        turn = np.abs(np.diff(np.concatenate([[0.0], p])))
        strat = p * r - turn * (cost_bps / 1e4)
        strat_frames.append(pd.Series(strat, index=df.index).rename(s))
        bh_frames.append(pd.Series(r, index=df.index).rename(s))
        raw.append((s, p, r, df.index))
    if not strat_frames:
        return None, None, []
    port = pd.concat(strat_frames, axis=1).mean(axis=1).dropna()
    bh = pd.concat(bh_frames, axis=1).mean(axis=1).dropna()
    return port, bh, raw


def main():
    print("[1/4] loading REAL Binance spot prices …", flush=True)
    bars = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    bar_idx = {s: bars[s].index for s in CRYPTO if len(bars[s])}

    print("[2/4] loading REAL funding / fear&greed / VIX from R2 cold lake (PIT available_at join) …", flush=True)
    con = _r2_con()
    fng_pts = load_lake_metric(con, "alternative.me", "fear_greed", symbol="MARKET")
    vix_pts = load_lake_metric(con, "fred", "vix_level", symbol="MARKET")
    funding_pts = {s: load_lake_metric(con, "binance", "funding_rate", symbol=s) for s in CRYPTO}
    con.close()
    print(f"      fear_greed rows={len(fng_pts)}  vix rows={len(vix_pts)}  "
          f"funding(BTC) rows={len(funding_pts['BTCUSDT'])}", flush=True)

    print("[3/4] building composite (+ disconfirmer baselines) — ALL-FOUR window only, PIT, no fit …", flush=True)
    per_asset = {}
    for s in CRYPTO:
        if s not in bar_idx:
            continue
        close = bars[s]["close"].astype(float)
        idx = close.index
        fng = asof_join(fng_pts, idx)
        vix = asof_join(vix_pts, idx)
        funding = asof_join(funding_pts[s], idx)
        comp = build_composite(close, funding, fng, vix)
        fwd = close.pct_change().shift(-1)   # bar_t -> bar_{t+1}, aligned to decision bar t (PIT)
        per_asset[s] = dict(composite=comp["composite"], mom_only=comp["mom_only"],
                            macro_only=comp["macro_only"], fwd=fwd, close=close)

    # ALL-FOUR window: the composite is NaN unless every component exists → its first valid date is the honest start.
    starts = [d["composite"].dropna().index.min() for d in per_asset.values() if d["composite"].notna().any()]
    common_start = max(starts) if starts else None
    ends = [d["composite"].dropna().index.max() for d in per_asset.values() if d["composite"].notna().any()]
    common_end = min(ends) if ends else None
    print(f"      ALL-FOUR honest window: {common_start} .. {common_end}", flush=True)

    print("[4/4] OOS split + proper null + economic(vs buy&hold) + deflation\n", flush=True)
    pd.set_option("display.width", 240, "display.max_columns", 40)
    rows = []
    null_lines = []
    for col in SIGNAL_COLS:
        for rule_name, posfun in RULES:
            port, bh, raw = _portfolio(per_asset, col, posfun, common_start)
            if port is None or len(port) < 120:
                continue
            n = len(port)
            cut = int(n * (1 - OOS_FRAC))
            oos = port.iloc[cut:]; bh_oos = bh.iloc[cut:]
            tr = port.iloc[:cut]
            # proper null: per-asset circular shift of positions vs returns, portfolio-averaged
            per_nulls = []
            for s, p, r, ix in raw:
                null, _obs = circshift_null_sharpe(p, r, N_NULL)
                per_nulls.append(null)
            min_n = min(len(x) for x in per_nulls)
            port_null = np.vstack([x[:min_n] for x in per_nulls]).mean(axis=0)
            obs_full = sharpe(port.to_numpy())
            p_null = float((np.abs(port_null) >= abs(obs_full)).mean())
            dsr = deflated_sharpe(obs_full, n_obs=n, n_trials=N_TRIALS,
                                  skew=float(pd.Series(port).skew()),
                                  kurt=float(pd.Series(port).kurt()) + 3.0)
            edge_oos = (ann_ret(oos.to_numpy()) - ann_ret(bh_oos.to_numpy())) * 100
            rows.append(dict(signal=col, rule=rule_name, n=n,
                             sh_tr=round(sharpe(tr.to_numpy()), 3),
                             sh_oos=round(sharpe(oos.to_numpy()), 3),
                             ann_oos=round(ann_ret(oos.to_numpy()) * 100, 2),
                             bh_oos=round(ann_ret(bh_oos.to_numpy()) * 100, 2),
                             edge_oos_pp=round(edge_oos, 2),
                             p_null=round(p_null, 4), dsr=round(dsr, 3)))
            null_lines.append(f"  {col:11s} {rule_name:13s} obs_sharpe={obs_full:.3f} "
                              f"null_mean={port_null.mean():.3f} null_sd={port_null.std():.3f} "
                              f"p_null={p_null:.4f} DSR={dsr:.3f}")
    res = pd.DataFrame(rows)
    print(res.to_string(index=False))
    print("\n--- null + deflation detail ---")
    print("\n".join(null_lines))

    # ── verdict logic (the FIND gate): a candidate must, on the COMPOSITE row, beat its null (p<.05) AND beat
    #    buy&hold OOS net of fees AND beat its mom_only baseline (the combo must ADD edge, not just be momentum). ──
    print("\n--- VERDICT ---")
    if len(res):
        for rule_name, _ in RULES:
            comp_row = res[(res.signal == "composite") & (res.rule == rule_name)]
            mom_row = res[(res.signal == "mom_only") & (res.rule == rule_name)]
            if not len(comp_row) or not len(mom_row):
                continue
            cr = comp_row.iloc[0]; mr = mom_row.iloc[0]
            beats_null = cr.p_null < 0.05
            beats_bh = cr.edge_oos_pp > 0
            adds_over_mom = cr.edge_oos_pp > mr.edge_oos_pp + 5  # combo must add >5pp/yr over pure trend
            verdict = "CANDIDATE" if (beats_null and beats_bh and adds_over_mom and cr.dsr > 0.95) else "NO_EDGE"
            print(f"  {rule_name}: composite edge_oos={cr.edge_oos_pp}pp vs mom_only={mr.edge_oos_pp}pp | "
                  f"p_null={cr.p_null} dsr={cr.dsr} | beats_null={beats_null} beats_bh={beats_bh} "
                  f"adds_over_mom={adds_over_mom} -> {verdict}")

    out_csv = "scripts/research/astro_strategy_lab/combo_composite_results.csv"
    res.to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}")
    print("DONE")


if __name__ == "__main__":
    main()
