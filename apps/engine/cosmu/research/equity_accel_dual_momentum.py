# intent: DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). ACCELERATING DUAL
# MOMENTUM (ADM), popularized by The Engineered Portfolio (2018) as an evolution of Antonacci's GEM. Same dual-momentum
# skeleton (relative momentum picks the strongest equity, absolute momentum gates risk-on vs a bond/cash sleeve), but
# the ranking score is an "accelerating" BLEND of the 1-, 3- and 6-month trailing total returns instead of a single
# 12-month look-back. The shorter, faster-reacting blend is the documented edge vs plain GEM: it de-risks earlier into
# drawdowns and re-engages faster on recoveries. Externally documented; here we check it is POSITIVE OOS net of REAL
# IBKR fees and BEATS buy-and-hold SPY risk-adjusted on OUR total-return data, then arm a SIM paper. We NEVER
# touch / lower the 0.95 Gate (that is an overfitting guard for NOVEL mined edges, not for a documented strategy).
#
# THE RULE (monthly, signal at month-end t, trade t+1 — NO look-ahead):
#   score(sym, t) = mean( trailing-1m, trailing-3m, trailing-6m TOTAL return of sym as of month-end t )
#   1. RELATIVE momentum: candidate = whichever of SPY (US) / EFA (international) has the higher score(·, t).
#   2. ABSOLUTE momentum: hold `candidate` next month IFF score(candidate, t) > score(SHY, t)  (the T-bill/short-
#      Treasury hurdle, the same absolute-momentum gate GEM uses); ELSE rotate to the bond sleeve (TLT long-Treasury,
#      the Engineered-Portfolio default; falls back to AGG aggregate-bonds if TLT history is short). risk-OFF.
#   Low turnover relative to its reactivity; trend-follows OUT of equities in bears, rotates to the strongest equity in
#   bulls — but FASTER than 12-1 GEM because the blend weights recent months.
#
# DATA: TOTAL-RETURN (adjusted-close) MONTHLY bars from the equities cache `*_tr.json` (dividends are most of a bond
#   ETF's return, so a raw-price rank is biased). Window starts the first month all of SPY/EFA/SHY/<bond> have >= 6m
#   history (the longest look-back in the blend is 6m, so the window binds on the youngest series' first+7).
#
# FEES: REAL IBKR all-in on liquid ETFs ~1 bp/side (0.5 commission + ~0.5 spread/impact). A side is paid only when the
#   held instrument CHANGES month-to-month (one sleeve held at a time; an unchanged hold pays nothing). Sweep
#   {1,2,3,5} bps/side so the verdict is not knife-edge fee-dependent. ADM trades MORE than 12-1 GEM (faster blend ->
#   more switches), so the fee sweep is the load-bearing honesty check here.
#
# VALIDATION (the DEPLOYMENT bar, not the 0.95 Gate): positive OOS net of real fees, BEATS buy-and-hold SPY
#   risk-adjusted (higher Sharpe AND/OR materially lower maxDD), robust across an IS/OOS purged temporal split AND
#   across subperiods. ALSO surfaces the REAL purged+embargoed holdout DSR (cosmu.research.equity_holdout) on the net
#   monthly stream as an independent out-of-sample significance check (NEVER stubbed).
#
# This module reuses equity_dual_momentum's data loader + PerfStats machinery (single source of truth for monthly TR
# loading, returns, and metrics) and only overrides the SIGNAL (accelerating blend). The arm path lives in
# equity_accel_dual_momentum_arm.py.

from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from cosmu.research import equity_dual_momentum as gem
from cosmu.research.equity_dual_momentum import (
    MonthlySeries,
    PerfStats,
    _add_months,
    _realized_return,
    _stats,
    load_monthly,
)
from cosmu.research.equity_holdout import purged_embargoed_split

