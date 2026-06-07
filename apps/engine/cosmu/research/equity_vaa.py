# intent: DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). Wouter Keller & Jan
# Willem Keuning's VIGILANT ASSET ALLOCATION — AGGRESSIVE (VAA-G4), from "Breadth Momentum and Vigilant Asset
# Allocation" (2017). Externally validated, published, widely replicated. Like GEM it is a documented monthly
# cross-asset rotation; it does NOT need our in-sample Gate to "discover" it (the Gate is an overfitting guard for
# NOVEL mined edges). The appropriate validators are (a) the external literature, (b) a positive OOS-net-of-fees check
# on OUR total-return data, (c) the LIVE forward-test. This module does (b) and (its sibling arm) does (c). It NEVER
# touches / lowers the 0.95 Gate.
#
# THE RULE (monthly; signal at month-end t from completed-month closes, trade t+1 — NO look-ahead):
#   Universe:
#     OFFENSIVE = {SPY (US eq), EFA (intl dev eq), EEM (EM eq), AGG (US agg bonds)}
#     CANARY    = {EEM, AGG}                              # the "breadth" crash detectors
#     DEFENSIVE = {LQD (IG corp bonds), IEF (7-10y UST), SHY (1-3y UST)}
#   Score of an asset = 12*r1m + 4*r3m + 2*r6m + 1*r12m   (trailing TOTAL-return momentum, "13612W" weighting).
#   1. Compute the score of BOTH canaries (EEM, AGG).
#   2. If ANY canary score < 0  -> RISK-OFF: hold the single best-scoring DEFENSIVE asset (max score of LQD/IEF/SHY).
#   3. Else                      -> RISK-ON : hold the single best-scoring OFFENSIVE asset (max score of the 4).
#   (This is "VAA-G4 aggressive": breadth = number of bad canaries; with B=1 protection threshold, a SINGLE negative
#    canary flips the whole book defensive. Aggressive = top-1 offensive holding, not a spread.)
#
# DATA: TOTAL-RETURN (adjusted-close) MONTHLY bars from the equities cache `*_tr.json`
#   (equity_total_return_backfill.py) — dividends are most of a bond ETF's return, so a raw-price rank is biased. The
#   binding (youngest) series are EEM (lists 2003-05) and AGG (2003-10); with a 12m lookback the first signal is
#   ~2004-10 and the first held month ~2004-11.
#
# FEES: REAL IBKR all-in on liquid ETFs ~1 bp/side (0.5 commission + ~0.5 spread/impact). A side is paid only when the
#   held instrument CHANGES month-to-month (VAA holds one ETF at a time; an unchanged hold pays nothing — but note VAA
#   is HIGHER turnover than GEM, so the fee leg matters more). Sweep {1,2,3,5} bps/side so the verdict is not
#   knife-edge fee-dependent.
#
# VALIDATION (the DEPLOYMENT bar, not the 0.95 Gate): positive OOS net of real fees, BEATS buy-and-hold SPY
#   risk-adjusted (higher Sharpe AND/OR materially lower maxDD), robust across an IS/OOS purged temporal split. VAA's
#   DOCUMENTED edge is CRISIS AVOIDANCE — the canary breadth signal yanks it to short Treasuries before equity
#   drawdowns deepen, so the honest expectation is a markedly lower maxDD with a higher full-cycle Sharpe than SPY.
#
# Propose/measure-only — this module moves no money; the sibling `equity_vaa_arm` arms a SIM forward-test (live OFF).

from __future__ import annotations

import json
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CACHE = Path("/Users/device/cosmu/.cosmu/market_data/equities")

# VAA-G4 aggressive universe.
OFFENSIVE = ["SPY", "EFA", "EEM", "AGG"]
CANARY = ["EEM", "AGG"]
DEFENSIVE = ["LQD", "IEF", "SHY"]
VAA_SERIES = sorted(set(OFFENSIVE + CANARY + DEFENSIVE))  # all series the strategy needs loaded
BENCHMARK = "SPY"  # buy-and-hold benchmark for the deployment bar

