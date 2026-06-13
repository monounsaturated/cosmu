# intent: DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). Wouter Keller & Jan Willem
# Keuning's PROTECTIVE ASSET ALLOCATION (PAA), from "Protective Asset Allocation (PAA): A Simple Momentum-Based
# Alternative for Term Deposits" (2016). Externally validated, published, widely replicated. Like GEM/VAA it is a
# documented monthly cross-asset rotation; it does NOT need our in-sample Gate to "discover" it (the Gate is an
# overfitting guard for NOVEL mined edges). The appropriate validators are (a) the external literature, (b) a positive
# OOS-net-of-fees check on OUR total-return data that BEATS buy-and-hold SPY risk-adjusted, (c) the LIVE paper.
# This module does (b) and (its sibling arm) does (c). It NEVER touches / lowers the 0.95 Gate.
#
# THE RULE (monthly; signal at month-end t from completed-month closes, trade t+1 — NO look-ahead):
#   RISK universe (here, the liquid ETFs we hold point-in-time): {SPY, QQQ, EFA, EEM, GLD, AGG, LQD, TLT}.
#   SAFE asset (the crash-protection bucket) = IEF (7-10y Treasury).
#   1. Momentum of each risk asset = close[t] / SMA_12(t) - 1  (the price relative to its own 12-month average; the SMA
#      INCLUDES close[t]). "Good" = momentum > 0 (the asset is above its own trend).
#   2. n = count of risk assets with momentum > 0 (the BREADTH of the risk universe).
#   3. Protective BOND FRACTION (the PAA crash dial): BF = (N - n) / (N - n1), clamped to [0, 1], where
#      N = number of risk assets and n1 = a * N / 4 with protection factor a = 1 (PAA1, the canonical "medium"
#      protection). As breadth weakens (n falls), BF rises toward 1 (fully into the safe asset) — a STEPWISE,
#      breadth-driven de-risk, NOT a binary switch. BF of capital goes to IEF.
#   4. The remaining (1 - BF) is split EQUALLY across the TOP-`TOP_N` risk assets by momentum that are also "good"
#      (momentum > 0). If fewer than TOP_N are good, only the good ones are held (the rest of the risk fraction also
#      parks in the safe asset — never a forced buy of a down-trending asset).
#   This is the canonical PAA: ride the strongest trending assets, and let DETERIORATING BREADTH (not a single index)
#   pull the book progressively into Treasuries before a crash deepens. The documented payoff is a dramatically lower
#   drawdown than buy-and-hold equities at a comparable return.
#
# DATA: TOTAL-RETURN (adjusted-close) MONTHLY bars from the equities cache `*_tr.json`
#   (equity_total_return_backfill.py) — dividends are most of a bond ETF's return, so a raw-price SMA/return is biased.
#   The window starts the first month every series has its full 12m SMA available (binds on the youngest ETF).
#
# FEES: REAL IBKR all-in on liquid ETFs ~1 bp/side (0.5 commission + ~0.5 spread/impact). Fees are charged on the
#   fraction of the portfolio whose target weight CHANGES month to month (turnover * 1 side). Sweep {1,2,3,5} bps/side
#   so the verdict is not knife-edge fee-dependent.
#
# VALIDATION (the DEPLOYMENT bar, not the 0.95 Gate): positive OOS net of real fees, BEATS buy-and-hold SPY
#   risk-adjusted (higher Sharpe AND/OR materially lower maxDD), robust across an IS/OOS purged temporal split + the
#   major regime subperiods.
#
# Propose/measure-only — this module moves no money; the sibling `equity_paa_arm` arms a SIM paper (live OFF).

from __future__ import annotations

import json
import math
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CACHE = Path(os.environ.get("COSMU_EQUITY_CACHE", "/Users/device/cosmu/.cosmu/market_data/equities"))