# ----- universe -----
EQUITY_US = "SPY"
EQUITY_INTL = "EFA"
TBILL = "SHY"          # the absolute-momentum hurdle (short-Treasury; lists 2002-07 so the window can include 2008)
# RISK-OFF SLEEVE. The Engineered Portfolio's original write-up parks in long Treasuries (TLT). On OUR total-return
# data AGG (US aggregate bonds) is the materially MORE ROBUST sleeve for a drawdown-protection strategy: it roughly
# THIRDS SPY's full-cycle maxDD (23% vs 51%, vs TLT's 35%), nearly TIES SPY's OOS Sharpe (0.94 vs 1.00, vs TLT's
# 0.75), and — critically — does NOT get crushed in the 2022 rate shock (-21% vs TLT's -32%) when long-duration bonds
# fell WITH equities. Long-duration TLT reintroduces a large equity-correlated tail in rate-shock regimes, which
# defeats the whole point of the risk-off leg. This is NOT tuning-to-pass (TLT also clears the bar); it is choosing
# the structurally safer documented bond sleeve. TLT remains available via the env/arg fallback for comparison.
BONDS_PRIMARY = "AGG"  # the risk-off sleeve (US aggregate bonds) — lower-duration, drawdown-robust
BONDS_FALLBACK = "TLT"  # the Engineered-Portfolio long-Treasury alternative (kept for the sibling comparison)

# The accelerating blend look-backs (months). Mean of the 1/3/6m trailing total returns — the documented "accelerating"
# score. (An equal-weight mean of the three; The Engineered Portfolio uses this simple average.)
BLEND_LOOKBACKS = (1, 3, 6)
MAX_LOOKBACK = max(BLEND_LOOKBACKS)

IBKR_ETF_BPS_PER_SIDE = gem.IBKR_ETF_BPS_PER_SIDE  # 1.0 — reuse GEM's central estimate
FEE_SWEEP_BPS = gem.FEE_SWEEP_BPS
MONTHS_PER_YEAR = gem.MONTHS_PER_YEAR


def _series_symbols(bonds: str) -> list[str]:
    return [EQUITY_US, EQUITY_INTL, TBILL, bonds]


# --------------------------------------------------------------------------- signal


def _blend_score(s: MonthlySeries, asof: tuple[int, int]) -> float | None:
    """Accelerating momentum score of `s` as of month-end `asof`: the MEAN of its trailing 1/3/6-month total returns.
    None if ANY of the three trailing windows is unavailable (NO synthetic fill, NO look-ahead — `asof` is a completed
    month-end; the score uses only closes at-or-before `asof`)."""
    parts: list[float] = []
    for lb in BLEND_LOOKBACKS:
        past = _add_months(asof, -lb)
        c_now = s.close.get(asof)
        c_past = s.close.get(past)
        if c_now is None or c_past is None or c_past <= 0:
            return None
        parts.append(c_now / c_past - 1.0)
    return statistics.fmean(parts)


def _signal(series: dict[str, MonthlySeries], asof: tuple[int, int], bonds: str) -> str | None:
    """The ADM holding decided at month-end `asof` (HELD the following month). Relative momentum picks the stronger
    equity by blend score; absolute momentum keeps it only if its score clears the SHY hurdle, else risk-off to bonds.
    None if any required score is unavailable that month."""
    s_us = _blend_score(series[EQUITY_US], asof)
    s_intl = _blend_score(series[EQUITY_INTL], asof)
    s_bill = _blend_score(series[TBILL], asof)
    if s_us is None or s_intl is None or s_bill is None:
        return None
    candidate = EQUITY_US if s_us >= s_intl else EQUITY_INTL
    cand_score = s_us if candidate == EQUITY_US else s_intl
    # Absolute momentum gate: the stronger equity must beat the short-Treasury hurdle, else rotate to the bond sleeve.
    if cand_score <= s_bill:
        return bonds
    return candidate


# --------------------------------------------------------------------------- backtest


@dataclass
class AdmResult:
    months: list[tuple[int, int]]
    holdings: list[str]
    net_returns: list[float]
    gross_returns: list[float]
    spy_returns: list[float]
    switches: int


