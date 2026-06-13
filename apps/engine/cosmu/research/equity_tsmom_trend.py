# intent: DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). TIME-SERIES MOMENTUM /
# absolute trend-following on a diversified ETF set is one of the most-replicated published anomalies (Moskowitz-Ooi-
# Pedersen "Time Series Momentum" 2012; Hurst-Ooi-Pedersen "A Century of Evidence on Trend-Following" 2017;
# Faber "A Quantitative Approach to Tactical Asset Allocation" 2007 — the 10-month/12-month timing rule). The edge is
# external + decades-deep, so it does NOT need our in-sample Gate (which is an OVERFITTING guard for NOVEL mined
# edges). The validators here are: (a) the external literature, (b) a positive OOS-net-of-fees check on OUR data that
# BEATS buy-and-hold SPY risk-adjusted, on the REAL purged+embargoed holdout, (c) the LIVE paper. This module
# does (b) and arms (c). It NEVER touches / lowers the 0.95 Gate.
#
# THE RULE (monthly, signal at month-end t, trade t+1 — NO look-ahead):
#   For a diversified ETF set {SPY, EFA, AGG, GLD, TLT}, independently per asset:
#     hold it LONG for the next month IF its trailing-12m total return > 0 (absolute/time-series momentum, trend up),
#     ELSE hold CASH for that asset's sleeve.
#   EQUAL-WEIGHT the longs (1/N of capital each, where N = number of assets in the set). The sleeves whose asset is in
#   cash earn the cash return (BIL T-bill total return where available, else 0% — conservative, never look-ahead).
#   Rebalanced monthly. This is the canonical diversified time-series trend-follower: each asset is timed on its own
#   trend; diversification across equities (SPY/EFA), bonds (AGG/TLT) and gold (GLD) smooths the equity curve and the
#   absolute-momentum filter side-steps the deep drawdowns of any single sleeve.
#
# DATA: TOTAL-RETURN (adjusted-close) MONTHLY bars from the equities cache `*_tr.json` — dividends/coupons are most of
#   a bond/ETF's return, so a raw-price trend rank is biased. Window starts the first month all five assets have >=12m
#   history (GLD lists 2004-12 -> first signal ~2005-12, first held month ~2006-01).
#
# FEES: REAL IBKR all-in on liquid ETFs ~1 bp/side (0.5 commission + ~0.5 spread/impact). A side is paid per asset only
#   when THAT asset's weight changes month-to-month (long->cash or cash->long flips one side of turnover on 1/N of
#   capital). Sweep {1,2,3,5} bps/side so the verdict is not knife-edge fee-dependent.
#
# VALIDATION (the DEPLOYMENT bar, not the 0.95 Gate): positive OOS net of real fees on the REAL purged+embargoed
#   holdout, BEATS buy-and-hold SPY risk-adjusted (higher Sharpe AND/OR materially lower maxDD), robust across
#   subperiods. An honest FAIL is a valid outcome — we never tune to pass.

from __future__ import annotations

import math
import statistics
import sys
from dataclasses import dataclass

from cosmu.research.equity_dual_momentum import (
    MonthlySeries,
    _add_months,
    load_monthly,
)
from cosmu.research.equity_holdout import purged_embargoed_split

# The diversified ETF set this strategy times (each on its own trend). Equities (SPY/EFA), bonds (AGG/TLT), gold (GLD).
ASSETS = ["SPY", "EFA", "AGG", "GLD", "TLT"]
BENCH = "SPY"          # buy-and-hold benchmark (the prompt's bar: beat B&H-SPY risk-adjusted)
CASH = "BIL"           # T-bill total-return proxy for the cash sleeve (lists 2007-06; 0% before — conservative)
ALL_SERIES = ASSETS + [CASH]

LOOKBACK_MONTHS = 12   # trailing absolute-momentum window (MOP 2012 / Faber 10-12m timing)
IBKR_ETF_BPS_PER_SIDE = 1.0
FEE_SWEEP_BPS = [1.0, 2.0, 3.0, 5.0]
MONTHS_PER_YEAR = 12

