# intent: DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). Wouter Keller & Jan Willem
# Keuning's DEFENSIVE ASSET ALLOCATION (DAA), from "Breadth Momentum and the Canary Universe: Defensive Asset
# Allocation (DAA)" (2018) — the successor to their VAA. Externally validated, published, widely replicated. Like
# GEM/VAA/PAA it is a documented monthly cross-asset rotation; it does NOT need our in-sample Gate to "discover" it
# (the Gate is an overfitting guard for NOVEL mined edges). The appropriate validators are (a) the external literature,
# (b) a positive OOS-net-of-fees check on OUR total-return data that BEATS buy-and-hold SPY risk-adjusted, (c) the LIVE
# paper. This module does (b) and (its sibling arm) does (c). It NEVER touches / lowers the 0.95 Gate.
#
# THE RULE (monthly; signal at month-end t from completed-month closes, trade t+1 — NO look-ahead):
#   RISK universe (the liquid ETFs we hold point-in-time): {SPY, QQQ, EFA, EEM, GLD, AGG, LQD, TLT}.
#   CANARY universe = {EEM, AGG}                  # the crash detectors (Keller uses VWO+BND; EEM/AGG are the proxies
#                                                 #  available point-in-time, exactly as our VAA module uses them).
#   DEFENSIVE pool   = {SHY, IEF, LQD}            # where the protective fraction parks (best of the three by momentum).
#   Momentum score of an asset = 12*r1m + 4*r3m + 2*r6m + 1*r12m   ("13612W" trailing TOTAL-return weighting, Keller).
#   1. b = number of canaries with score <= 0 (the BREADTH of the crash signal; B = 2 canaries total).
#   2. Protective CASH FRACTION = b / B  (0 with both canaries good, 1/2 with one bad, 1 with both bad). This is DAA's
#      STEPWISE breadth-momentum de-risk — NOT VAA's binary risk-on/off switch.
#   3. The protective fraction parks in the single BEST-scoring defensive asset (max score of {SHY, IEF, LQD}).
#   4. The remaining (1 - cash fraction) is split EQUALLY across the TOP-`TOP_N` risk assets by score (DAA holds a
#      basket of the strongest risk assets, not VAA's single top-1).
#   This is canonical DAA (the "G* / B1" family, here a top-6 risk basket with the EEM/AGG canary pair): the canary
#   breadth signal scales the book PROGRESSIVELY into short Treasuries before equity drawdowns deepen, while holding a
#   diversified momentum basket when risk is on. The documented payoff is a much lower drawdown than buy-and-hold
#   equities, typically at a HIGHER full-cycle Sharpe.
#
# DATA: TOTAL-RETURN (adjusted-close) MONTHLY bars from the equities cache `*_tr.json`
#   (equity_total_return_backfill.py) — dividends are most of a bond ETF's return, so a raw-price rank is biased. The
#   window starts the first month every series has its full 12m trailing return available (binds on the youngest ETF).
#
# FEES: REAL IBKR all-in on liquid ETFs ~1 bp/side (0.5 commission + ~0.5 spread/impact). Fees are charged on the
#   one-sided turnover (sum of |w_M - w_{M-1}| / 2) month to month. DAA is HIGHER turnover than GEM/PAA (the canary
#   step can rotate the whole basket), so the fee leg matters — sweep {1,2,3,5} bps/side so the verdict isn't knife-edge.
#
# VALIDATION (the DEPLOYMENT bar, not the 0.95 Gate): positive OOS net of real fees, BEATS buy-and-hold SPY
#   risk-adjusted (higher Sharpe AND/OR materially lower maxDD), robust across an IS/OOS purged split + major regimes.
#
# Propose/measure-only — this module moves no money; the sibling `equity_daa_arm` arms a SIM paper (live OFF).

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

# DAA universe (the liquid ETFs we hold point-in-time).
RISK_UNIVERSE = ["SPY", "QQQ", "EFA", "EEM", "GLD", "AGG", "LQD", "TLT"]
CANARY = ["EEM", "AGG"]            # crash detectors (Keller VWO+BND proxies, as in our VAA module)
DEFENSIVE = ["SHY", "IEF", "LQD"]  # the protective pool — the best by score holds the protective fraction
BENCHMARK = "SPY"                  # buy-and-hold benchmark for the deployment bar
DAA_SERIES = sorted(set([*RISK_UNIVERSE, *CANARY, *DEFENSIVE, BENCHMARK]))

