# intent: DEPLOY-A-DOCUMENTED-STRATEGY track — a TECH-TILT VARIANT of Antonacci's Global Equities Momentum (GEM).
# The canonical GEM rotates between US-broad (SPY) and international (EFA) equity, de-risking to bonds when US equity
# fails the T-bill hurdle. This variant swaps the US sleeve SPY -> QQQ (Nasdaq-100, a tech/large-growth tilt) while
# keeping EFA as the international sleeve. It is the SAME documented dual-momentum mechanism (absolute + relative
# momentum), expressed on a higher-beta US equity proxy. We validate it HONESTLY on our own total-return data and
# compare it head-to-head with the live SPY-based GEM. It is NOT routed through the 0.95 in-sample Gate (that guard is
# for NOVEL mined edges); the appropriate validators are external literature (dual momentum) + positive OOS net of
# real fees + a REAL purged/embargoed holdout + the live paper.
#
# THE RULE (monthly, signal at month-end t, trade t+1 — NO look-ahead):
#   1. ABSOLUTE momentum: is QQQ's trailing-12m total return > SHY's (short-Treasury hurdle)?
#        NO  -> hold AGG (US aggregate bonds) for the month  (risk-OFF).
#        YES -> RELATIVE momentum: hold whichever of QQQ (US-tech) / EFA (international) has the higher trailing-12m
#               total return for the month  (risk-ON, the stronger equity).
#   Per the candidate brief: "QQQ vs EFA dual momentum (12m), winner if > SHY else AGG; monthly."
#
# DATA: TOTAL-RETURN (adjusted-close) MONTHLY bars from the equities cache `*_tr.json`. Window binds on the youngest
#   series (AGG, lists 2003-09) -> first investable month ~2004-10. QQQ (1999), EFA (2001), SHY (2002) all predate AGG.
#
# FEES: REAL IBKR all-in on liquid ETFs ~1 bp/side (sweep {1,2,3,5}). A side is paid only when the held instrument
#   CHANGES month-to-month (one ETF held at a time; an unchanged hold pays nothing).
#
# HOLDOUT: a REAL purged+embargoed holdout via cosmu.research.equity_holdout.purged_embargoed_split on the realized
#   NET monthly return stream (NOT a stub). The held-out tail's deflated Sharpe (PSR vs 0, recentred) must be > 0.
#
# VALIDATION (the DEPLOYMENT bar, not the 0.95 Gate): positive OOS net of real fees, BEATS buy-and-hold SPY
#   risk-adjusted (higher Sharpe AND/OR materially lower maxDD), robust across regimes, holdout DSR > 0. Honest FAIL
#   is a valid outcome — we do NOT tune to pass.

from __future__ import annotations

import sys
from dataclasses import dataclass

from cosmu.research.equity_dual_momentum import (
    FEE_SWEEP_BPS,
    IBKR_ETF_BPS_PER_SIDE,
    LOOKBACK_MONTHS,
    MonthlySeries,
    PerfStats,
    _add_months,
    _fmt_stats,
    _realized_return,
    _stats,
    _trailing_return,
    load_monthly,
)
from cosmu.research.equity_holdout import purged_embargoed_split

# Tech-tilt universe: US sleeve = QQQ (was SPY). INTL = EFA. Hurdle = SHY. Risk-off = AGG.
EQUITY_US = "QQQ"
EQUITY_INTL = "EFA"
BONDS = "AGG"
TBILL = "SHY"
SERIES = [EQUITY_US, EQUITY_INTL, BONDS, TBILL]
BENCH = "SPY"  # the live-GEM benchmark we must beat risk-adjusted (buy & hold SPY total return)


@dataclass
class GemResult:
    months: list[tuple[int, int]]
    holdings: list[str]
    net_returns: list[float]
    gross_returns: list[float]
    bench_returns: list[float]   # buy-and-hold SPY total return over the SAME months (the benchmark)
    switches: int