# Embargo for the purged+embargoed holdout: the 12m formation window must not straddle the IS/holdout boundary, so we
# discard >= LOOKBACK observations between the in-sample slice and the holdout tail.
HOLDOUT_FRAC = 0.25
HOLDOUT_EMBARGO = LOOKBACK_MONTHS


# --------------------------------------------------------------------------- backtest


@dataclass
class TsmomResult:
    months: list[tuple[int, int]]      # the months the strategy was invested (a return realized for each)
    net_returns: list[float]           # monthly NET-of-fee portfolio total return
    gross_returns: list[float]
    bench_returns: list[float]         # buy-and-hold SPY total return over the SAME months
    n_longs: list[int]                 # number of assets held long each month (diagnostic)
    side_count: int                    # total per-asset fee sides paid over the window (turnover diagnostic)


def _trailing_return(s: MonthlySeries, asof: tuple[int, int], lookback: int) -> float | None:
    """Trailing `lookback`-month TOTAL return of `s` as of completed month `asof`. None if either endpoint missing
    (NO synthetic fill, NO look-ahead — `asof` is a completed month-end)."""
    past = _add_months(asof, -lookback)
    c_now = s.close.get(asof)
    c_past = s.close.get(past)
    if c_now is None or c_past is None or c_past <= 0:
        return None
    return c_now / c_past - 1.0


def _realized_return(s: MonthlySeries, month: tuple[int, int]) -> float | None:
    """Total return of holding `s` THROUGH `month` = close[month]/close[month-1] - 1. None if either close missing."""
    prev = _add_months(month, -1)
    c = s.close.get(month)
    c_prev = s.close.get(prev)
    if c is None or c_prev is None or c_prev <= 0:
        return None
    return c / c_prev - 1.0


def _cash_return(series: dict[str, MonthlySeries], month: tuple[int, int]) -> float:
    """Cash-sleeve return for `month`: BIL T-bill total return where available, else 0.0. Using 0% before BIL lists
    (2007-06) is CONSERVATIVE — it understates the strategy (cash actually earned ~4-5% in 2005-07) and never looks
    ahead. The benchmark (B&H SPY) gets no such cash leg, so this can only make the comparison HARDER for us."""
    r = _realized_return(series[CASH], month)
    return r if r is not None else 0.0


def run_tsmom(
    series: dict[str, MonthlySeries],
    *,
    lookback: int = LOOKBACK_MONTHS,
    fee_bps_per_side: float = IBKR_ETF_BPS_PER_SIDE,
    start: tuple[int, int] | None = None,
    end: tuple[int, int] | None = None,
) -> TsmomResult:
    """Run the diversified time-series trend-follower month-by-month with NO look-ahead.

    For each invested month M: each asset's weight is decided from data through month M-1's end (trailing-12m>0 -> 1/N
    long, else its 1/N sleeve sits in cash), the return is realized over month M, and a fee is charged PER ASSET only
    when its long/cash state flips vs the prior month (one side of turnover on its 1/N of capital). Equal weight = 1/N
    over the FULL asset set (cash sleeves are a real allocation decision, so de-risking shrinks gross exposure rather
    than concentrating into fewer names — this is the honest absolute-momentum overlay, not a top-K selection)."""
    fee = fee_bps_per_side / 1e4
    n_assets = len(ASSETS)
    w = 1.0 / n_assets
    all_months = series[BENCH].months
    months_out: list[tuple[int, int]] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    bench_r: list[float] = []
    n_longs: list[int] = []
    side_count = 0
    prev_state: dict[str, bool] | None = None  # asset -> was it long last month
    for m in all_months:
        if start is not None and m < start:
            continue
        if end is not None and m > end:
            continue
        signal_month = _add_months(m, -1)  # decide at the PRIOR month-end (PIT)
        # Build this month's long/cash state per asset; require ALL trailing signals + realized returns to exist.
        state: dict[str, bool] = {}
        realized: dict[str, float] = {}
        ok = True
        for a in ASSETS:
            tr = _trailing_return(series[a], signal_month, lookback)
            rr = _realized_return(series[a], m)
            if tr is None or rr is None:
                ok = False
                break
            state[a] = tr > 0.0
            realized[a] = rr
        if not ok:
            continue
        bench = _realized_return(series[BENCH], m)
        if bench is None:
            continue
        cash_r = _cash_return(series, m)
        # Gross portfolio return: each 1/N sleeve earns its asset's return if long, else the cash return.
        gross = 0.0
        for a in ASSETS:
            gross += w * (realized[a] if state[a] else cash_r)
        # Fee: per-asset, a flip of long/cash state pays one side of turnover on that sleeve's 1/N weight. First month
        # (prev None): every sleeve that goes LONG pays its initial buy side (cash sleeves pay nothing).
        cost = 0.0
        if prev_state is None:
            for a in ASSETS:
                if state[a]:
                    cost += w * fee
                    side_count += 1
        else:
            for a in ASSETS:
                if state[a] != prev_state[a]:
                    cost += w * fee
                    side_count += 1
        net = gross - cost
        months_out.append(m)
        gross_r.append(gross)
        net_r.append(net)
        bench_r.append(bench)
        n_longs.append(sum(1 for a in ASSETS if state[a]))
        prev_state = state
    return TsmomResult(months_out, net_r, gross_r, bench_r, n_longs, side_count)