# 13612W momentum weighting: 12*1m + 4*3m + 2*6m + 1*12m (Keller). Lookbacks in months -> weight.
SCORE_WEIGHTS: list[tuple[int, float]] = [(1, 12.0), (3, 4.0), (6, 2.0), (12, 1.0)]
MAX_LOOKBACK = 12  # longest trailing window used (binds the first investable month + the IS/OOS purge gap)
TOP_N = 6          # canonical DAA top-6 risk basket (split the risk fraction equally across the 6 strongest)
N_CANARY = len(CANARY)  # B = 2 canaries -> cash fraction is b/B in {0, 1/2, 1}

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


def _trailing_return(s: MonthlySeries, asof: tuple[int, int], lookback: int) -> float | None:
    """Trailing `lookback`-month TOTAL return of `s` as of month `asof` (close[asof]/close[asof-lookback] - 1). None if
    either endpoint is missing — the caller treats the asset's score as unavailable (NO synthetic fill, NO look-ahead:
    `asof` is a completed month-end)."""
    past = _add_months(asof, -lookback)
    c_now = s.close.get(asof)
    c_past = s.close.get(past)
    if c_now is None or c_past is None or c_past <= 0:
        return None
    return c_now / c_past - 1.0


def _score(series: dict[str, MonthlySeries], symbol: str, asof: tuple[int, int]) -> float | None:
    """13612W momentum score of `symbol` at month-end `asof`: 12*r1 + 4*r3 + 2*r6 + 1*r12. None if ANY of the four
    trailing returns is unavailable (we never fabricate a partial score — fail closed so a half-history asset can't be
    ranked top)."""
    s = series[symbol]
    total = 0.0
    for lb, w in SCORE_WEIGHTS:
        r = _trailing_return(s, asof, lb)
        if r is None:
            return None
        total += w * r
    return total


def _realized_return(s: MonthlySeries, month: tuple[int, int]) -> float | None:
    """Total return of holding `s` THROUGH `month` = close[month]/close[month-1] - 1. None if either close missing."""
    prev = _add_months(month, -1)
    c = s.close.get(month)
    c_prev = s.close.get(prev)
    if c is None or c_prev is None or c_prev <= 0:
        return None
    return c / c_prev - 1.0


def _target_weights(
    series: dict[str, MonthlySeries], asof: tuple[int, int]
) -> dict[str, float] | None:
    """The DAA target weight per symbol decided at month-end `asof` (to be HELD next month). Returns a {symbol: weight}
    map summing to ~1.0 (the best defensive asset absorbs the protective cash fraction; the risk basket holds the rest),
    or None if any required score is unavailable that month (fail closed — no partial book, no synthetic fill)."""
    # Canary breadth: b = number of canaries with score <= 0; protective cash fraction = b / B.
    b = 0
    for c in CANARY:
        sc = _score(series, c, asof)
        if sc is None:
            return None
        if sc <= 0:
            b += 1
    cash_fraction = b / N_CANARY
    risk_fraction = 1.0 - cash_fraction

    weights: dict[str, float] = {}

    # Protective fraction -> the single best-scoring defensive asset.
    if cash_fraction > 0:
        best_def: str | None = None
        best_def_score = -math.inf
        for sym in DEFENSIVE:
            sc = _score(series, sym, asof)
            if sc is None:
                return None
            if sc > best_def_score:
                best_def_score = sc
                best_def = sym
        if best_def is None:
            return None
        weights[best_def] = weights.get(best_def, 0.0) + cash_fraction

    # Risk fraction -> equal split across the TOP_N risk assets by score (require all risk scores to exist).
    if risk_fraction > 0:
        risk_scores: dict[str, float] = {}
        for sym in RISK_UNIVERSE:
            sc = _score(series, sym, asof)
            if sc is None:
                return None
            risk_scores[sym] = sc
        held = sorted(RISK_UNIVERSE, key=lambda s: risk_scores[s], reverse=True)[:TOP_N]
        per = risk_fraction / len(held)
        for sym in held:
            weights[sym] = weights.get(sym, 0.0) + per

    return weights