# PAA risk universe (the liquid ETFs we hold point-in-time) + the single safe / crash-protection asset.
RISK_UNIVERSE = ["SPY", "QQQ", "EFA", "EEM", "GLD", "AGG", "LQD", "TLT"]
SAFE = "IEF"  # the crash-protection bucket — capital flows here as breadth deteriorates
BENCHMARK = "SPY"  # buy-and-hold benchmark for the deployment bar
PAA_SERIES = sorted(set([*RISK_UNIVERSE, SAFE, BENCHMARK]))

SMA_MONTHS = 12  # canonical PAA momentum lookback (close vs 12m SMA, SMA inclusive of the current month-end close)
TOP_N = 6        # canonical PAA "top-6" risk holding (split the risk fraction equally across the 6 strongest)
PROTECTION_FACTOR = 1.0  # PAA1 ("medium" protection): n1 = a*N/4 with a=1
N_RISK = len(RISK_UNIVERSE)
N1 = PROTECTION_FACTOR * N_RISK / 4.0  # breadth at which BF hits 1 (fully defensive)

IBKR_ETF_BPS_PER_SIDE = 1.0  # central IBKR all-in estimate on liquid ETFs; sweep below
FEE_SWEEP_BPS = [1.0, 2.0, 3.0, 5.0]
MONTHS_PER_YEAR = 12


# --------------------------------------------------------------------------- data


@dataclass
class MonthlySeries:
    symbol: str
    months: list[tuple[int, int]]   # (year, month) ascending
    close: dict[tuple[int, int], float]  # month -> total-return (adjusted) close


def _month_key(ms: int) -> tuple[int, int]:
    d = datetime.fromtimestamp(ms / 1000, tz=UTC).date()
    return (d.year, d.month)


def load_monthly(symbol: str) -> MonthlySeries:
    """Load a `*_tr.json` total-return series collapsed to ONE close per calendar month (the last bar in the month).
    The backfill returns ~monthly bars; collapsing is idempotent and robust to a stray intra-month bar (e.g. the
    partial current-month bar). PIT: only the last *completed* observation in a month is used as that month's close."""
    path = CACHE / f"{symbol}_tr.json"
    rows = json.loads(path.read_text())
    by_month: dict[tuple[int, int], tuple[int, float]] = {}
    for r in rows:
        ts = int(r["ts"])
        mk = _month_key(ts)
        if mk not in by_month or ts >= by_month[mk][0]:
            by_month[mk] = (ts, float(r["close"]))
    months = sorted(by_month)
    return MonthlySeries(symbol, months, {m: by_month[m][1] for m in months})


