# intent: DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the 0.95 in-sample Gate). A simple, textbook RISK-PARITY sleeve:
# inverse-realized-vol weight a {SPY (US equity), AGG (US agg bonds), GLD (gold)} basket, rebalanced MONTHLY. This is
# the canonical "equal risk contribution by 1/vol" heuristic (Qian; the retail "All-Weather-lite"): size each sleeve so
# its dollar position is proportional to 1/its recent volatility, so the high-vol equity leg doesn't dominate portfolio
# risk. The documented edge is RISK-ADJUSTED: a smoother equity curve (higher Sharpe and/or much lower drawdown) than
# either 60/40 or buy-and-hold SPY, by diversifying across assets whose drawdowns rarely coincide (gold + bonds cushion
# equity crashes). It is NOT a return-maximiser; in a pure equity bull it gives ground (it caps equity exposure).
#
# THE RULE (monthly, signal at month-end t, trade/hold over month t+1 — NO look-ahead):
#   1. At the last trading day of month t, for each asset estimate realized vol = stdev of the trailing VOL_LOOKBACK_D
#      (=60) DAILY total-return log-ish simple returns, annualized (display only; the WEIGHT only needs relative vol).
#   2. weight_i = (1/vol_i) / sum_j(1/vol_j)   — inverse-vol, normalized to sum to 1 (fully invested, long-only).
#   3. HOLD those weights through month t+1; the portfolio return is the weight-dot-sleeve-return over that month.
#   4. Pay a rebalance fee on the TURNOVER = sum_i |target_w_i - drifted_w_i| * fee_bps/side at each month boundary.
#   All weights are decided from data through month-end t only; the realized return uses month t+1 (unseen at decision).
#
# DATA: DAILY adjusted-close (total-return) `<SYM>_tr_daily.json` (equity_risk_parity_backfill.py) for BOTH the 60d vol
#   estimate AND the monthly held return — same total-return basis so dividends/coupons (most of AGG's return) count.
#   Binds on the youngest sleeve (GLD lists 2004-11) + a warm 60d vol window -> first held month ~2005-04.
#
# FEES: REAL IBKR all-in on liquid ETFs ~1 bp/side. A monthly rebalance trades only the weight DRIFT (turnover), so the
#   fee is sum|Δw|*bps; we sweep {1,2,3,5} bps/side so the verdict is not knife-edge fee-dependent.
#
# VALIDATION (the DEPLOYMENT bar, not the 0.95 Gate): positive OOS net of real fees, BEATS BOTH 60/40 AND buy-and-hold
#   SPY risk-adjusted (higher Sharpe AND/OR materially lower maxDD), robust across an IS/OOS purged temporal split and
#   the major regime subperiods (2008, 2020, 2022). An honest FAIL here is a valid result — we never tune to pass.

from __future__ import annotations

import json
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import os

CACHE = Path(os.environ.get("COSMU_EQUITY_CACHE", "/Users/device/cosmu/.cosmu/market_data/equities"))

ASSETS = ["SPY", "AGG", "GLD"]          # the inverse-vol basket (US equity / US agg bonds / gold)
BENCH_SPY = "SPY"                       # buy-and-hold benchmark
SIXTY_FORTY = {"SPY": 0.60, "AGG": 0.40}  # the classic balanced benchmark (monthly rebalanced)

VOL_LOOKBACK_D = 60                     # trailing TRADING days of daily returns for the realized-vol estimate
IBKR_ETF_BPS_PER_SIDE = 1.0            # central IBKR all-in estimate on liquid ETFs; swept below
FEE_SWEEP_BPS = [1.0, 2.0, 3.0, 5.0]
MONTHS_PER_YEAR = 12
TRADING_DAYS_YR = 252


# --------------------------------------------------------------------------- data


@dataclass
class DailySeries:
    symbol: str
    ts: list[int]               # ms, ascending
    close: list[float]          # adjusted (total-return) close, aligned to ts