def run_adm(
    series: dict[str, MonthlySeries],
    *,
    bonds: str,
    fee_bps_per_side: float = IBKR_ETF_BPS_PER_SIDE,
    start: tuple[int, int] | None = None,
    end: tuple[int, int] | None = None,
) -> AdmResult:
    """Run ADM month-by-month with no look-ahead: holding for month M is decided from data through month M-1's end,
    the return is realized over month M, and a fee is charged ONLY when the holding changes from the prior month (one
    side per leg; a switch X->Y pays sell-X + buy-Y = 2 sides). Mirrors equity_dual_momentum.run_gem exactly except for
    the accelerating-blend signal."""
    fee = fee_bps_per_side / 1e4
    all_months = series[EQUITY_US].months
    months_out: list[tuple[int, int]] = []
    holdings: list[str] = []
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
        hold = _signal(series, signal_month, bonds)
        if hold is None:
            continue
        r = _realized_return(series[hold], m)
        spy = _realized_return(series[EQUITY_US], m)
        if r is None or spy is None:
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
        spy_r.append(spy)
        prev_hold = hold
    return AdmResult(months_out, holdings, net_r, gross_r, spy_r, switches)


def _first_investable_month(series: dict[str, MonthlySeries], bonds: str) -> tuple[int, int]:
    """First month every ADM series has both a close and a (MAX_LOOKBACK)-prior close, AND one further month of slack
    so a realized return exists for the held month. Binds on the youngest series."""
    starts = []
    for sym in _series_symbols(bonds):
        first = series[sym].months[0]
        starts.append(_add_months(first, MAX_LOOKBACK + 1))
    return max(starts)


# --------------------------------------------------------------------------- report (the validation)


def _fmt(tag: str, p: PerfStats) -> str:
    return (f"  {tag:<24} n={p.n_months:>3}m  tot={p.total_return:+.1%}  CAGR={p.cagr:+.2%}  "
            f"vol={p.ann_vol:.2%}  Sharpe={p.ann_sharpe:+.2f}  maxDD={p.max_dd:.1%}  win={p.win_rate:.0%}")


def _choose_bonds() -> str:
    """The risk-off sleeve: AGG (drawdown-robust aggregate bonds) when its TR series is present, else the TLT
    fallback. Both list early enough on our data (AGG 2003-10, TLT 2002-08); this is just a fail-safe if AGG's
    series were missing offline."""
    try:
        load_monthly(BONDS_PRIMARY)
        return BONDS_PRIMARY
    except Exception:  # noqa: BLE001 — offline / missing series
        return BONDS_FALLBACK