def _add_months(ym: tuple[int, int], n: int) -> tuple[int, int]:
    y, m = ym
    total = (y * 12 + (m - 1)) + n
    return (total // 12, total % 12 + 1)


# --------------------------------------------------------------------------- signal + backtest


def _momentum(s: MonthlySeries, asof: tuple[int, int], window: int) -> float | None:
    """PAA momentum of one asset at month-end `asof`: close[asof] / SMA_window(asof) - 1 (the SMA INCLUDES close[asof]).
    None if the full window of month-end closes is not available (the caller drops that asset — NO synthetic fill, NO
    look-ahead: `asof` is a completed month-end)."""
    closes: list[float] = []
    for k in range(window):
        c = s.close.get(_add_months(asof, -k))
        if c is None:
            return None
        closes.append(c)
    sma = statistics.fmean(closes)
    if sma <= 0:
        return None
    return s.close.get(asof, 0.0) / sma - 1.0


def _realized_return(s: MonthlySeries, month: tuple[int, int]) -> float | None:
    """Total return of holding `s` THROUGH `month` = close[month]/close[month-1] - 1. None if either close missing."""
    prev = _add_months(month, -1)
    c = s.close.get(month)
    c_prev = s.close.get(prev)
    if c is None or c_prev is None or c_prev <= 0:
        return None
    return c / c_prev - 1.0


def _target_weights(
    series: dict[str, MonthlySeries], asof: tuple[int, int], window: int
) -> dict[str, float] | None:
    """The PAA target weight per symbol decided at month-end `asof` (to be HELD next month). Returns a {symbol: weight}
    map summing to ~1.0 (the safe asset absorbs the bond fraction + any unfilled risk fraction), or None if any required
    momentum is unavailable that month (fail closed — no partial book, no synthetic fill)."""
    moms: dict[str, float] = {}
    for sym in RISK_UNIVERSE:
        m = _momentum(series[sym], asof, window)
        if m is None:
            return None
        moms[sym] = m
    # Breadth: number of "good" (above-trend) risk assets.
    good = [sym for sym in RISK_UNIVERSE if moms[sym] > 0]
    n = len(good)
    # PAA protective bond fraction: BF = (N - n) / (N - n1), clamped [0, 1].
    bf = (N_RISK - n) / (N_RISK - N1) if (N_RISK - N1) > 0 else 1.0
    bf = max(0.0, min(1.0, bf))
    risk_fraction = 1.0 - bf
    # Hold the TOP_N good risk assets by momentum; split the risk fraction equally across however many are actually held.
    held = sorted(good, key=lambda s: moms[s], reverse=True)[:TOP_N]
    weights: dict[str, float] = {SAFE: bf}
    if held and risk_fraction > 0:
        per = risk_fraction / len(held)
        for sym in held:
            weights[sym] = weights.get(sym, 0.0) + per
    else:
        # No good risk assets (or fully defensive): the whole risk fraction also parks in the safe asset.
        weights[SAFE] = weights.get(SAFE, 0.0) + risk_fraction
    return weights


@dataclass
class PaaResult:
    months: list[tuple[int, int]]          # the months the strategy was INVESTED (a return realized for each)
    weights: list[dict[str, float]]        # the target weights held entering each month (signal from the PRIOR end)
    net_returns: list[float]               # monthly NET-of-fee total return of the strategy
    gross_returns: list[float]
    spy_returns: list[float]               # buy-and-hold SPY total return over the SAME months (the benchmark)
    turnover: float                        # cumulative one-sided turnover over the window (a fee proxy)
    bond_fractions: list[float]            # the protective bond fraction (BF) each month — the de-risk dial


def run_paa(
    series: dict[str, MonthlySeries],
    *,
    window: int = SMA_MONTHS,
    fee_bps_per_side: float = IBKR_ETF_BPS_PER_SIDE,
    start: tuple[int, int] | None = None,
    end: tuple[int, int] | None = None,
) -> PaaResult:
    """Run PAA month-by-month with no look-ahead: the target weights for month M are decided from data through month
    M-1's end (signal@M-1, trade@M); the portfolio return over M is the weighted blend of each held asset's realized
    return; a fee is charged on the one-sided turnover (sum of |w_M - w_{M-1}| / 2) at month M vs the prior month."""
    fee = fee_bps_per_side / 1e4
    all_months = series[BENCHMARK].months
    months_out: list[tuple[int, int]] = []
    weights_out: list[dict[str, float]] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    spy_r: list[float] = []
    bf_out: list[float] = []
    total_turnover = 0.0
    prev_w: dict[str, float] | None = None
    for m in all_months:
        if start is not None and m < start:
            continue
        if end is not None and m > end:
            continue
        signal_month = _add_months(m, -1)  # decide at the PRIOR month-end (PIT)
        w = _target_weights(series, signal_month, window)
        if w is None:
            continue
        # Require every held asset (+ SPY benchmark) to have a realized return this month (no synthetic fill).
        rets: dict[str, float] = {}
        ok = True
        for sym in w:
            r = _realized_return(series[sym], m)
            if r is None:
                ok = False
                break
            rets[sym] = r
        spy = _realized_return(series[BENCHMARK], m)
        if not ok or spy is None:
            continue
        gross = sum(w[sym] * rets[sym] for sym in w)
        # Turnover fee: one-sided turnover = 0.5 * sum |w_M - w_{M-1}| over the union of held symbols. The first month
        # pays one side on the full deployment (turnover = 1.0). An unchanged book pays nothing.
        if prev_w is None:
            turnover = 1.0
        else:
            symbols = set(w) | set(prev_w)
            turnover = 0.5 * sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in symbols)
        total_turnover += turnover
        cost = turnover * fee
        net = gross - cost
        months_out.append(m)
        weights_out.append(w)
        gross_r.append(gross)
        net_r.append(net)
        spy_r.append(spy)
        bf_out.append(w.get(SAFE, 0.0))
        prev_w = w
    return PaaResult(months_out, weights_out, net_r, gross_r, spy_r, total_turnover, bf_out)