# 13612W momentum weighting: 12*1m + 4*3m + 2*6m + 1*12m (Keller 2017). Lookbacks in months -> weight.
SCORE_WEIGHTS: list[tuple[int, float]] = [(1, 12.0), (3, 4.0), (6, 2.0), (12, 1.0)]
MAX_LOOKBACK = 12  # longest trailing window used (binds the first investable month + the IS/OOS purge gap)

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


# --------------------------------------------------------------------------- backtest


@dataclass
class VaaResult:
    months: list[tuple[int, int]]      # the months the strategy was INVESTED (a return realized for each)
    holdings: list[str]                # the ETF held entering each month (signal from the PRIOR month-end)
    risk_off: list[bool]               # whether the canary breadth signal forced defensive that month
    net_returns: list[float]           # monthly NET-of-fee total return of the strategy
    gross_returns: list[float]
    spy_returns: list[float]           # buy-and-hold SPY total return over the SAME months (the benchmark)
    switches: int                      # number of months the holding changed (a round-trip = 2 sides of fee)


def _trailing_return(s: MonthlySeries, asof: tuple[int, int], lookback: int) -> float | None:
    """Trailing `lookback`-month TOTAL return of `s` as of month `asof` (close[asof]/close[asof-lookback] - 1).
    None if either endpoint is missing — the caller treats the asset's score as unavailable that month (NO synthetic
    fill, NO look-ahead: `asof` is a completed month-end)."""
    past = _add_months(asof, -lookback)
    c_now = s.close.get(asof)
    c_past = s.close.get(past)
    if c_now is None or c_past is None or c_past <= 0:
        return None
    return c_now / c_past - 1.0


def _score(series: dict[str, MonthlySeries], symbol: str, asof: tuple[int, int]) -> float | None:
    """13612W momentum score of `symbol` at month-end `asof`: 12*r1 + 4*r3 + 2*r6 + 1*r12. None if ANY of the four
    trailing returns is unavailable (we never fabricate a partial score — fail closed so a half-history asset can't
    be ranked top)."""
    s = series[symbol]
    total = 0.0
    for lb, w in SCORE_WEIGHTS:
        r = _trailing_return(s, asof, lb)
        if r is None:
            return None
        total += w * r
    return total


def _signal(series: dict[str, MonthlySeries], asof: tuple[int, int]) -> tuple[str | None, bool]:
    """The VAA holding decided at month-end `asof` (to be HELD the following month). Returns (symbol, risk_off).
    risk_off=True when any canary score < 0 (breadth crash detector trips). Returns (None, *) if any required score
    is unavailable that month (the whole decision is dropped — no partial book)."""
    # Canary breadth: if ANY canary score < 0, go fully defensive.
    any_canary_negative = False
    for c in CANARY:
        sc = _score(series, c, asof)
        if sc is None:
            return None, False
        if sc < 0:
            any_canary_negative = True
    pool = DEFENSIVE if any_canary_negative else OFFENSIVE
    best_sym: str | None = None
    best_score = -math.inf
    for sym in pool:
        sc = _score(series, sym, asof)
        if sc is None:
            return None, any_canary_negative
        if sc > best_score:
            best_score = sc
            best_sym = sym
    return best_sym, any_canary_negative


def _realized_return(s: MonthlySeries, month: tuple[int, int]) -> float | None:
    """Total return of holding `s` THROUGH `month` = close[month]/close[month-1] - 1. None if either close missing."""
    prev = _add_months(month, -1)
    c = s.close.get(month)
    c_prev = s.close.get(prev)
    if c is None or c_prev is None or c_prev <= 0:
        return None
    return c / c_prev - 1.0