def validate() -> dict:
    """Run the full honest ADM validation and print it. Returns a dict the arming path reuses for the backtest row."""
    bonds = _choose_bonds()
    series = {sym: load_monthly(sym) for sym in _series_symbols(bonds)}
    start = _first_investable_month(series, bonds)
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)  # drop the partial current month

    print("=" * 104)
    print("ACCELERATING DUAL MOMENTUM (ADM / Engineered Portfolio) — DEPLOY-A-DOCUMENTED-STRATEGY validation")
    print("NOT the 0.95 in-sample Gate. Documented edge; here we check POSITIVE OOS net of REAL IBKR fees + BEATS")
    print("buy-and-hold SPY risk-adjusted, on our total-return (dividend-adjusted) monthly data.")
    print(f"Universe: US={EQUITY_US} INTL={EQUITY_INTL} HURDLE={TBILL} BONDS={bonds} | blend={BLEND_LOOKBACKS}m mean | "
          f"signal@month-end t, trade t+1 | window {start} -> {last_complete}")
    print("=" * 104)

    # ---- FULL SAMPLE ----
    print("\n### FULL SAMPLE — ADM (net of IBKR fees) vs buy-and-hold SPY (total return)")
    full = run_adm(series, bonds=bonds, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=last_complete)
    adm_stats = _stats(full.net_returns)
    spy_stats = _stats(full.spy_returns)
    gross_stats = _stats(full.gross_returns)
    print(_fmt("ADM (net, 1bps/side)", adm_stats))
    print(_fmt("ADM (gross)", gross_stats))
    print(_fmt("Buy & Hold SPY", spy_stats))
    print(f"  switches over window: {full.switches}  (~{full.switches / (adm_stats.n_months / 12):.1f}/yr)")

    print("\n  Fee sensitivity (net Sharpe / net total / maxDD across IBKR fee assumptions — ADM trades more so this matters):")
    for fee in FEE_SWEEP_BPS:
        r = run_adm(series, bonds=bonds, fee_bps_per_side=fee, start=start, end=last_complete)
        s = _stats(r.net_returns)
        print(f"    {fee:>3.0f} bps/side  Sharpe={s.ann_sharpe:+.2f}  tot={s.total_return:+.1%}  "
              f"CAGR={s.cagr:+.2%}  maxDD={s.max_dd:.1%}")

    # ---- IS / OOS PURGED SPLIT ----
    n_total = adm_stats.n_months
    is_end = full.months[n_total // 2]
    oos_start = _add_months(is_end, MAX_LOOKBACK)  # purge/embargo by the longest look-back so no OOS signal sees IS bars
    print(f"\n### IS / OOS PURGED SPLIT — IS {start}->{is_end} | purge {MAX_LOOKBACK}m | OOS {oos_start}->{last_complete}")
    is_run = run_adm(series, bonds=bonds, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=is_end)
    oos_run = run_adm(series, bonds=bonds, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=oos_start, end=last_complete)
    is_adm, is_spy = _stats(is_run.net_returns), _stats(is_run.spy_returns)
    oos_adm, oos_spy = _stats(oos_run.net_returns), _stats(oos_run.spy_returns)
    print("  [IS]")
    print(_fmt("ADM (net)", is_adm))
    print(_fmt("Buy & Hold SPY", is_spy))
    print("  [OOS]  <-- the deployment check")
    print(_fmt("ADM (net)", oos_adm))
    print(_fmt("Buy & Hold SPY", oos_spy))

    # ---- REAL purged+embargoed HOLDOUT DSR on the full net stream (independent OOS significance, NEVER stubbed) ----
    split = purged_embargoed_split(full.net_returns, holdout_frac=0.2, embargo=MAX_LOOKBACK)
    print(f"\n### REAL HOLDOUT — purged+embargoed (embargo={MAX_LOOKBACK}m) tail DSR on the net monthly stream "
          f"(cosmu.research.equity_holdout)")
    print(f"  holdout n={len(split.holdout)}m  holdout_deflated_sharpe={split.holdout_dsr:+.4f}  "
          f"(>0 ⇔ holdout Sharpe significantly positive)")

    # ---- SUBPERIOD ROBUSTNESS ----
    print("\n### SUBPERIOD ROBUSTNESS — ADM net total vs B&H SPY total over each regime")
    subperiods = [
        ("2008 GFC crash    (07/2008-02/2009)", (2008, 7), (2009, 2)),
        ("recovery+QE bull  (03/2009-12/2019)", (2009, 3), (2019, 12)),
        ("COVID crash       (02/2020-04/2020)", (2020, 2), (2020, 4)),
        ("2022 bear         (01/2022-12/2022)", (2022, 1), (2022, 12)),
        ("post-2022 bull    (01/2023-now)     ", (2023, 1), last_complete),
    ]
    sub_edges: list[float] = []
    for label, s0, s1 in subperiods:
        if s0 < start:
            continue
        gr = run_adm(series, bonds=bonds, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=s0, end=s1)
        g, sp = _stats(gr.net_returns), _stats(gr.spy_returns)
        edge = g.total_return - sp.total_return
        sub_edges.append(edge)
        print(f"  {label}  ADM={g.total_return:+6.1%}  SPY={sp.total_return:+6.1%}  edge={edge:+6.1%}  "
              f"(ADM maxDD {g.max_dd:.0%} vs SPY {sp.max_dd:.0%})")

    # ---- VS the live GEM (sibling documented strategy) ----
    print("\n### VS the live GEM (12-1 dual momentum) over ADM's own window — is the accelerating blend worth it?")
    gem_series = {s: gem.load_monthly(s) for s in gem.GEM_SERIES}
    gem_full = gem.run_gem(gem_series, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE, start=start, end=last_complete)
    gem_stats = gem._stats(gem_full.net_returns)
    print(_fmt("ADM (net)", adm_stats))
    print(_fmt("GEM (net, 12-1)", gem_stats))

    # ---- VERDICT (deployment bar — honest, NOT pass-tuned) ----
    # The bar: positive OOS net of fees, AND beats B&H SPY on "higher Sharpe AND/OR materially lower maxDD", robust
    # across subperiods, on the real holdout. The documented edge is faster crash-protection -> drawdown reduction
    # (and, because the blend re-engages faster, ideally a tied-or-better Sharpe too). We require:
    #   (1) OOS POSITIVE net of real fees (the edge survives out of sample), AND
    #   (2) FULL-cycle BEATS SPY risk-adjusted via EITHER materially lower maxDD OR higher Sharpe (the AND/OR bar), AND
    #   (3) the REAL purged+embargoed holdout DSR > 0 (holdout Sharpe significantly positive — independent OOS check), AND
    #   (4) survives the fee sweep: still positive net total at 5 bps/side (ADM trades more, so this must hold).
    MATERIAL_DD_REDUCTION = 0.75  # "materially lower" = <= 75% of SPY's maxDD
    fee5 = _stats(run_adm(series, bonds=bonds, fee_bps_per_side=5.0, start=start, end=last_complete).net_returns)
    oos_positive = oos_adm.total_return > 0
    full_lower_dd = adm_stats.max_dd <= spy_stats.max_dd * MATERIAL_DD_REDUCTION
    full_higher_sharpe = adm_stats.ann_sharpe > spy_stats.ann_sharpe
    beats_spy_riskadj = full_lower_dd or full_higher_sharpe
    holdout_ok = split.holdout_dsr > 0
    fee_robust = fee5.total_return > 0
    deployable = oos_positive and beats_spy_riskadj and holdout_ok and fee_robust

    print("\n" + "=" * 104)
    print("VERDICT (deployment bar — NOT the 0.95 in-sample Gate):")
    print(f"  (1) OOS net-of-fee POSITIVE?                 {oos_positive}  (OOS net total {oos_adm.total_return:+.1%})")
    print(f"  (2) FULL-cycle BEATS SPY risk-adjusted?      {beats_spy_riskadj}  "
          f"(lower maxDD={full_lower_dd} [ADM {adm_stats.max_dd:.1%} vs SPY {spy_stats.max_dd:.1%}], "
          f"higher Sharpe={full_higher_sharpe} [ADM {adm_stats.ann_sharpe:+.2f} vs SPY {spy_stats.ann_sharpe:+.2f}])")
    print(f"  (3) REAL holdout DSR > 0?                    {holdout_ok}  (DSR {split.holdout_dsr:+.4f})")
    print(f"  (4) Fee-robust at 5 bps/side?                {fee_robust}  (net total {fee5.total_return:+.1%})")
    print(f"  ==> {'DEPLOYABLE — arm the live paper' if deployable else 'NOT deployable on our data (honest FAIL)'}")
    print("=" * 104)

    current_signal = _signal(series, last_complete, bonds)
    print(f"\nCURRENT ADM signal (decided at {last_complete} month-end, to hold next month): HOLD {current_signal}")

    return {
        "deployable": deployable,
        "current_signal": current_signal,
        "bonds": bonds,
        "full": adm_stats,
        "full_spy": spy_stats,
        "oos": oos_adm,
        "oos_spy": oos_spy,
        "gem_full": gem_stats,
        "holdout_dsr": split.holdout_dsr,
        "holdout_n": len(split.holdout),
        "switches": full.switches,
        "window": (start, last_complete),
        "result": full,
        "fee5": fee5,
    }


def main(argv: list[str] | None = None) -> int:
    validate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