def _signal(series: dict[str, MonthlySeries], asof: tuple[int, int], lookback: int) -> str | None:
    """The holding decided at month-end `asof` (held the following month). Tech-tilt: US sleeve is QQQ.
    None if any required trailing return is unavailable that month (NO synthetic fill / NO look-ahead)."""
    r_us = _trailing_return(series[EQUITY_US], asof, lookback)
    r_intl = _trailing_return(series[EQUITY_INTL], asof, lookback)
    r_bill = _trailing_return(series[TBILL], asof, lookback)
    if r_us is None or r_intl is None or r_bill is None:
        return None
    if r_us <= r_bill:           # absolute momentum fails -> risk-off into bonds
        return BONDS
    return EQUITY_US if r_us >= r_intl else EQUITY_INTL  # relative: stronger of QQQ / EFA


def run(
    series: dict[str, MonthlySeries],
    *,
    lookback: int = LOOKBACK_MONTHS,
    fee_bps_per_side: float = IBKR_ETF_BPS_PER_SIDE,
    start: tuple[int, int] | None = None,
    end: tuple[int, int] | None = None,
) -> GemResult:
    """Run the QQQ/EFA dual-momentum variant month-by-month with no look-ahead. Holding for month M is decided from
    data through M-1; return realized over M; a fee charged ONLY when the holding changes (2 sides per switch)."""
    fee = fee_bps_per_side / 1e4
    all_months = series[EQUITY_US].months
    months_out: list[tuple[int, int]] = []
    holdings: list[str] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    bench_r: list[float] = []
    switches = 0
    prev_hold: str | None = None
    for m in all_months:
        if start is not None and m < start:
            continue
        if end is not None and m > end:
            continue
        signal_month = _add_months(m, -1)  # decide at the PRIOR month-end (PIT)
        hold = _signal(series, signal_month, lookback)
        if hold is None:
            continue
        r = _realized_return(series[hold], m)
        bench = _realized_return(series[BENCH], m)
        if r is None or bench is None:
            continue
        if prev_hold is None:
            cost = fee
        elif hold != prev_hold:
            cost = 2 * fee
            switches += 1
        else:
            cost = 0.0
        months_out.append(m)
        holdings.append(hold)
        gross_r.append(r)
        net_r.append(r - cost)
        bench_r.append(bench)
        prev_hold = hold
    return GemResult(months_out, holdings, net_r, gross_r, bench_r, switches)


def first_investable_month(series: dict[str, MonthlySeries], lookback: int) -> tuple[int, int]:
    """First month every series has BOTH a close and a `lookback`-prior close. Binds on AGG (2003-09)."""
    starts = []
    for sym in SERIES + [BENCH]:
        starts.append(_add_months(series[sym].months[0], lookback + 1))
    return max(starts)