def load_daily(symbol: str) -> DailySeries:
    rows = json.loads((CACHE / f"{symbol}_tr_daily.json").read_text())
    rows.sort(key=lambda r: int(r["ts"]))
    return DailySeries(symbol, [int(r["ts"]) for r in rows], [float(r["close"]) for r in rows])


def _month_key(ms: int) -> tuple[int, int]:
    d = datetime.fromtimestamp(ms / 1000, tz=UTC).date()
    return (d.year, d.month)


@dataclass
class AssetData:
    """Daily closes + the month-end INDEX (last trading-day position) per calendar month."""
    symbol: str
    ts: list[int]
    close: list[float]
    month_end_idx: dict[tuple[int, int], int]  # (year,month) -> index of the LAST daily bar in that month
    months: list[tuple[int, int]]               # ascending list of months present


def build(symbol: str) -> AssetData:
    s = load_daily(symbol)
    last_in_month: dict[tuple[int, int], int] = {}
    for i, ms in enumerate(s.ts):
        last_in_month[_month_key(ms)] = i  # ascending -> ends up at the last bar of the month
    months = sorted(last_in_month)
    return AssetData(symbol, s.ts, s.close, last_in_month, months)


# --------------------------------------------------------------------------- vol + returns


def realized_vol(a: AssetData, month_end: tuple[int, int], lookback_d: int) -> float | None:
    """Annualized stdev of the trailing `lookback_d` DAILY simple returns ENDING at the last trading day of `month_end`.
    None if that month has no bar or there isn't a full lookback window before it (NO synthetic fill, NO look-ahead —
    the window ends at a completed month-end and never reaches past it)."""
    end_i = a.month_end_idx.get(month_end)
    if end_i is None or end_i < lookback_d:
        return None
    rets = []
    for i in range(end_i - lookback_d + 1, end_i + 1):
        p0, p1 = a.close[i - 1], a.close[i]
        if p0 <= 0:
            return None
        rets.append(p1 / p0 - 1.0)
    if len(rets) < 2:
        return None
    sd = statistics.pstdev(rets)
    return sd * math.sqrt(TRADING_DAYS_YR)


def month_return(a: AssetData, month: tuple[int, int], prev_month: tuple[int, int]) -> float | None:
    """Total return of holding `a` THROUGH `month` = close[month-end]/close[prev_month-end] - 1. None if a month-end
    bar is missing (the caller drops that month — no fabrication)."""
    i_now = a.month_end_idx.get(month)
    i_prev = a.month_end_idx.get(prev_month)
    if i_now is None or i_prev is None:
        return None
    p_prev = a.close[i_prev]
    if p_prev <= 0:
        return None
    return a.close[i_now] / p_prev - 1.0