@dataclass
class DaaResult:
    months: list[tuple[int, int]]          # the months the strategy was INVESTED (a return realized for each)
    weights: list[dict[str, float]]        # the target weights held entering each month (signal from the PRIOR end)
    net_returns: list[float]               # monthly NET-of-fee total return of the strategy
    gross_returns: list[float]
    spy_returns: list[float]               # buy-and-hold SPY total return over the SAME months (the benchmark)
    turnover: float                        # cumulative one-sided turnover over the window (a fee proxy)
    cash_fractions: list[float]            # the protective cash fraction (b/B) each month — the de-risk dial


def run_daa(
    series: dict[str, MonthlySeries],
    *,
    fee_bps_per_side: float = IBKR_ETF_BPS_PER_SIDE,
    start: tuple[int, int] | None = None,
    end: tuple[int, int] | None = None,
) -> DaaResult:
    """Run DAA month-by-month with no look-ahead: the target weights for month M are decided from data through month
    M-1's end (signal@M-1, trade@M); the portfolio return over M is the weighted blend of each held asset's realized
    return; a fee is charged on the one-sided turnover (sum of |w_M - w_{M-1}| / 2) at month M vs the prior month."""
    fee = fee_bps_per_side / 1e4
    all_months = series[BENCHMARK].months
    months_out: list[tuple[int, int]] = []
    weights_out: list[dict[str, float]] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    spy_r: list[float] = []
    cash_out: list[float] = []
    total_turnover = 0.0
    prev_w: dict[str, float] | None = None
    for m in all_months:
        if start is not None and m < start:
            continue
        if end is not None and m > end:
            continue
        signal_month = _add_months(m, -1)  # decide at the PRIOR month-end (PIT)
        w = _target_weights(series, signal_month)
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
        # Turnover fee: one-sided turnover = 0.5 * sum |w_M - w_{M-1}|. The first month pays one side on the full
        # deployment (turnover = 1.0). An unchanged book pays nothing.
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
        # Protective cash fraction this month = total weight parked in the defensive pool.
        cash_out.append(sum(w.get(sym, 0.0) for sym in DEFENSIVE))
        prev_w = w
    return DaaResult(months_out, weights_out, net_r, gross_r, spy_r, total_turnover, cash_out)


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


def first_investable_month(series: dict[str, MonthlySeries]) -> tuple[int, int]:
    """The first month every DAA series has BOTH a close and a `MAX_LOOKBACK`-months-prior close (so the 12m trailing
    return exists for all of them). Binds on the youngest ETF."""
    starts = []
    for sym in DAA_SERIES:
        s = series[sym]
        first = s.months[0]
        starts.append(_add_months(first, MAX_LOOKBACK + 1))
    return max(starts)


# --------------------------------------------------------------------------- report (the validation)


def _fmt_stats(tag: str, p: PerfStats) -> str:
    return (f"  {tag:<22} n={p.n_months:>3}m  tot={p.total_return:+.1%}  CAGR={p.cagr:+.2%}  "
            f"vol={p.ann_vol:.2%}  Sharpe={p.ann_sharpe:+.2f}  maxDD={p.max_dd:.1%}  win={p.win_rate:.0%}")


def current_weights() -> dict[str, float]:
    """The DAA target weights at the latest COMPLETED month-end (to be held next month). Empty if unavailable."""
    series = {sym: load_monthly(sym) for sym in DAA_SERIES}
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)
    w = _target_weights(series, last_complete)
    return w or {}


