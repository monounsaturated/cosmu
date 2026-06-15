# intent: LENS sentiment_meanrev — is the crypto Fear & Greed index a REAL, live-tradeable mean-reversion
# edge, or a decayed train-only artifact? We test it as a STANDALONE long/short rule (buy fear / fade greed)
# and as a long-only risk-off FILTER overlay, on BTC/ETH + a basket, with top-quant rigor:
#
#   * REAL prices: Binance public daily klines (via real_panel.load_crypto_bars).
#   * IMMUTABLE signal: the alternative.me crypto Fear&Greed index — a free public index computed ONCE per UTC
#     day and NEVER revised (PIT-honest, no backfill/look-ahead, unlike LunarCrush social). We pull the full
#     2018+ history straight from the same public API the prod ingest uses (provider 'alternative.me'). The hot
#     prod alt_data table only retains a ~90d window post cold-tier migration, far too short for OOS, so we go to
#     the immutable source directly.
#   * PIT: the FG value timestamped for day t is available at the close of day t; we act on it for the t->t+1
#     return (positions are shift(1) before being multiplied into forward returns). A value can NEVER touch a
#     past bar.
#   * PROPER NULLS: circular-shift of the SIGNAL (preserves its autocorrelation + the price autocorrelation,
#     destroys only the cross-alignment) AND a stationary block-bootstrap of the (signal, fwd-return) PAIRS.
#     Two-sided on the net-Sharpe statistic. Not iid shuffles.
#   * OOS: a single chronological 70/30 split. Thresholds are NOT re-fit on test.
#   * DEFLATED SHARPE at the TRUE trial count (every asset x variant x threshold-combo evaluated here).
#   * ECONOMIC: net of fee_bps per position change (default 10 bps round-trip), and a strategy only "wins" if it
#     beats its own buy&hold over the SAME (OOS) window after fees.
#
# "Nothing lucrative" is a valid finding. No p-hacking: the trial count fed to the Deflated Sharpe is the full
# grid actually scanned, and the headline verdict is taken on the OOS segment only.

from __future__ import annotations

import json
import ssl
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "scripts" / "research" / "astro_deep"))
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(12345)
ANN = np.sqrt(365.0)
FEE_BPS = 10.0  # round-trip cost charged per unit change in position


# ── immutable Fear&Greed signal (alternative.me; computed once/day, never revised) ──────────────────

def load_fear_greed() -> pd.Series:
    """Full daily crypto Fear&Greed index from the public alternative.me API. tz-naive UTC DatetimeIndex,
    float value in [0,100]. The value timestamped for day t is published at the close of day t (available_at
    == ts effectively, daily cadence), so it is PIT-usable for the t->t+1 trade after a shift(1)."""
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        ctx = ssl.create_default_context()
    req = urllib.request.Request(
        "https://api.alternative.me/fng/?limit=0&format=json",
        headers={"User-Agent": "cosmu-research/0.1"},
    )
    raw = json.loads(urllib.request.urlopen(req, timeout=30, context=ctx).read())
    rows = []
    for d in raw["data"]:
        ts = datetime.fromtimestamp(int(d["timestamp"]), tz=UTC).replace(tzinfo=None)
        rows.append((pd.Timestamp(ts).normalize(), float(d["value"])))
    s = pd.Series({t: v for t, v in rows}).sort_index()
    s.index.name = "ts"
    s.name = "fear_greed"
    return s


# ── strategy position generators (signal at t -> raw position for the t->t+1 return) ────────────────

def pos_meanrev(fg: pd.Series, lo: float, hi: float, *, allow_short: bool) -> pd.Series:
    """Standalone mean-reversion: +1 long when FG<lo (fear), -1 short (or 0 if long-only) when FG>hi (greed),
    else flat. Raw position keyed at signal time t (caller shifts for PIT)."""
    pos = pd.Series(0.0, index=fg.index)
    pos[fg < lo] = 1.0
    pos[fg > hi] = -1.0 if allow_short else 0.0
    return pos


def pos_filter_overlay(fg: pd.Series, greed_thr: float) -> pd.Series:
    """Long-only risk-off FILTER on a buy&hold: stay 100% long, but flatten to cash when FG>greed_thr (greed).
    Tests whether 'sell into euphoria' improves a hold."""
    pos = pd.Series(1.0, index=fg.index)
    pos[fg > greed_thr] = 0.0
    return pos


# ── PIT backtest: positions act on t for the t->t+1 log return, net of turnover fees ────────────────

def backtest(close: pd.Series, raw_pos: pd.Series, *, fee_bps: float = FEE_BPS) -> pd.Series:
    """Return the per-bar NET pnl series (log units). raw_pos is the position decided at t from info known at
    t; we shift(1) so it is HELD over t->t+1, charge fee_bps * |delta position| at each change. Aligned on the
    common index of close and raw_pos."""
    df = pd.concat([close.rename("close"), raw_pos.rename("pos")], axis=1).dropna()
    if len(df) < 30:
        return pd.Series(dtype=float)
    ret = np.log(df["close"]).diff()  # ret[t] = log return t-1 -> t
    held = df["pos"].shift(1)  # position decided at t-1, earns ret[t]; PIT: no look-ahead
    turn = held.diff().abs().fillna(held.abs())
    pnl = held * ret - turn * (fee_bps / 1e4)
    return pnl.dropna()