def run_vaa(
    series: dict[str, MonthlySeries],
    *,
    fee_bps_per_side: float = IBKR_ETF_BPS_PER_SIDE,
    start: tuple[int, int] | None = None,
    end: tuple[int, int] | None = None,
) -> VaaResult:
    """Run VAA-G4 aggressive month-by-month with no look-ahead: the holding for month M is decided from data through
    month M-1's end, the return is realized over month M, and a fee is charged ONLY when the holding changes from the
    prior month (one side per leg of a switch; a switch from X to Y pays one side to sell X + one to buy Y = 2 sides)."""
    fee = fee_bps_per_side / 1e4
    all_months = series[BENCHMARK].months
    months_out: list[tuple[int, int]] = []
    holdings: list[str] = []
    risk_off_flags: list[bool] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    spy_r: list[float] = []
    switches = 0
    prev_hold: str | None = None
    for m in all_months:
        if start is not None and m < start:
            continue
        if end is not None and m > end:
            continue
        signal_month = _add_months(m, -1)  # decide at the PRIOR month-end (PIT)
        hold, risk_off = _signal(series, signal_month)
        if hold is None:
            continue
        r = _realized_return(series[hold], m)
        spy = _realized_return(series[BENCHMARK], m)
        if r is None or spy is None:
            continue
        gross = r
        # Fee: a CHANGE of holding pays two sides (sell old + buy new). First investment (prev None) pays one side
        # (the initial buy). An unchanged hold pays nothing.
        if prev_hold is None:
            cost = fee
        elif hold != prev_hold:
            cost = 2 * fee
            switches += 1
        else:
            cost = 0.0
        net = gross - cost
        months_out.append(m)
        holdings.append(hold)
        risk_off_flags.append(risk_off)
        gross_r.append(gross)
        net_r.append(net)
        spy_r.append(spy)
        prev_hold = hold
    return VaaResult(months_out, holdings, risk_off_flags, net_r, gross_r, spy_r, switches)


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
    """The first month every VAA series has BOTH a close and a `MAX_LOOKBACK`-months-prior close (so the 12m trailing
    return exists for all of them). Binds on the youngest ETF (EEM 2003-05 / AGG 2003-10) -> first signal ~2004-10,
    first held month ~2004-11."""
    starts = []
    for sym in VAA_SERIES:
        s = series[sym]
        first = s.months[0]
        starts.append(_add_months(first, MAX_LOOKBACK + 1))
    return max(starts)


# --------------------------------------------------------------------------- report (the validation)


def _fmt_stats(tag: str, p: PerfStats) -> str:
    return (f"  {tag:<22} n={p.n_months:>3}m  tot={p.total_return:+.1%}  CAGR={p.cagr:+.2%}  "
            f"vol={p.ann_vol:.2%}  Sharpe={p.ann_sharpe:+.2f}  maxDD={p.max_dd:.1%}  win={p.win_rate:.0%}")