# --------------------------------------------------------------------------- metrics


@dataclass
class PerfStats:
    n_months: int
    total_return: float        # cumulative, compounded
    cagr: float
    ann_vol: float
    ann_sharpe: float          # annualized, rf=0 (both legs share rf so the COMPARISON to SPY is fair)
    max_dd: float
    win_rate: float


def _stats(returns: list[float]) -> PerfStats:
    n = len(returns)
    if n == 0:
        return PerfStats(0, 0, 0, 0, 0, 0, 0)
    equity = 1.0
    peak = 1.0
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


def first_investable_month(series: dict[str, MonthlySeries], window: int) -> tuple[int, int]:
    """The first month every PAA series has its FULL `window`-month SMA available AND a realized return (so the signal
    at M-1 and the return over M both exist for all of them). Binds on the youngest ETF."""
    starts = []
    for sym in PAA_SERIES:
        s = series[sym]
        first = s.months[0]
        starts.append(_add_months(first, window))
    return max(starts)


# --------------------------------------------------------------------------- report (the validation)


def _fmt_stats(tag: str, p: PerfStats) -> str:
    return (f"  {tag:<22} n={p.n_months:>3}m  tot={p.total_return:+.1%}  CAGR={p.cagr:+.2%}  "
            f"vol={p.ann_vol:.2%}  Sharpe={p.ann_sharpe:+.2f}  maxDD={p.max_dd:.1%}  win={p.win_rate:.0%}")


def current_weights(window: int = SMA_MONTHS) -> dict[str, float]:
    """The PAA target weights at the latest COMPLETED month-end (to be held next month). Empty if unavailable."""
    series = {sym: load_monthly(sym) for sym in PAA_SERIES}
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)
    w = _target_weights(series, last_complete, window)
    return w or {}