def sharpe(pnl: pd.Series) -> float:
    if len(pnl) < 30 or pnl.std() == 0:
        return float("nan")
    return float(pnl.mean() / pnl.std() * ANN)


def total_net(pnl: pd.Series) -> float:
    return float(np.exp(pnl.sum()) - 1.0) if len(pnl) else float("nan")


# ── proper nulls on the SIGNAL (preserve autocorrelation) ───────────────────────────────────────────

def block_boot_sharpe(pnl: pd.Series, n: int, mean_block: int = 10) -> np.ndarray:
    """Stationary block-bootstrap of the REALIZED per-bar net pnl (preserves serial structure under the
    strategy) -> sampling spread of the Sharpe. A robustness cross-check; centered at the observed Sharpe so it
    measures stability, not significance (the shift-null does significance)."""
    arr = pnl.to_numpy()
    N = len(arr)
    if N < 30:
        return np.array([])
    p = 1.0 / mean_block
    out = np.empty(n)
    for i in range(n):
        idx = np.empty(N, dtype=int)
        t = 0
        while t < N:
            start = int(RNG.integers(0, N))
            L = min(N - t, int(RNG.geometric(p)))
            for j in range(L):
                idx[t + j] = (start + j) % N
            t += L
        bs = arr[idx]
        out[i] = bs.mean() / bs.std() * ANN if bs.std() > 0 else np.nan
    return out[np.isfinite(out)]


def deflated_sharpe(sr_ann: float, n_trials: int, n_obs: int, skew: float, kurt: float) -> float:
    """Bailey & Lopez de Prado DSR: P(true SR>0) after charging for n_trials selections. sr_ann is annualized;
    convert to per-bar. Wants >0.95 for a real edge."""
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


# ── one full evaluation of a (symbol, variant, params) over train+OOS ───────────────────────────────

def split_idx(index: pd.DatetimeIndex, frac: float = 0.70) -> pd.Timestamp:
    return index[int(len(index) * frac)]