def validate() -> dict:
    """Run the full honest validation and print it. Returns a dict the arming path reuses for the backtest row."""
    series = {sym: load_monthly(sym) for sym in VAA_SERIES}
    start = first_investable_month(series)
    # Drop the partial CURRENT month (its close is a mid-month snapshot, not a completed month-end return).
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)

    print("=" * 104)
    print("KELLER VIGILANT ASSET ALLOCATION — AGGRESSIVE (VAA-G4) — DEPLOY-A-DOCUMENTED-STRATEGY validation")
    print("NOT the 0.95 in-sample Gate. Externally validated edge (Keller & Keuning 2017); here we check POSITIVE OOS")
    print("net of REAL IBKR fees + BEATS buy-and-hold SPY risk-adjusted, on our total-return (div-adjusted) monthly data.")
    print(f"OFFENSIVE={OFFENSIVE} CANARY={CANARY} DEFENSIVE={DEFENSIVE}")
    print(f"score=12*1m+4*3m+2*6m+12m | ANY canary<0 -> best defensive, else best offensive | "
          f"signal@month-end t, trade t+1 | window {start} -> {last_complete}")
    print("=" * 104)

    # ---- FULL SAMPLE at the central fee + fee sweep ----
    print("\n### FULL SAMPLE — strategy (net of IBKR fees) vs buy-and-hold SPY (total return)")
    full = run_vaa(series, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=last_complete)
    vaa_stats = _stats(full.net_returns)
    spy_stats = _stats(full.spy_returns)
    gross_stats = _stats(full.gross_returns)
    print(_fmt_stats("VAA (net, 1bps/side)", vaa_stats))
    print(_fmt_stats("VAA (gross)", gross_stats))
    print(_fmt_stats("Buy & Hold SPY", spy_stats))
    months_off = sum(1 for f in full.risk_off if f)
    print(f"  switches over window: {full.switches}  (~{full.switches / (vaa_stats.n_months / 12):.1f}/yr — higher "
          f"turnover than GEM)   |   risk-OFF months: {months_off}/{vaa_stats.n_months} "
          f"({months_off / vaa_stats.n_months:.0%} defensive)")

    print("\n  Fee sensitivity (net Sharpe / net total / maxDD across IBKR fee assumptions):")
    for fee in FEE_SWEEP_BPS:
        r = run_vaa(series, fee_bps_per_side=fee, start=start, end=last_complete)
        s = _stats(r.net_returns)
        print(f"    {fee:>3.0f} bps/side  Sharpe={s.ann_sharpe:+.2f}  tot={s.total_return:+.1%}  "
              f"CAGR={s.cagr:+.2%}  maxDD={s.max_dd:.1%}")

    # ---- IS / OOS purged temporal split ----
    # Split the window in half by time. PURGE: the OOS leg starts `MAX_LOOKBACK` months AFTER the IS leg ends so no
    # OOS signal is computed from any IS-era bar (the 12m trailing window can't straddle the boundary).
    n_total = vaa_stats.n_months
    mid_idx = full.months[n_total // 2]
    is_end = mid_idx
    oos_start = _add_months(is_end, MAX_LOOKBACK)  # embargo/purge gap
    print(f"\n### IS / OOS PURGED SPLIT — IS {start}->{is_end} | purge {MAX_LOOKBACK}m | OOS {oos_start}->{last_complete}")
    is_run = run_vaa(series, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=is_end)
    oos_run = run_vaa(series, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=oos_start, end=last_complete)
    is_vaa, is_spy = _stats(is_run.net_returns), _stats(is_run.spy_returns)
    oos_vaa, oos_spy = _stats(oos_run.net_returns), _stats(oos_run.spy_returns)
    print("  [IS]")
    print(_fmt_stats("VAA (net)", is_vaa))
    print(_fmt_stats("Buy & Hold SPY", is_spy))
    print("  [OOS]  <-- the deployment check")
    print(_fmt_stats("VAA (net)", oos_vaa))
    print(_fmt_stats("Buy & Hold SPY", oos_spy))

    # ---- SUBPERIOD ROBUSTNESS — VAA's documented edge is CRISIS AVOIDANCE; show it across the major regimes ----
    print("\n### SUBPERIOD ROBUSTNESS — VAA net total vs B&H SPY total over each regime (the edge is crisis avoidance)")
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
        gr = run_vaa(series, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=s0, end=s1)
        g, sp = _stats(gr.net_returns), _stats(gr.spy_returns)
        edge = g.total_return - sp.total_return
        print(f"  {label}  VAA={g.total_return:+6.1%}  SPY={sp.total_return:+6.1%}  edge={edge:+6.1%}  "
              f"(VAA maxDD {g.max_dd:.0%} vs SPY {sp.max_dd:.0%})")

    # ---- VERDICT (deployment bar — honest, NOT pass-tuned) ----
    # The prompt's bar is: positive OOS net of fees, AND beats B&H SPY on "higher Sharpe AND/OR materially lower
    # maxDD", robust across subperiods, on the real holdout. VAA's documented edge is crisis avoidance -> it should
    # show BOTH a materially lower maxDD AND (because it sidesteps the worst equity drawdowns with a defensive sleeve)
    # a higher full-cycle Sharpe. We require:
    #   (1) OOS POSITIVE net of real fees (the edge survives out of sample), AND
    #   (2) beats SPY on the AND/OR bar: higher full-cycle Sharpe OR materially (<=75% of SPY) lower maxDD, AND
    #   (3) OOS not catastrophically worse than SPY (OOS maxDD <= SPY's OOS maxDD — the de-risking didn't backfire).
    # No knob is tuned to pass; the fee sweep + subperiod table are disclosed so the verdict is not knife-edge.
    MATERIAL_DD_REDUCTION = 0.75  # "materially lower" = <= 75% of SPY's maxDD
    oos_positive = oos_vaa.total_return > 0
    full_lower_dd = vaa_stats.max_dd <= spy_stats.max_dd * MATERIAL_DD_REDUCTION
    full_higher_sharpe = vaa_stats.ann_sharpe > spy_stats.ann_sharpe
    beats_risk_adjusted = full_higher_sharpe or full_lower_dd
    oos_dd_ok = oos_vaa.max_dd <= oos_spy.max_dd + 1e-9
    deployable = oos_positive and beats_risk_adjusted and oos_dd_ok
    print("\n" + "=" * 104)
    print("VERDICT (deployment bar — NOT the 0.95 in-sample Gate; the edge is crisis avoidance via canary breadth):")
    print(f"  (1) OOS net-of-fee POSITIVE?                       {oos_positive}  (OOS net total {oos_vaa.total_return:+.1%})")
    print(f"  (2) beats B&H SPY risk-adjusted (Sharpe OR maxDD)? {beats_risk_adjusted}")
    print(f"        - higher full-cycle Sharpe?                  {full_higher_sharpe}  "
          f"(VAA {vaa_stats.ann_sharpe:+.2f} vs SPY {spy_stats.ann_sharpe:+.2f})")
    print(f"        - materially lower full-cycle maxDD?         {full_lower_dd}  "
          f"(VAA {vaa_stats.max_dd:.1%} vs SPY {spy_stats.max_dd:.1%}, "
          f"~{vaa_stats.max_dd / spy_stats.max_dd:.0%} of SPY)")
    print(f"  (3) OOS maxDD not worse than SPY OOS?              {oos_dd_ok}  "
          f"(VAA {oos_vaa.max_dd:.1%} vs SPY {oos_spy.max_dd:.1%})")
    print(f"  ==> {'DEPLOYABLE — arm the live forward-test' if deployable else 'NOT deployable on our data'}")
    print("  HONEST EXPECTATION: a crisis-avoidance strategy — the canary breadth signal (EEM/AGG) flips the book to")
    print("  short Treasuries before equity drawdowns deepen. It trades some bull upside for a much shallower maxDD;")
    print("  higher turnover than GEM means the fee leg matters (see the sweep). That asymmetry IS the documented edge.")
    print("=" * 104)

    current_signal, current_risk_off = _signal(series, last_complete)
    print(f"\nCURRENT VAA signal (decided at {last_complete} month-end, to hold next month): HOLD {current_signal} "
          f"({'RISK-OFF / defensive' if current_risk_off else 'RISK-ON / offensive'})")

    return {
        "deployable": deployable,
        "current_signal": current_signal,
        "current_risk_off": current_risk_off,
        "full": vaa_stats,
        "full_spy": spy_stats,
        "oos": oos_vaa,
        "oos_spy": oos_spy,
        "switches": full.switches,
        "window": (start, last_complete),
        "result": full,
    }


def main(argv: list[str] | None = None) -> int:
    validate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