def _add_months(ym: tuple[int, int], n: int) -> tuple[int, int]:
    total = (ym[0] * 12 + (ym[1] - 1)) + n
    return (total // 12, total % 12 + 1)


def inverse_vol_weights(data: dict[str, AssetData], month_end: tuple[int, int], lookback_d: int) -> dict[str, float] | None:
    """Inverse-realized-vol weights for ASSETS as of `month_end`, normalized to sum to 1. None if any vol is
    unavailable that month (we never partially-fill a missing sleeve)."""
    inv: dict[str, float] = {}
    for sym in ASSETS:
        v = realized_vol(data[sym], month_end, lookback_d)
        if v is None or v <= 0:
            return None
        inv[sym] = 1.0 / v
    tot = sum(inv.values())
    if tot <= 0:
        return None
    return {sym: inv[sym] / tot for sym in ASSETS}


# --------------------------------------------------------------------------- backtest


@dataclass
class PortResult:
    months: list[tuple[int, int]]
    net_returns: list[float]
    gross_returns: list[float]
    weights: list[dict[str, float]]   # target weights HELD over each month
    turnover_sum: float               # sum of monthly sum|Δw| (a diagnostic of trading cost)


def first_investable_month(data: dict[str, AssetData], lookback_d: int) -> tuple[int, int]:
    """First month for which every asset has a month-end bar AND a full `lookback_d` daily window before it, so an
    inverse-vol weight exists for ALL sleeves (binds on the youngest / shortest-history sleeve = GLD)."""
    candidates: list[tuple[int, int]] = []
    for sym in ASSETS:
        a = data[sym]
        # walk months until the lookback window is full
        for m in a.months:
            end_i = a.month_end_idx[m]
            if end_i >= lookback_d:
                candidates.append(m)
                break
    return max(candidates)


def run_risk_parity(
    data: dict[str, AssetData],
    *,
    lookback_d: int = VOL_LOOKBACK_D,
    fee_bps_per_side: float = IBKR_ETF_BPS_PER_SIDE,
    start: tuple[int, int] | None = None,
    end: tuple[int, int] | None = None,
) -> PortResult:
    """Run inverse-vol risk parity month-by-month with no look-ahead: target weights for month M are computed from data
    through month M-1's end; the return is realized over month M; a turnover fee is charged at the M-1 month boundary on
    the difference between the new targets and the weights that DRIFTED into the boundary from the prior month's hold."""
    fee = fee_bps_per_side / 1e4
    all_months = data[BENCH_SPY].months
    months_out: list[tuple[int, int]] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    weights_out: list[dict[str, float]] = []
    prev_drifted: dict[str, float] | None = None  # weights as they DRIFTED into the rebalance boundary
    turnover_sum = 0.0
    for m in all_months:
        if start is not None and m < start:
            continue
        if end is not None and m > end:
            continue
        prev_m = _add_months(m, -1)
        signal_month = prev_m  # weights decided at the PRIOR month-end (PIT)
        w = inverse_vol_weights(data, signal_month, lookback_d)
        if w is None:
            continue
        # sleeve returns over month M
        sleeve_r: dict[str, float] = {}
        ok = True
        for sym in ASSETS:
            r = month_return(data[sym], m, prev_m)
            if r is None:
                ok = False
                break
            sleeve_r[sym] = r
        if not ok:
            continue
        gross = sum(w[sym] * sleeve_r[sym] for sym in ASSETS)
        # turnover cost at the rebalance boundary: trade from the drifted weights to the new targets
        if prev_drifted is None:
            turnover = sum(w.values())  # initial buy = full notional
        else:
            turnover = sum(abs(w[sym] - prev_drifted.get(sym, 0.0)) for sym in ASSETS)
        turnover_sum += turnover
        cost = turnover * fee
        net = gross - cost
        # drift the held weights through month M for the NEXT boundary's turnover calc
        drifted: dict[str, float] = {}
        denom = 1.0 + gross
        if denom <= 0:
            denom = 1e-9
        for sym in ASSETS:
            drifted[sym] = w[sym] * (1.0 + sleeve_r[sym]) / denom
        prev_drifted = drifted
        months_out.append(m)
        gross_r.append(gross)
        net_r.append(net)
        weights_out.append(w)
    return PortResult(months_out, net_r, gross_r, weights_out, turnover_sum)


def run_fixed_weight(
    data: dict[str, AssetData],
    target: dict[str, float],
    *,
    fee_bps_per_side: float = IBKR_ETF_BPS_PER_SIDE,
    start: tuple[int, int] | None = None,
    end: tuple[int, int] | None = None,
) -> PortResult:
    """A fixed-weight, monthly-rebalanced benchmark (e.g. 60/40). Same fee/turnover/PIT treatment as risk parity, but
    the target weights are constant — only DRIFT generates turnover each month."""
    fee = fee_bps_per_side / 1e4
    syms = list(target)
    all_months = data[BENCH_SPY].months
    months_out: list[tuple[int, int]] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    prev_drifted: dict[str, float] | None = None
    turnover_sum = 0.0
    for m in all_months:
        if start is not None and m < start:
            continue
        if end is not None and m > end:
            continue
        prev_m = _add_months(m, -1)
        sleeve_r: dict[str, float] = {}
        ok = True
        for sym in syms:
            r = month_return(data[sym], m, prev_m)
            if r is None:
                ok = False
                break
            sleeve_r[sym] = r
        if not ok:
            continue
        gross = sum(target[sym] * sleeve_r[sym] for sym in syms)
        if prev_drifted is None:
            turnover = sum(target.values())
        else:
            turnover = sum(abs(target[sym] - prev_drifted.get(sym, 0.0)) for sym in syms)
        turnover_sum += turnover
        net = gross - turnover * fee
        denom = 1.0 + gross
        if denom <= 0:
            denom = 1e-9
        prev_drifted = {sym: target[sym] * (1.0 + sleeve_r[sym]) / denom for sym in syms}
        months_out.append(m)
        gross_r.append(gross)
        net_r.append(net)
    return PortResult(months_out, net_r, gross_r, [], turnover_sum)


def run_buy_hold(data: dict[str, AssetData], symbol: str, *, start=None, end=None) -> list[float]:
    """Buy-and-hold monthly total returns of a single symbol over the window (no fee after the initial entry; one ETF,
    no rebalancing). Used as the SPY benchmark return stream."""
    a = data[symbol]
    out: list[float] = []
    for m in a.months:
        if start is not None and m < start:
            continue
        if end is not None and m > end:
            continue
        r = month_return(a, m, _add_months(m, -1))
        if r is not None:
            out.append(r)
    return out


# --------------------------------------------------------------------------- metrics


@dataclass
class PerfStats:
    n_months: int
    total_return: float
    cagr: float
    ann_vol: float
    ann_sharpe: float
    max_dd: float
    win_rate: float


def stats(returns: list[float]) -> PerfStats:
    n = len(returns)
    if n == 0:
        return PerfStats(0, 0, 0, 0, 0, 0, 0)
    equity = peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1 + r
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    total = equity - 1.0
    years = n / MONTHS_PER_YEAR
    cagr = equity ** (1 / years) - 1.0 if years > 0 else 0.0
    mean = statistics.fmean(returns)
    vol = statistics.pstdev(returns) if n > 1 else 0.0
    ann_vol = vol * math.sqrt(MONTHS_PER_YEAR)
    ann_sharpe = (mean / vol) * math.sqrt(MONTHS_PER_YEAR) if vol > 0 else 0.0
    win_rate = sum(1 for r in returns if r > 0) / n
    return PerfStats(n, total, cagr, ann_vol, ann_sharpe, max_dd, win_rate)


def _fmt(tag: str, p: PerfStats) -> str:
    return (f"  {tag:<26} n={p.n_months:>3}m  tot={p.total_return:+.1%}  CAGR={p.cagr:+.2%}  "
            f"vol={p.ann_vol:.2%}  Sharpe={p.ann_sharpe:+.2f}  maxDD={p.max_dd:.1%}  win={p.win_rate:.0%}")


# --------------------------------------------------------------------------- validation


def validate(lookback_d: int = VOL_LOOKBACK_D) -> dict:
    """Full honest validation. Returns a dict the arming path reuses for the backtest row + current weights."""
    data = {sym: build(sym) for sym in set(ASSETS) | {BENCH_SPY}}
    start = first_investable_month(data, lookback_d)
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)

    print("=" * 104)
    print("RISK PARITY (inverse-realized-vol {SPY, AGG, GLD}, monthly rebalance) — DEPLOY-A-DOCUMENTED-STRATEGY validation")
    print("NOT the 0.95 in-sample Gate. The edge is RISK-ADJUSTED: smoother equity curve (Sharpe and/or lower maxDD)")
    print("than 60/40 and buy-and-hold SPY, by diversifying across assets whose drawdowns rarely coincide.")
    print(f"Universe: {ASSETS} | vol lookback={lookback_d}d daily | signal@month-end t, hold t+1 | "
          f"window {start} -> {last_complete}")
    print("=" * 104)

    # ---- FULL SAMPLE ----
    rp = run_risk_parity(data, lookback_d=lookback_d, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=last_complete)
    rp_s = stats(rp.net_returns)
    rp_gross = stats(rp.gross_returns)
    sf = run_fixed_weight(data, SIXTY_FORTY, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=last_complete)
    sf_s = stats(sf.net_returns)
    spy_r = run_buy_hold(data, BENCH_SPY, start=start, end=last_complete)
    spy_s = stats(spy_r)
    print("\n### FULL SAMPLE — Risk Parity (net of IBKR fees) vs 60/40 vs buy-and-hold SPY (all total-return)")
    print(_fmt("Risk Parity (net,1bps)", rp_s))
    print(_fmt("Risk Parity (gross)", rp_gross))
    print(_fmt("60/40 SPY/AGG (net)", sf_s))
    print(_fmt("Buy & Hold SPY", spy_s))
    print(f"  RP avg monthly turnover: {rp.turnover_sum / max(rp_s.n_months,1):.1%}  "
          f"(low — inverse-vol weights drift slowly)")

    print("\n  Fee sensitivity (RP net Sharpe / net total / maxDD across IBKR fee assumptions):")
    for fee in FEE_SWEEP_BPS:
        r = run_risk_parity(data, lookback_d=lookback_d, fee_bps_per_side=fee, start=start, end=last_complete)
        s = stats(r.net_returns)
        print(f"    {fee:>3.0f} bps/side  Sharpe={s.ann_sharpe:+.2f}  tot={s.total_return:+.1%}  "
              f"CAGR={s.cagr:+.2%}  maxDD={s.max_dd:.1%}")

    # ---- IS / OOS purged temporal split ----
    n_total = rp_s.n_months
    mid_idx = rp.months[n_total // 2]
    is_end = mid_idx
    # embargo: the vol window is ~3 months of daily data; a 3-month gap keeps the OOS vol window off IS bars.
    embargo_m = 3
    oos_start = _add_months(is_end, embargo_m)
    print(f"\n### IS / OOS PURGED SPLIT — IS {start}->{is_end} | embargo {embargo_m}m | OOS {oos_start}->{last_complete}")
    rp_is = stats(run_risk_parity(data, lookback_d=lookback_d, start=start, end=is_end).net_returns)
    rp_oos = stats(run_risk_parity(data, lookback_d=lookback_d, start=oos_start, end=last_complete).net_returns)
    sf_oos = stats(run_fixed_weight(data, SIXTY_FORTY, start=oos_start, end=last_complete).net_returns)
    spy_oos = stats(run_buy_hold(data, BENCH_SPY, start=oos_start, end=last_complete))
    print("  [IS]")
    print(_fmt("Risk Parity (net)", rp_is))
    print("  [OOS]  <-- the deployment check")
    print(_fmt("Risk Parity (net)", rp_oos))
    print(_fmt("60/40 (net)", sf_oos))
    print(_fmt("Buy & Hold SPY", spy_oos))

    # ---- SUBPERIOD ROBUSTNESS ----
    print("\n### SUBPERIOD ROBUSTNESS — RP net total + maxDD vs 60/40 + SPY over each regime")
    subperiods = [
        ("2008 GFC crash   (07/2008-02/2009)", (2008, 7), (2009, 2)),
        ("recovery bull    (03/2009-12/2019)", (2009, 3), (2019, 12)),
        ("COVID crash      (02/2020-04/2020)", (2020, 2), (2020, 4)),
        ("2022 stock+bond  (01/2022-12/2022)", (2022, 1), (2022, 12)),
        ("post-2022 bull   (01/2023-now)    ", (2023, 1), last_complete),
    ]
    for label, s0, s1 in subperiods:
        if s0 < start:
            continue
        g = stats(run_risk_parity(data, lookback_d=lookback_d, start=s0, end=s1).net_returns)
        f = stats(run_fixed_weight(data, SIXTY_FORTY, start=s0, end=s1).net_returns)
        sp = stats(run_buy_hold(data, BENCH_SPY, start=s0, end=s1))
        print(f"  {label}  RP={g.total_return:+6.1%}(dd{g.max_dd:4.0%})  "
              f"60/40={f.total_return:+6.1%}(dd{f.max_dd:4.0%})  SPY={sp.total_return:+6.1%}(dd{sp.max_dd:4.0%})")

    # ---- VERDICT (deployment bar — honest, NOT pass-tuned) ----
    # The documented edge of risk parity is RISK-ADJUSTED return, NOT raw return. We require, on the FULL cycle:
    #   (1) OOS POSITIVE net of real fees (the edge survives out of sample), AND
    #   (2) beats buy-and-hold SPY risk-adjusted: higher Sharpe AND/OR materially lower maxDD, AND
    #   (3) beats 60/40 risk-adjusted: higher Sharpe AND/OR lower maxDD (else it adds nothing over the trivial balanced
    #       benchmark and isn't worth deploying as its own track).
    # "materially lower maxDD" = <= 75% of the benchmark's. Honest: if RP only ties on every axis we report FAIL.
    MATERIAL_DD = 0.75
    oos_positive = rp_oos.total_return > 0
    beats_spy = (rp_s.ann_sharpe > spy_s.ann_sharpe + 0.05) or (rp_s.max_dd <= spy_s.max_dd * MATERIAL_DD)
    beats_6040 = (rp_s.ann_sharpe > sf_s.ann_sharpe + 0.02) or (rp_s.max_dd <= sf_s.max_dd * 0.90)
    deployable = oos_positive and beats_spy and beats_6040
    print("\n" + "=" * 104)
    print("VERDICT (deployment bar — NOT the 0.95 in-sample Gate; the edge is risk-adjusted smoothness):")
    print(f"  (1) OOS net-of-fee POSITIVE?                  {oos_positive}  (OOS net total {rp_oos.total_return:+.1%})")
    print(f"  (2) Beats B&H SPY risk-adjusted?              {beats_spy}  "
          f"(RP Sharpe {rp_s.ann_sharpe:+.2f} vs {spy_s.ann_sharpe:+.2f}; "
          f"maxDD {rp_s.max_dd:.1%} vs {spy_s.max_dd:.1%} = {rp_s.max_dd / spy_s.max_dd:.0%} of SPY)")
    print(f"  (3) Beats 60/40 risk-adjusted?                {beats_6040}  "
          f"(RP Sharpe {rp_s.ann_sharpe:+.2f} vs {sf_s.ann_sharpe:+.2f}; "
          f"maxDD {rp_s.max_dd:.1%} vs {sf_s.max_dd:.1%})")
    print(f"  ==> {'DEPLOYABLE — arm the live forward-test' if deployable else 'NOT deployable on our data'}")
    print("=" * 104)

    current_w = inverse_vol_weights(data, last_complete, lookback_d)
    print(f"\nCURRENT risk-parity weights (decided at {last_complete} month-end, to hold next month): "
          + ", ".join(f"{s}={current_w[s]:.1%}" for s in ASSETS) if current_w else "\nCURRENT weights: unavailable")

    return {
        "deployable": deployable,
        "current_weights": current_w,
        "full": rp_s,
        "full_6040": sf_s,
        "full_spy": spy_s,
        "oos": rp_oos,
        "oos_6040": sf_oos,
        "oos_spy": spy_oos,
        "window": (start, last_complete),
        "result": rp,
        "avg_turnover": rp.turnover_sum / max(rp_s.n_months, 1),
    }


def main(argv: list[str] | None = None) -> int:
    validate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