def validate() -> dict:
    """Run the full honest validation and print it. Returns a dict the arming path reuses for the backtest row."""
    series = {sym: load_monthly(sym) for sym in DAA_SERIES}
    start = first_investable_month(series)
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)  # drop the partial current month

    print("=" * 104)
    print("KELLER DEFENSIVE ASSET ALLOCATION (DAA, top-6, canary EEM/AGG) — DEPLOY-A-DOCUMENTED-STRATEGY validation")
    print("NOT the 0.95 in-sample Gate. Externally validated edge (Keller & Keuning 2018); here we check POSITIVE OOS")
    print("net of REAL IBKR fees + BEATS buy-and-hold SPY risk-adjusted, on our total-return (div-adjusted) monthly data.")
    print(f"RISK={RISK_UNIVERSE} | CANARY={CANARY} | DEFENSIVE={DEFENSIVE} | top-{TOP_N}")
    print(f"score=12*1m+4*3m+2*6m+12m | cash fraction = (#canary<=0)/{N_CANARY} into best defensive | "
          f"signal@month-end t, trade t+1 | window {start} -> {last_complete}")
    print("=" * 104)

    # ---- FULL SAMPLE at the central fee + fee sweep ----
    print("\n### FULL SAMPLE — DAA (net of IBKR fees) vs buy-and-hold SPY (total return)")
    full = run_daa(series, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=last_complete)
    daa_stats = _stats(full.net_returns)
    spy_stats = _stats(full.spy_returns)
    gross_stats = _stats(full.gross_returns)
    print(_fmt_stats("DAA (net, 1bps/side)", daa_stats))
    print(_fmt_stats("DAA (gross)", gross_stats))
    print(_fmt_stats("Buy & Hold SPY", spy_stats))
    avg_cash = statistics.fmean(full.cash_fractions) if full.cash_fractions else 0.0
    print(f"  one-sided turnover over window: {full.turnover:.1f}  (~{full.turnover / (daa_stats.n_months / 12):.1f}/yr) "
          f"|  avg protective cash fraction: {avg_cash:.0%} (the de-risk dial; higher turnover than GEM/PAA)")

    print("\n  Fee sensitivity (net Sharpe / net total / maxDD across IBKR fee assumptions):")
    for fee in FEE_SWEEP_BPS:
        r = run_daa(series, fee_bps_per_side=fee, start=start, end=last_complete)
        s = _stats(r.net_returns)
        print(f"    {fee:>3.0f} bps/side  Sharpe={s.ann_sharpe:+.2f}  tot={s.total_return:+.1%}  "
              f"CAGR={s.cagr:+.2%}  maxDD={s.max_dd:.1%}")

    # ---- IS / OOS purged temporal split ----
    # Split the window in half by time. PURGE: the OOS leg starts `MAX_LOOKBACK` months AFTER the IS leg ends so no
    # OOS signal is computed from any IS-era bar (the 12m trailing window can't straddle the boundary).
    n_total = daa_stats.n_months
    is_end = full.months[n_total // 2]
    oos_start = _add_months(is_end, MAX_LOOKBACK)
    print(f"\n### IS / OOS PURGED SPLIT — IS {start}->{is_end} | purge {MAX_LOOKBACK}m | OOS {oos_start}->{last_complete}")
    is_run = run_daa(series, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=is_end)
    oos_run = run_daa(series, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=oos_start, end=last_complete)
    is_daa, is_spy = _stats(is_run.net_returns), _stats(is_run.spy_returns)
    oos_daa, oos_spy = _stats(oos_run.net_returns), _stats(oos_run.spy_returns)
    print("  [IS]")
    print(_fmt_stats("DAA (net)", is_daa))
    print(_fmt_stats("Buy & Hold SPY", is_spy))
    print("  [OOS]  <-- the deployment check")
    print(_fmt_stats("DAA (net)", oos_daa))
    print(_fmt_stats("Buy & Hold SPY", oos_spy))

    # ---- SUBPERIOD ROBUSTNESS — DAA's documented edge is CRISIS AVOIDANCE via canary breadth ----
    print("\n### SUBPERIOD ROBUSTNESS — DAA net total vs B&H SPY total over each regime (the edge is crisis avoidance)")
    subperiods = [
        ("2008 GFC crash    (01/2008-02/2009)", (2008, 1), (2009, 2)),
        ("recovery+QE bull  (03/2009-12/2019)", (2009, 3), (2019, 12)),
        ("COVID crash       (02/2020-04/2020)", (2020, 2), (2020, 4)),
        ("2021 bull         (01/2021-12/2021)", (2021, 1), (2021, 12)),
        ("2022 bear         (01/2022-12/2022)", (2022, 1), (2022, 12)),
        ("post-2022 bull    (01/2023-now)     ", (2023, 1), last_complete),
    ]
    for label, s0, s1 in subperiods:
        if s0 < start:
            continue
        gr = run_daa(series, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=s0, end=s1)
        g, sp = _stats(gr.net_returns), _stats(gr.spy_returns)
        edge = g.total_return - sp.total_return
        print(f"  {label}  DAA={g.total_return:+6.1%}  SPY={sp.total_return:+6.1%}  edge={edge:+6.1%}  "
              f"(DAA maxDD {g.max_dd:.0%} vs SPY {sp.max_dd:.0%})")

    # ---- VERDICT (deployment bar — honest, NOT pass-tuned) ----
    # The prompt's bar: positive OOS net of fees, AND beats B&H SPY on "higher Sharpe AND/OR materially lower maxDD",
    # robust across subperiods, on the real holdout. DAA's documented edge is crisis avoidance via the canary breadth
    # signal -> a materially lower maxDD AND (because it sidesteps the worst equity drawdowns) typically a higher Sharpe.
    # We require, applying the prompt's exact AND/OR bar to the REAL OOS leg + full cycle:
    #   (1) OOS POSITIVE net of real fees (the edge survives out of sample), AND
    #   (2) OOS risk-adjusted beat: OOS Sharpe >= SPY's OOS Sharpe OR OOS maxDD materially lower, AND
    #   (3) FULL-cycle risk-adjusted beat: higher Sharpe AND/OR materially lower maxDD vs B&H SPY.
    # No knob is tuned to pass; the fee sweep + subperiod table are disclosed so the verdict is not knife-edge.
    MATERIAL_DD_REDUCTION = 0.75  # "materially lower" = <= 75% of SPY's maxDD
    oos_positive = oos_daa.total_return > 0
    oos_sharpe_beat = oos_daa.ann_sharpe >= oos_spy.ann_sharpe
    oos_dd_beat = oos_daa.max_dd <= oos_spy.max_dd * MATERIAL_DD_REDUCTION
    oos_riskadj_beat = oos_sharpe_beat or oos_dd_beat
    full_sharpe_beat = daa_stats.ann_sharpe >= spy_stats.ann_sharpe
    full_dd_beat = daa_stats.max_dd <= spy_stats.max_dd * MATERIAL_DD_REDUCTION
    full_riskadj_beat = full_sharpe_beat or full_dd_beat
    deployable = oos_positive and oos_riskadj_beat and full_riskadj_beat

    print("\n" + "=" * 104)
    print("VERDICT (deployment bar — NOT the 0.95 in-sample Gate; the edge is crisis avoidance via canary breadth):")
    print(f"  (1) OOS net-of-fee POSITIVE?                       {oos_positive}  (OOS net total {oos_daa.total_return:+.1%})")
    print(f"  (2) OOS risk-adjusted beat vs B&H SPY?             {oos_riskadj_beat}  "
          f"(Sharpe {oos_daa.ann_sharpe:+.2f} vs {oos_spy.ann_sharpe:+.2f} [{oos_sharpe_beat}]; "
          f"maxDD {oos_daa.max_dd:.1%} vs {oos_spy.max_dd:.1%} [{oos_dd_beat}])")
    print(f"  (3) FULL-cycle risk-adjusted beat vs B&H SPY?      {full_riskadj_beat}  "
          f"(Sharpe {daa_stats.ann_sharpe:+.2f} vs {spy_stats.ann_sharpe:+.2f} [{full_sharpe_beat}]; "
          f"maxDD {daa_stats.max_dd:.1%} vs {spy_stats.max_dd:.1%} [{full_dd_beat}])")
    print(f"  ==> {'DEPLOYABLE — arm the live paper' if deployable else 'NOT deployable on our data'}")
    print("  HONEST EXPECTATION: a crisis-avoidance portfolio — the canary breadth signal (EEM/AGG) scales the book")
    print("  PROGRESSIVELY into short Treasuries before equity drawdowns deepen, while holding a diversified momentum")
    print("  basket when risk is on. Higher turnover than GEM/PAA means the fee leg matters (see the sweep). That")
    print("  asymmetry IS the documented edge.")
    print("=" * 104)

    cur = _target_weights(series, last_complete) or {}
    held_now = sorted(((s, w) for s, w in cur.items() if w > 0), key=lambda kv: kv[1], reverse=True)
    cash_now = sum(cur.get(sym, 0.0) for sym in DEFENSIVE)
    print(f"\nCURRENT DAA target weights (decided at {last_complete} month-end, to hold next month):")
    for s, w in held_now:
        print(f"  {s}: {w:.0%}")
    print(f"  -> protective cash fraction (best of {DEFENSIVE}): {cash_now:.0%}")

    return {
        "deployable": deployable,
        "current_weights": cur,
        "full": daa_stats,
        "full_spy": spy_stats,
        "oos": oos_daa,
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