# --------------------------------------------------------------------------- metrics


@dataclass
class PerfStats:
    n_months: int
    total_return: float
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


def first_investable_month(series: dict[str, MonthlySeries], lookback: int) -> tuple[int, int]:
    """First month every timed asset has BOTH a close and a `lookback`-months-prior close (so a trailing return exists
    for all of them). Binds on the youngest asset (GLD, 2004-12) -> first signal ~2005-12, first held ~2006-01."""
    starts = []
    for sym in ASSETS:
        s = series[sym]
        starts.append(_add_months(s.months[0], lookback + 1))
    return max(starts)


def _fmt_stats(tag: str, p: PerfStats) -> str:
    return (f"  {tag:<24} n={p.n_months:>3}m  tot={p.total_return:+.1%}  CAGR={p.cagr:+.2%}  "
            f"vol={p.ann_vol:.2%}  Sharpe={p.ann_sharpe:+.2f}  maxDD={p.max_dd:.1%}  win={p.win_rate:.0%}")


# --------------------------------------------------------------------------- the current signal


def current_signal(series: dict[str, MonthlySeries], asof: tuple[int, int],
                   lookback: int = LOOKBACK_MONTHS) -> dict[str, bool]:
    """The long/cash state per asset decided at month-end `asof` (to hold next month)."""
    out: dict[str, bool] = {}
    for a in ASSETS:
        tr = _trailing_return(series[a], asof, lookback)
        out[a] = bool(tr is not None and tr > 0.0)
    return out


# --------------------------------------------------------------------------- report (the validation)