def validate(window: int = SMA_MONTHS) -> dict:
    """Run the full honest validation and print it. Returns a dict the arming path reuses for the backtest row."""
    series = {sym: load_monthly(sym) for sym in PAA_SERIES}
    start = first_investable_month(series, window)
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)  # drop the partial current month

    print("=" * 104)
    print("KELLER PROTECTIVE ASSET ALLOCATION (PAA1, top-6, a=1) — DEPLOY-A-DOCUMENTED-STRATEGY validation")
    print("NOT the 0.95 in-sample Gate. Externally validated edge (Keller & Keuning 2016); here we check POSITIVE OOS")
    print("net of REAL IBKR fees + BEATS buy-and-hold SPY risk-adjusted, on our total-return (div-adjusted) monthly data.")
    print(f"RISK universe (N={N_RISK}): {RISK_UNIVERSE} | SAFE={SAFE} | top-{TOP_N} | SMA={window}m | "
          f"protective BF=(N-n)/(N-{N1:g})")
    print(f"signal@month-end t (SMA inclusive of t), trade t+1 | window {start} -> {last_complete}")
    print("=" * 104)

    # ---- FULL SAMPLE at the central fee + fee sweep ----
    print("\n### FULL SAMPLE — PAA (net of IBKR fees) vs buy-and-hold SPY (total return)")
    full = run_paa(series, window=window, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=last_complete)
    paa_stats = _stats(full.net_returns)
    spy_stats = _stats(full.spy_returns)
    gross_stats = _stats(full.gross_returns)
    print(_fmt_stats("PAA (net, 1bps/side)", paa_stats))
    print(_fmt_stats("PAA (gross)", gross_stats))
    print(_fmt_stats("Buy & Hold SPY", spy_stats))
    avg_bf = statistics.fmean(full.bond_fractions) if full.bond_fractions else 0.0
    print(f"  one-sided turnover over window: {full.turnover:.1f}  (~{full.turnover / (paa_stats.n_months / 12):.1f}/yr) "
          f"|  avg protective bond fraction: {avg_bf:.0%} (the de-risk dial)")

    print("\n  Fee sensitivity (net Sharpe / net total / maxDD across IBKR fee assumptions):")
    for fee in FEE_SWEEP_BPS:
        r = run_paa(series, window=window, fee_bps_per_side=fee, start=start, end=last_complete)
        s = _stats(r.net_returns)
        print(f"    {fee:>3.0f} bps/side  Sharpe={s.ann_sharpe:+.2f}  tot={s.total_return:+.1%}  "
              f"CAGR={s.cagr:+.2%}  maxDD={s.max_dd:.1%}")

    # ---- IS / OOS purged temporal split ----
    # Split the window in half by time. PURGE: the OOS leg starts `window` months AFTER the IS leg ends so no OOS
    # signal is computed from any IS-era bar (the 12m SMA window can't straddle the boundary).
    n_total = paa_stats.n_months
    is_end = full.months[n_total // 2]
    oos_start = _add_months(is_end, window)
    print(f"\n### IS / OOS PURGED SPLIT — IS {start}->{is_end} | purge {window}m | OOS {oos_start}->{last_complete}")
    is_run = run_paa(series, window=window, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=is_end)
    oos_run = run_paa(series, window=window, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=oos_start, end=last_complete)
    is_paa, is_spy = _stats(is_run.net_returns), _stats(is_run.spy_returns)
    oos_paa, oos_spy = _stats(oos_run.net_returns), _stats(oos_run.spy_returns)
    print("  [IS]")
    print(_fmt_stats("PAA (net)", is_paa))
    print(_fmt_stats("Buy & Hold SPY", is_spy))
    print("  [OOS]  <-- the deployment check")
    print(_fmt_stats("PAA (net)", oos_paa))
    print(_fmt_stats("Buy & Hold SPY", oos_spy))

    # ---- SUBPERIOD ROBUSTNESS — PAA's documented edge is CRASH PROTECTION via deteriorating breadth ----
    print("\n### SUBPERIOD ROBUSTNESS — PAA net total vs B&H SPY total over each regime (the edge is asymmetric)")
    subperiods = [
        ("2008 GFC crash    (01/2008-02/2009)", (2008, 1), (2009, 2)),
        ("recovery+QE bull  (03/2009-12/2019)", (2009, 3), (2019, 12)),
        ("COVID crash       (02/2020-04/2020)", (2020, 2), (2020, 4)),
        ("2022 bear         (01/2022-12/2022)", (2022, 1), (2022, 12)),
        ("post-2022 bull    (01/2023-now)     ", (2023, 1), last_complete),
    ]
    for label, s0, s1 in subperiods:
        if s0 < start:
            continue
        gr = run_paa(series, window=window, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=s0, end=s1)
        g, sp = _stats(gr.net_returns), _stats(gr.spy_returns)
        edge = g.total_return - sp.total_return
        print(f"  {label}  PAA={g.total_return:+6.1%}  SPY={sp.total_return:+6.1%}  edge={edge:+6.1%}  "
              f"(PAA maxDD {g.max_dd:.0%} vs SPY {sp.max_dd:.0%})")

    # ---- VERDICT (deployment bar — honest, NOT pass-tuned) ----
    # The prompt's bar: positive OOS net of fees, AND beats B&H SPY on "higher Sharpe AND/OR materially lower maxDD",
    # robust across subperiods, on the real holdout. PAA's documented edge is crash protection via the breadth-driven
    # bond dial -> a materially lower maxDD (and, because it cuts volatility hard, usually a higher Sharpe too). We
    # require, applying the prompt's exact AND/OR bar to the REAL OOS leg + full cycle:
    #   (1) OOS POSITIVE net of real fees (the edge survives out of sample), AND
    #   (2) OOS risk-adjusted beat: OOS Sharpe >= SPY's OOS Sharpe OR OOS maxDD materially lower, AND
    #   (3) FULL-cycle risk-adjusted beat: higher Sharpe AND/OR materially lower maxDD vs B&H SPY.
    # No knob is tuned to pass; the fee sweep + subperiod table are disclosed so the verdict is not knife-edge.
    MATERIAL_DD_REDUCTION = 0.75  # "materially lower" = <= 75% of SPY's maxDD
    oos_positive = oos_paa.total_return > 0
    oos_sharpe_beat = oos_paa.ann_sharpe >= oos_spy.ann_sharpe
    oos_dd_beat = oos_paa.max_dd <= oos_spy.max_dd * MATERIAL_DD_REDUCTION
    oos_riskadj_beat = oos_sharpe_beat or oos_dd_beat
    full_sharpe_beat = paa_stats.ann_sharpe >= spy_stats.ann_sharpe
    full_dd_beat = paa_stats.max_dd <= spy_stats.max_dd * MATERIAL_DD_REDUCTION
    full_riskadj_beat = full_sharpe_beat or full_dd_beat
    deployable = oos_positive and oos_riskadj_beat and full_riskadj_beat

    print("\n" + "=" * 104)
    print("VERDICT (deployment bar — NOT the 0.95 in-sample Gate; the edge is crash protection via breadth):")
    print(f"  (1) OOS net-of-fee POSITIVE?                       {oos_positive}  (OOS net total {oos_paa.total_return:+.1%})")
    print(f"  (2) OOS risk-adjusted beat vs B&H SPY?             {oos_riskadj_beat}  "
          f"(Sharpe {oos_paa.ann_sharpe:+.2f} vs {oos_spy.ann_sharpe:+.2f} [{oos_sharpe_beat}]; "
          f"maxDD {oos_paa.max_dd:.1%} vs {oos_spy.max_dd:.1%} [{oos_dd_beat}])")
    print(f"  (3) FULL-cycle risk-adjusted beat vs B&H SPY?      {full_riskadj_beat}  "
          f"(Sharpe {paa_stats.ann_sharpe:+.2f} vs {spy_stats.ann_sharpe:+.2f} [{full_sharpe_beat}]; "
          f"maxDD {paa_stats.max_dd:.1%} vs {spy_stats.max_dd:.1%} [{full_dd_beat}])")
    print(f"  ==> {'DEPLOYABLE — arm the live paper' if deployable else 'NOT deployable on our data'}")
    print("  HONEST EXPECTATION: a crash-protection portfolio — deteriorating breadth (fewer assets above their 12m")
    print("  trend) pulls the book PROGRESSIVELY into Treasuries. It trades a slice of bull upside for a much shallower")
    print("  drawdown and lower volatility than buy-and-hold equities. That asymmetry IS the documented edge.")
    print("=" * 104)

    cur = _target_weights(series, last_complete, window) or {}
    held_now = sorted(((s, w) for s, w in cur.items() if w > 0), key=lambda kv: kv[1], reverse=True)
    print(f"\nCURRENT PAA target weights (decided at {last_complete} month-end, to hold next month):")
    for s, w in held_now:
        print(f"  {s}: {w:.0%}")
    print(f"  -> protective bond fraction (SAFE={SAFE}): {cur.get(SAFE, 0.0):.0%}")

    return {
        "deployable": deployable,
        "current_weights": cur,
        "full": paa_stats,
        "full_spy": spy_stats,
        "oos": oos_paa,
        "oos_spy": oos_spy,
        "turnover": full.turnover,
        "window": (start, last_complete),
        "result": full,
    }


def main(argv: list[str] | None = None) -> int:
    validate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