def validate(lookback: int = LOOKBACK_MONTHS) -> dict:
    """Honest validation of the QQQ/EFA tech-tilt dual-momentum variant + head-to-head vs the live SPY-based GEM.
    Returns a dict the arming path reuses. Uses the REAL purged+embargoed holdout (NOT a stub)."""
    from datetime import UTC, datetime

    series = {sym: load_monthly(sym) for sym in SERIES + [BENCH]}
    start = first_investable_month(series, lookback)
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)

    print("=" * 100)
    print("QQQ/EFA DUAL MOMENTUM (tech-tilt GEM variant) — DEPLOY-A-DOCUMENTED-STRATEGY validation")
    print("NOT the 0.95 in-sample Gate. Dual-momentum is an externally-validated mechanism; here we check POSITIVE")
    print("OOS net of REAL IBKR fees + BEATS buy-and-hold SPY risk-adjusted + a REAL purged/embargoed holdout.")
    print(f"Universe: US={EQUITY_US} INTL={EQUITY_INTL} BONDS={BONDS} HURDLE={TBILL} | bench={BENCH} | "
          f"lookback={lookback}m | signal@t, trade t+1 | window {start} -> {last_complete}")
    print("=" * 100)

    # ---- FULL SAMPLE + fee sweep ----
    print("\n### FULL SAMPLE — QQQ/EFA dual-momentum (net of IBKR fees) vs buy-and-hold SPY (total return)")
    full = run(series, lookback=lookback, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=last_complete)
    var_stats = _stats(full.net_returns)
    bench_stats = _stats(full.bench_returns)
    gross_stats = _stats(full.gross_returns)
    print(_fmt_stats("QQQ/EFA DM (net,1bps)", var_stats))
    print(_fmt_stats("QQQ/EFA DM (gross)", gross_stats))
    print(_fmt_stats("Buy & Hold SPY", bench_stats))
    print(f"  switches over window: {full.switches}  (~{full.switches / (var_stats.n_months / 12):.1f}/yr)")

    print("\n  Fee sensitivity (net Sharpe / net total / maxDD across IBKR fee assumptions):")
    for fee in FEE_SWEEP_BPS:
        r = run(series, lookback=lookback, fee_bps_per_side=fee, start=start, end=last_complete)
        s = _stats(r.net_returns)
        print(f"    {fee:>3.0f} bps/side  Sharpe={s.ann_sharpe:+.2f}  tot={s.total_return:+.1%}  "
              f"CAGR={s.cagr:+.2%}  maxDD={s.max_dd:.1%}")

    # ---- IS / OOS purged temporal split ----
    n_total = var_stats.n_months
    is_end = full.months[n_total // 2]
    oos_start = _add_months(is_end, lookback)
    print(f"\n### IS / OOS PURGED SPLIT — IS {start}->{is_end} | purge {lookback}m | OOS {oos_start}->{last_complete}")
    is_run = run(series, lookback=lookback, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=is_end)
    oos_run = run(series, lookback=lookback, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=oos_start, end=last_complete)
    is_var, is_bench = _stats(is_run.net_returns), _stats(is_run.bench_returns)
    oos_var, oos_bench = _stats(oos_run.net_returns), _stats(oos_run.bench_returns)
    print("  [IS]")
    print(_fmt_stats("QQQ/EFA DM (net)", is_var))
    print(_fmt_stats("Buy & Hold SPY", is_bench))
    print("  [OOS]  <-- the deployment check")
    print(_fmt_stats("QQQ/EFA DM (net)", oos_var))
    print(_fmt_stats("Buy & Hold SPY", oos_bench))

    # ---- REAL purged + embargoed HOLDOUT (cosmu.research.equity_holdout — NOT a stub) ----
    # Split the realized NET monthly stream into in-sample (~80%) + held-out tail (~20%) with an embargo band that
    # covers the 12m formation window. The held-out tail's deflated Sharpe (PSR vs 0, recentred) must be > 0.
    split = purged_embargoed_split(full.net_returns, holdout_frac=0.2, embargo=lookback)
    holdout_dsr = split.holdout_dsr
    holdout_stats = _stats(split.holdout) if split.holdout else PerfStats(0, 0, 0, 0, 0, 0, 0)
    print(f"\n### REAL HOLDOUT (purged+embargoed, embargo={lookback}m) — held-out tail is {len(split.holdout)} months")
    print(_fmt_stats("Holdout tail (net)", holdout_stats))
    print(f"  holdout_deflated_sharpe = {holdout_dsr:+.6f}   (>0 ⇔ held-out Sharpe significantly positive)")

    # ---- SUBPERIOD ROBUSTNESS ----
    print("\n### SUBPERIOD ROBUSTNESS — variant net total vs B&H SPY total over each regime")
    subperiods = [
        ("2008 GFC crash    (07/2008-02/2009)", (2008, 7), (2009, 2)),
        ("recovery+QE bull  (03/2009-12/2019)", (2009, 3), (2019, 12)),
        ("COVID crash       (02/2020-03/2020)", (2020, 2), (2020, 3)),
        ("2022 bear         (01/2022-12/2022)", (2022, 1), (2022, 12)),
        ("post-2022 bull    (01/2023-now)     ", (2023, 1), last_complete),
    ]
    for label, s0, s1 in subperiods:
        if s0 < start:
            continue
        gr = run(series, lookback=lookback, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=s0, end=s1)
        g, sp = _stats(gr.net_returns), _stats(gr.bench_returns)
        print(f"  {label}  VAR={g.total_return:+6.1%}  SPY={sp.total_return:+6.1%}  edge={g.total_return - sp.total_return:+6.1%}  "
              f"(VAR maxDD {g.max_dd:.0%} vs SPY {sp.max_dd:.0%})")

    # ---- HEAD-TO-HEAD vs the live SPY-based GEM ----
    from cosmu.research import equity_dual_momentum as gem
    gem_series = {sym: load_monthly(sym) for sym in gem.GEM_SERIES}
    gem_start = gem.first_investable_month(gem_series, lookback)
    common_start = max(start, gem_start)
    gem_full = gem.run_gem(gem_series, lookback=lookback, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE,
                           start=common_start, end=last_complete)
    var_common = run(series, lookback=lookback, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE,
                     start=common_start, end=last_complete)
    gem_c, var_c = _stats(gem_full.net_returns), _stats(var_common.net_returns)
    print(f"\n### HEAD-TO-HEAD vs live SPY-based GEM (common window {common_start}->{last_complete})")
    print(_fmt_stats("Live GEM (SPY/EFA)", gem_c))
    print(_fmt_stats("This variant (QQQ/EFA)", var_c))

    # ---- VERDICT (deployment bar — honest, NOT pass-tuned) ----
    MATERIAL_DD_REDUCTION = 0.75  # "materially lower" = <= 75% of SPY's maxDD
    oos_positive = oos_var.total_return > 0
    full_lower_dd = var_stats.max_dd <= bench_stats.max_dd * MATERIAL_DD_REDUCTION
    full_sharpe_tied_or_better = var_stats.ann_sharpe >= bench_stats.ann_sharpe - 0.05
    holdout_passed = holdout_dsr > 0
    deployable = oos_positive and full_lower_dd and full_sharpe_tied_or_better and holdout_passed

    print("\n" + "=" * 100)
    print("VERDICT (deployment bar — NOT the 0.95 in-sample Gate):")
    print(f"  (1) OOS net-of-fee POSITIVE?            {oos_positive}  (OOS net total {oos_var.total_return:+.1%})")
    print(f"  (2) FULL-cycle materially lower maxDD?  {full_lower_dd}  "
          f"(VAR {var_stats.max_dd:.1%} vs SPY {bench_stats.max_dd:.1%}, "
          f"~{var_stats.max_dd / bench_stats.max_dd:.0%} of SPY)")
    print(f"  (3) FULL-cycle Sharpe tied-or-better?   {full_sharpe_tied_or_better}  "
          f"(VAR {var_stats.ann_sharpe:+.2f} vs SPY {bench_stats.ann_sharpe:+.2f})")
    print(f"  (4) REAL holdout DSR > 0?               {holdout_passed}  (holdout_dsr {holdout_dsr:+.4f})")
    print(f"  ==> {'DEPLOYABLE — arm the live paper' if deployable else 'NOT deployable on our data (honest FAIL)'}")
    print("=" * 100)

    current_signal = _signal(series, last_complete, lookback)
    print(f"\nCURRENT signal (decided at {last_complete} month-end, to hold next month): HOLD {current_signal}")

    return {
        "deployable": deployable,
        "current_signal": current_signal,
        "full": var_stats,
        "full_bench": bench_stats,
        "oos": oos_var,
        "oos_bench": oos_bench,
        "holdout_dsr": holdout_dsr,
        "holdout_passed": holdout_passed,
        "switches": full.switches,
        "window": (start, last_complete),
        "result": full,
        "gem_common": gem_c,
        "var_common": var_c,
    }


def main(argv: list[str] | None = None) -> int:
    validate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