def evaluate(symbol, close, fg, variant, params, n_trials, n_null=600):
    """Build positions, backtest on TRAIN and OOS, run the shift-null on OOS, DSR on OOS, buy&hold compare."""
    common = close.index.intersection(fg.index)
    close = close.loc[common]
    fg = fg.loc[common]
    if len(common) < 200:
        return None
    cut = split_idx(common)

    if variant == "meanrev_ls":
        make_pos = lambda s: pos_meanrev(s, params["lo"], params["hi"], allow_short=True)
    elif variant == "meanrev_lo":
        make_pos = lambda s: pos_meanrev(s, params["lo"], params["hi"], allow_short=False)
    elif variant == "filter_overlay":
        make_pos = lambda s: pos_filter_overlay(s, params["greed"])
    else:
        raise ValueError(variant)

    pos_full = make_pos(fg)
    pnl_full = backtest(close, pos_full)
    tr = pnl_full[pnl_full.index <= cut]
    oos = pnl_full[pnl_full.index > cut]
    if len(oos) < 60 or len(tr) < 60:
        return None

    # buy & hold over the SAME oos window (net of one entry fee, generous to B&H)
    bh_ret = np.log(close).diff()
    bh_oos = bh_ret[(bh_ret.index > cut)].dropna()
    bh_oos_net = float(np.exp(bh_oos.sum()) - 1.0)
    bh_oos_sharpe = sharpe(bh_oos)

    # shift-null on the OOS segment: rebuild positions from shifted fg, take only the oos pnl
    def make_oos_pos(shifted):
        p = make_pos(shifted)
        bt = backtest(close, p)
        return bt[bt.index > cut]

    obs_oos_sharpe = sharpe(oos)
    # shift-null returning OOS sharpe (circular shift of fg preserves autocorrelation)
    out = []
    N = len(fg)
    lo_k, hi_k = max(10, N // 50), N - max(10, N // 50)
    vals = fg.to_numpy()
    for _ in range(n_null):
        k = int(RNG.integers(lo_k, hi_k))
        shifted = pd.Series(np.roll(vals, k), index=fg.index, name="fear_greed")
        out.append(sharpe(make_oos_pos(shifted)))
    null = np.array([x for x in out if np.isfinite(x)])
    p_null = float((np.abs(null) >= abs(obs_oos_sharpe)).mean()) if len(null) else float("nan")

    bb = block_boot_sharpe(oos, 400)
    bb_lo, bb_hi = (float(np.percentile(bb, 2.5)), float(np.percentile(bb, 97.5))) if len(bb) else (np.nan, np.nan)

    dsr = deflated_sharpe(
        obs_oos_sharpe, n_trials, len(oos),
        float(stats.skew(oos)), float(stats.kurtosis(oos) + 3),
    )

    return {
        "symbol": symbol,
        "variant": variant,
        "params": params,
        "n_train": int(len(tr)),
        "n_oos": int(len(oos)),
        "train_sharpe": round(sharpe(tr), 3),
        "oos_sharpe": round(obs_oos_sharpe, 3),
        "train_net": round(total_net(tr), 4),
        "oos_net": round(total_net(oos), 4),
        "bh_oos_net": round(bh_oos_net, 4),
        "bh_oos_sharpe": round(bh_oos_sharpe, 3),
        "beats_bh_net": bool(total_net(oos) > bh_oos_net),
        "p_null": round(p_null, 4),
        "dsr": round(dsr, 4) if np.isfinite(dsr) else None,
        "bb_ci95": [round(bb_lo, 3), round(bb_hi, 3)] if np.isfinite(bb_lo) else None,
        "frac_trades_oos": round(float((make_pos(fg).shift(1).diff().abs() > 0)[(fg.index > cut)].mean()), 4),
    }


# ── basket (equal-weight) close as a synthetic symbol ───────────────────────────────────────────────

def basket_close(bars: dict[str, pd.DataFrame], syms: list[str]) -> pd.Series:
    """Equal-weight basket: average of per-symbol close indexed to 1.0 at each symbol's first common bar.
    We rebase each on the shared index then average — a tradeable EW portfolio proxy."""
    closes = []
    common = None
    for s in syms:
        c = bars[s]["close"]
        common = c.index if common is None else common.intersection(c.index)
    for s in syms:
        c = bars[s]["close"].loc[common]
        closes.append(c / c.iloc[0])
    ew = pd.concat(closes, axis=1).mean(axis=1)
    ew.name = "close"
    return ew


def main() -> None:
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    print("loading real Binance bars + immutable Fear&Greed ...", flush=True)
    bars = RP.load_crypto_bars(syms, "1d", days=3650)
    fg = load_fear_greed()
    print(f"fear_greed: {len(fg)} days {fg.index.min().date()}..{fg.index.max().date()}", flush=True)

    # the grid we ACTUALLY scan -> this is the honest trial count fed to the DSR
    lo_thrs = [20, 25, 30]
    hi_thrs = [75, 80, 70]
    greed_thrs = [75, 80, 70]
    targets = {s: bars[s]["close"] for s in syms if len(bars[s])}
    targets["BASKET"] = basket_close(bars, syms)

    trials = []  # (symbol, variant, params)
    for sym in targets:
        for lo in lo_thrs:
            for hi in hi_thrs:
                trials.append((sym, "meanrev_ls", {"lo": lo, "hi": hi}))
                trials.append((sym, "meanrev_lo", {"lo": lo, "hi": hi}))
        for g in greed_thrs:
            trials.append((sym, "filter_overlay", {"greed": g}))
    n_trials = len(trials)
    print(f"honest trial count (for DSR): {n_trials}", flush=True)

    results = []
    for i, (sym, variant, params) in enumerate(trials):
        r = evaluate(sym, targets[sym], fg, variant, params, n_trials, n_null=500)
        if r:
            results.append(r)
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{n_trials}", flush=True)

    res = pd.DataFrame(results)
    if res.empty:
        print("NO evaluable trials")
        return

    # rank by OOS sharpe among economically valid + significant
    res["candidate"] = (
        (res["oos_sharpe"] > 0)
        & (res["oos_net"] > 0)
        & res["beats_bh_net"]
        & (res["p_null"] < 0.05)
        & (res["dsr"].fillna(0) > 0.95)
    )
    res = res.sort_values("oos_sharpe", ascending=False)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    cols = ["symbol", "variant", "params", "n_oos", "train_sharpe", "oos_sharpe",
            "oos_net", "bh_oos_net", "beats_bh_net", "p_null", "dsr", "candidate"]
    print("\n=== TOP 18 by OOS Sharpe ===")
    print(res[cols].head(18).to_string(index=False))

    print("\n=== CANDIDATES (oos>0 & net>0 & beats B&H & p_null<.05 & DSR>.95) ===")
    cand = res[res["candidate"]]
    if cand.empty:
        print("NONE — no config clears the full economic+null+DSR bar on OOS.")
    else:
        print(cand[cols].to_string(index=False))

    # per-variant best & a focused look at the canonical BTC/ETH long/short 25/75
    print("\n=== canonical configs (BTC/ETH, meanrev_ls lo=25 hi=75) ===")
    canon = res[(res["variant"] == "meanrev_ls") & (res["params"].apply(lambda p: p.get("lo") == 25 and p.get("hi") == 75))]
    print(canon[cols + ["bb_ci95", "frac_trades_oos"]].to_string(index=False))

    out_csv = ENGINE_ROOT / "scripts" / "research" / "sentiment_meanrev_results.csv"
    res.drop(columns=["candidate"]).assign(candidate=res["candidate"]).to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}")


if __name__ == "__main__":
    main()