def validate(lookback: int = LOOKBACK_MONTHS) -> dict:
    """Run the full honest validation against the REAL purged+embargoed holdout and print it. Returns a dict the
    arming path reuses for the backtest row. An honest FAIL is a valid outcome (deployable=False)."""
    series = {sym: load_monthly(sym) for sym in ALL_SERIES}
    start = first_investable_month(series, lookback)
    from datetime import UTC, datetime
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)

    print("=" * 104)
    print("TIME-SERIES MOMENTUM (diversified ETF trend-following) — DEPLOY-A-DOCUMENTED-STRATEGY validation")
    print("NOT the 0.95 in-sample Gate. Externally validated edge (MOP 2012 / Hurst-Ooi-Pedersen 2017 / Faber 2007);")
    print("here we check POSITIVE OOS net of REAL IBKR fees on the REAL purged+embargoed holdout + BEATS B&H SPY")
    print("risk-adjusted, on total-return (dividend-adjusted) monthly data.")
    print(f"Universe: {ASSETS} (each timed on its own 12m trend) | cash sleeve={CASH} | "
          f"signal@month-end t, trade t+1 | window {start} -> {last_complete}")
    print("=" * 104)

    # ---- FULL SAMPLE at the central fee + fee sweep ----
    print("\n### FULL SAMPLE — strategy (net of IBKR fees) vs buy-and-hold SPY (total return)")
    full = run_tsmom(series, lookback=lookback, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=last_complete)
    tsm_stats = _stats(full.net_returns)
    bench_stats = _stats(full.bench_returns)
    gross_stats = _stats(full.gross_returns)
    print(_fmt_stats("TSMOM (net, 1bps/side)", tsm_stats))
    print(_fmt_stats("TSMOM (gross)", gross_stats))
    print(_fmt_stats("Buy & Hold SPY", bench_stats))
    avg_long = statistics.fmean(full.n_longs) if full.n_longs else 0.0
    print(f"  avg #assets long: {avg_long:.2f}/{len(ASSETS)}  |  total fee-sides over window: {full.side_count} "
          f"(~{full.side_count / (tsm_stats.n_months / 12):.1f}/yr — low turnover)")

    print("\n  Fee sensitivity (net Sharpe / net total / CAGR / maxDD across IBKR fee assumptions):")
    for fee in FEE_SWEEP_BPS:
        r = run_tsmom(series, lookback=lookback, fee_bps_per_side=fee, start=start, end=last_complete)
        s = _stats(r.net_returns)
        print(f"    {fee:>3.0f} bps/side  Sharpe={s.ann_sharpe:+.2f}  tot={s.total_return:+.1%}  "
              f"CAGR={s.cagr:+.2%}  maxDD={s.max_dd:.1%}")

    # ---- REAL purged + embargoed HOLDOUT (the deployment OOS check) ----
    # Use the shared cosmu.research.equity_holdout split: chronological, last HOLDOUT_FRAC of the realized NET-return
    # stream is the genuine out-of-sample tail; an embargo of LOOKBACK observations is discarded between IS and holdout
    # so no 12m formation window straddles the boundary. We score the HOLDOUT tail honestly (Sharpe, total, maxDD).
    split = purged_embargoed_split(full.net_returns, holdout_frac=HOLDOUT_FRAC, embargo=HOLDOUT_EMBARGO,
                                   min_holdout=6)
    n_is = len(split.in_sample)
    n_hold = len(split.holdout)
    # Align the benchmark stream to the same chronological holdout tail (last n_hold months of the bench series).
    bench_holdout = full.bench_returns[len(full.bench_returns) - n_hold:] if n_hold > 0 else []
    is_stats = _stats(split.in_sample)
    hold_stats = _stats(split.holdout)
    hold_bench_stats = _stats(bench_holdout)
    hold_start = full.months[len(full.months) - n_hold] if n_hold > 0 else None
    print(f"\n### REAL PURGED+EMBARGOED HOLDOUT — IS {n_is}m | embargo {HOLDOUT_EMBARGO}m | "
          f"HOLDOUT {n_hold}m (from {hold_start} -> {last_complete})")
    print("  [IN-SAMPLE]")
    print(_fmt_stats("TSMOM (net)", is_stats))
    print("  [HOLDOUT]  <-- the deployment check (genuinely out-of-sample tail)")
    print(_fmt_stats("TSMOM (net)", hold_stats))
    print(_fmt_stats("Buy & Hold SPY", hold_bench_stats))
    print(f"  holdout_dsr (PSR of holdout Sharpe vs 0, recentred; >0 ⇔ significantly positive): {split.holdout_dsr:+.4f}")

    # ---- SUBPERIOD ROBUSTNESS ----
    print("\n### SUBPERIOD ROBUSTNESS — TSMOM net total vs B&H SPY total over each regime")
    subperiods = [
        ("2008 GFC crash    (07/2008-02/2009)", (2008, 7), (2009, 2)),
        ("recovery+QE bull  (03/2009-12/2019)", (2009, 3), (2019, 12)),
        ("COVID crash       (02/2020-04/2020)", (2020, 2), (2020, 4)),
        ("2022 bear         (01/2022-12/2022)", (2022, 1), (2022, 12)),
        ("post-2022 bull    (01/2023-now)     ", (2023, 1), last_complete),
    ]
    for label, s0, s1 in subperiods:
        if s0 < start:
            continue
        gr = run_tsmom(series, lookback=lookback, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=s0, end=s1)
        g, sp = _stats(gr.net_returns), _stats(gr.bench_returns)
        edge = g.total_return - sp.total_return
        print(f"  {label}  TSMOM={g.total_return:+6.1%}  SPY={sp.total_return:+6.1%}  edge={edge:+6.1%}  "
              f"(TSMOM maxDD {g.max_dd:.0%} vs SPY {sp.max_dd:.0%})")

    # ---- VERDICT (deployment bar — honest, NOT pass-tuned) ----
    # The prompt's bar: positive OOS net of fees on the REAL holdout, AND beats B&H SPY risk-adjusted (higher Sharpe
    # AND/OR materially lower maxDD), robust across subperiods. The documented TSMOM edge is risk-adjusted return +
    # drawdown control from diversification + absolute-momentum de-risking. We require ALL of:
    #   (1) HOLDOUT net total POSITIVE (the edge survives, untouched, into a window it never saw), AND
    #   (2) holdout_dsr > 0 (the holdout Sharpe is significantly positive — the REAL holdout gate, not a stub), AND
    #   (3) beats B&H SPY risk-adjusted over the FULL cycle: higher Sharpe OR materially (<=75%) lower maxDD.
    MATERIAL_DD = 0.75
    holdout_positive = hold_stats.total_return > 0
    holdout_dsr_ok = split.holdout_dsr > 0
    beats_sharpe = tsm_stats.ann_sharpe > bench_stats.ann_sharpe
    lower_dd = tsm_stats.max_dd <= bench_stats.max_dd * MATERIAL_DD
    beats_risk_adj = beats_sharpe or lower_dd
    deployable = holdout_positive and holdout_dsr_ok and beats_risk_adj
    print("\n" + "=" * 104)
    print("VERDICT (deployment bar — NOT the 0.95 in-sample Gate):")
    print(f"  (1) HOLDOUT net-of-fee POSITIVE?                  {holdout_positive}  "
          f"(holdout net total {hold_stats.total_return:+.1%})")
    print(f"  (2) REAL holdout_dsr > 0 (sig. positive Sharpe)?  {holdout_dsr_ok}  (dsr {split.holdout_dsr:+.4f})")
    print(f"  (3) BEATS B&H SPY risk-adjusted (full cycle)?     {beats_risk_adj}  "
          f"[Sharpe {tsm_stats.ann_sharpe:+.2f} vs {bench_stats.ann_sharpe:+.2f} -> {beats_sharpe}; "
          f"maxDD {tsm_stats.max_dd:.1%} vs {bench_stats.max_dd:.1%} (~{tsm_stats.max_dd / bench_stats.max_dd:.0%}) -> {lower_dd}]")
    print(f"  ==> {'DEPLOYABLE — arm the live paper' if deployable else 'NOT deployable on our data (honest FAIL)'}")
    print("=" * 104)

    sig = current_signal(series, last_complete, lookback)
    longs_now = [a for a in ASSETS if sig[a]]
    print(f"\nCURRENT TSMOM signal (decided at {last_complete} month-end, to hold next month): "
          f"LONG {longs_now if longs_now else '(all cash)'}  (weight 1/{len(ASSETS)} each; rest in cash)")

    return {
        "deployable": deployable,
        "current_signal": sig,
        "longs_now": longs_now,
        "full": tsm_stats,
        "full_bench": bench_stats,
        "holdout": hold_stats,
        "holdout_bench": hold_bench_stats,
        "holdout_dsr": split.holdout_dsr,
        "in_sample": is_stats,
        "side_count": full.side_count,
        "window": (start, last_complete),
        "holdout_window": (hold_start, last_complete),
        "n_is": n_is,
        "n_hold": n_hold,
        "result": full,
    }


def main(argv: list[str] | None = None) -> int:
    validate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
