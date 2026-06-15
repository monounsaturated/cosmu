# intent: ECONOMIC + ROBUSTNESS validator for any (astro feature x regime cell) candidate that beat the
# circular-shift null. For each candidate we ask the questions that a "lucky" survivor fails:
#   (1) Tradeable? Build a within-cell cross-sectional long/short: each day in the cell, rank assets by the
#       astro feature, long top tercile / short bottom, hold `horizon` days, charge 10bps round-trip on the
#       realized turnover. Report gross & NET annualized Sharpe and mean net return per rebalance.
#   (2) Sign-stable OUT of sample? Split the cell's calendar in half (early vs late). Fit the IC sign on the
#       EARLY half, apply it to the LATE half. A real effect keeps its sign; a lucky one flips/dies.
#   (3) Robust to the era? Report the per-half IC so we can see if it is a single-regime mirage.
# LIVE-HONEST: same deterministic astro + real prices + immutable funding as the study. No look-ahead: the
# L/S uses the astro feature known at the bar and the SUBSEQUENT realized return.
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import regime_conditional_study as S  # noqa: E402


def _ls_net_sharpe(feat_panel: pd.DataFrame, fwd_panel: pd.DataFrame, mask_panel: pd.DataFrame,
                   horizon: int, sign: float, fee_rt: float = S.FEE_RT):
    """Cross-sectional L/S inside the regime. feat/fwd/mask are date x asset wide frames aligned on a common
    grid. Each eligible day: rank in-cell assets by sign*feat, long top third, short bottom third, equal
    weight, hold `horizon` days (we sample every `horizon`-th eligible day to avoid overlap). Net of fees on
    full turnover (open+close = 2x notional per leg per rebalance)."""
    dates = feat_panel.index
    rets = []
    turn = []
    elig_days = [d for d in dates if mask_panel.loc[d].sum() >= 6]
    elig_days = elig_days[::horizon]  # non-overlapping holds
    for d in elig_days:
        m = mask_panel.loc[d]
        f = (sign * feat_panel.loc[d])[m].dropna()
        y = fwd_panel.loc[d][m].reindex(f.index)
        ok = f.notna() & y.notna()
        f, y = f[ok], y[ok]
        if len(f) < 6:
            continue
        k = max(1, len(f) // 3)
        longs = f.nlargest(k).index
        shorts = f.nsmallest(k).index
        r = y[longs].mean() - y[shorts].mean()
        rets.append(float(r))
        turn.append(2.0)  # full open+close turnover each non-overlapping rebalance
    if len(rets) < 20:
        return None
    rets = np.array(rets)
    gross = rets.mean()
    net = gross - fee_rt * 1.0  # ~10bps round-trip applied per rebalance on the spread
    # annualize: holds are `horizon` days, ~252/horizon per yr
    per_yr = 252.0 / horizon
    sd = rets.std(ddof=1)
    gross_sharpe = (gross / sd) * np.sqrt(per_yr) if sd > 0 else np.nan
    net_mean = net
    net_sharpe = (net_mean / sd) * np.sqrt(per_yr) if sd > 0 else np.nan
    return {
        "n_rebal": len(rets), "gross_mean_bps": gross * 1e4, "net_mean_bps": net_mean * 1e4,
        "gross_sharpe": gross_sharpe, "net_sharpe": net_sharpe,
    }


def validate(candidates: list[dict], horizon: int = 1):
    """candidates: list of {'feature','cell','pooled_ic'} dicts."""
    cbars = S.RP.load_crypto_bars(S.CRYPTO, "1d", days=3650)
    ebars = S.RP.load_equity_bars(S.EQUITY)
    bars = {**{s: cbars[s] for s in S.CRYPTO if len(cbars.get(s, [])) > 600},
            **{s: ebars[s] for s in S.EQUITY if len(ebars.get(s, [])) > 600}}
    bidx = {s: bars[s].index for s in bars}
    funding_by_sym = {}
    try:
        fpanel = S.RP.load_real_alt_panel([s for s in bars if s.endswith("USDT")], ["funding_rate"], bidx)
        funding_by_sym = {s: fdf["funding_rate"] for s, fdf in fpanel.items() if "funding_rate" in fdf}
    except Exception:  # noqa: BLE001
        pass
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(b.index) for b in bars.values()])))
    AP = S.astro_panel(all_dates)
    frames = {s: S.build_asset_frame(bars[s]["close"], funding_by_sym.get(s), horizon) for s in bars}

    cell_fn = dict(S.REGIME_CELLS)
    results = []
    for c in candidates:
        feat, cell, pic = c["feature"], c["cell"], c.get("pooled_ic", 0.0)
        sign = float(np.sign(pic)) or 1.0
        # build wide panels on union grid
        feat_w = pd.DataFrame({s: AP[feat].reindex(all_dates) for s in bars})
        fwd_w = pd.DataFrame({s: frames[s]["fwd"].reindex(all_dates) for s in bars})
        mask_w = pd.DataFrame({s: cell_fn[cell](frames[s]).reindex(all_dates).fillna(False) for s in bars})
        # economic L/S
        ls = _ls_net_sharpe(feat_w, fwd_w, mask_w, horizon, sign)
        # out-of-sample sign stability: split cell calendar in half
        elig = all_dates[mask_w.any(axis=1).to_numpy()]
        if len(elig) > 100:
            mid = elig[len(elig) // 2]
            def half_ic(lo, hi):
                ics, ns = [], []
                for s in bars:
                    ix = (all_dates >= lo) & (all_dates < hi)
                    msk = mask_w[s].to_numpy() & ix
                    x = feat_w[s].to_numpy()[msk]; y = fwd_w[s].to_numpy()[msk]
                    ic = S.spearman_ic(x, y)
                    if np.isfinite(ic):
                        ics.append(ic); ns.append(len(x))
                return float(np.average(ics, weights=ns)) if ics else np.nan
            ic_early = half_ic(all_dates.min(), mid)
            ic_late = half_ic(mid, all_dates.max() + pd.Timedelta(days=1))
        else:
            ic_early = ic_late = np.nan
        row = {"feature": feat, "cell": cell, "pooled_ic": pic, "sign": sign,
               "ic_early": ic_early, "ic_late": ic_late,
               "sign_holds_oos": bool(np.isfinite(ic_early) and np.isfinite(ic_late) and np.sign(ic_early) == np.sign(ic_late) == sign)}
        if ls:
            row.update(ls)
        results.append(row)
    return pd.DataFrame(results)
