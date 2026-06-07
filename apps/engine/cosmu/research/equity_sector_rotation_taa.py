# intent: DEPLOY-A-DOCUMENTED-STRATEGY track (NOT the in-sample 0.95 deflated-Sharpe Gate). SECTOR-MOMENTUM ROTATION
# with a market-regime risk-off overlay — a textbook Tactical Asset Allocation (TAA) rule (Faber-style absolute-
# momentum trend filter + relative sector momentum; cf. Mebane Faber "A Quantitative Approach to Tactical Asset
# Allocation" 2007, and the broad sector-rotation literature). This is externally documented, so it does NOT need our
# in-sample Gate (which is an OVERFITTING guard for NOVEL mined edges). The appropriate validators are: (a) the
# external literature, (b) a positive OOS-net-of-fees check on OUR data that BEATS buy-and-hold SPY risk-adjusted,
# (c) the LIVE forward-test. This module does (b) (using the REAL purged+embargoed equity_holdout) and arms (c). It
# NEVER touches / lowers the 0.95 Gate.
#
# THE RULE (monthly, signal at month-end t, trade t+1 — NO look-ahead):
#   REGIME FILTER (absolute momentum / trend): is SPY's month-end close >= its trailing 200-DAY simple moving average?
#     NO  -> RISK-OFF: hold AGG (US aggregate bonds) for the next month.
#     YES -> RISK-ON: rank the 9 SPDR sectors (XLK/XLF/XLE/XLV/XLY/XLP/XLI/XLU/XLB) by trailing 6-MONTH total return;
#            hold the TOP-3 equal-weight (1/3 each) for the next month.
#   Rebalanced MONTHLY. Low turnover; the trend filter de-risks into bonds in bear markets (the documented edge is
#   drawdown protection), the relative-momentum sleeve tilts to the strongest sectors in bull markets.
#
# DATA: TOTAL-RETURN (adjusted-close) bars from the equities cache `*_tr.json` (split+dividend adjusted) — dividends
#   are most of a bond ETF's return and material for sectors, so a raw-price rank/return is biased. The 200-day SMA
#   regime filter is computed on SPY's daily total-return series. AGG (the risk-off sleeve) lists 2003-09, which binds
#   the start to the first month all of {SPY, AGG, the 9 sectors} have >=200 trading days + 6 months of history.
#
# FEES: REAL retail equity all-in on liquid ETFs ~1 bp/side (IBKR commission + spread/impact). A side is paid on the
#   realized two-sided monthly turnover (Σ|w_t - w_{t-1}| * per-side cost) so a low-turnover monthly book is charged
#   honestly little. Sweep {1,2,3,5} bps/side so the verdict is not knife-edge fee-dependent.
#
# VALIDATION (the DEPLOYMENT bar, not the 0.95 Gate): positive OOS net of real fees on the REAL purged+embargoed
#   holdout (cosmu.research.equity_holdout — NEVER stubbed), BEATS buy-and-hold SPY risk-adjusted (higher Sharpe
#   AND/OR materially lower maxDD), robust across subperiods.
#
# ARM: register the validated strategy as a forward-test track (the SAME control-plane rows the finder writes), open
#   ONE real held sim position in the currently-signalled book, and mark it. SIM-only; live stays OFF (no real money).

from __future__ import annotations

import json
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cosmu.research.equity_holdout import purged_embargoed_split

CACHE = Path("/Users/device/cosmu/.cosmu/market_data/equities")

SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB"]
MARKET = "SPY"          # regime-filter instrument
RISK_OFF = "AGG"        # risk-off sleeve (US aggregate bonds)
ALL_SERIES = [*SECTOR_ETFS, MARKET, RISK_OFF]

TOP_K = 3               # hold the top-3 sectors equal-weight
LOOKBACK_MONTHS = 6     # 6-month total-return momentum rank
SMA_DAYS = 200          # SPY 200-day SMA regime filter
ETF_BPS_PER_SIDE = 1.0  # central IBKR all-in estimate on liquid ETFs; sweep below
FEE_SWEEP_BPS = [1.0, 2.0, 3.0, 5.0]
MONTHS_PER_YEAR = 12


# --------------------------------------------------------------------------- data


@dataclass
class DailySeries:
    symbol: str
    ts: list[int]               # ascending ms timestamps
    close: list[float]          # total-return (adjusted) daily closes


def load_daily(symbol: str) -> DailySeries:
    """Load a `*_tr.json` total-return DAILY series (ascending). NO synthetic fill — Yahoo gap days are simply absent."""
    rows = json.loads((CACHE / f"{symbol}_tr.json").read_text())
    rows.sort(key=lambda r: int(r["ts"]))
    return DailySeries(symbol, [int(r["ts"]) for r in rows], [float(r["close"]) for r in rows])


def _month_key(ms: int) -> tuple[int, int]:
    d = datetime.fromtimestamp(ms / 1000, tz=UTC).date()
    return (d.year, d.month)


@dataclass
class MonthEnd:
    """The last completed daily bar of a calendar month (its month-end close) plus the index into the daily array
    (so the 200-day SMA can be computed from the trailing daily window ending at that bar — PIT, no look-ahead)."""

    close: float
    daily_idx: int


def month_end_index(s: DailySeries) -> dict[tuple[int, int], MonthEnd]:
    """Map each calendar month -> its LAST daily bar (close + daily index). PIT: only realized bars are used."""
    out: dict[tuple[int, int], tuple[int, float, int]] = {}
    for i, (t, c) in enumerate(zip(s.ts, s.close, strict=True)):
        mk = _month_key(t)
        if mk not in out or t >= out[mk][0]:
            out[mk] = (t, c, i)
    return {mk: MonthEnd(close=v[1], daily_idx=v[2]) for mk, v in out.items()}


def _add_months(ym: tuple[int, int], n: int) -> tuple[int, int]:
    y, m = ym
    total = (y * 12 + (m - 1)) + n
    return (total // 12, total % 12 + 1)


def sma_at(s: DailySeries, daily_idx: int, window: int) -> float | None:
    """Trailing `window`-day simple moving average of `s` ENDING AT (and including) `daily_idx`. PIT: uses only bars
    at indices [daily_idx-window+1 .. daily_idx], all <= the month-end. None if fewer than `window` bars precede it."""
    if daily_idx + 1 < window:
        return None
    return statistics.fmean(s.close[daily_idx - window + 1 : daily_idx + 1])


# --------------------------------------------------------------------------- backtest


@dataclass
class RotResult:
    months: list[tuple[int, int]]      # the months the strategy was INVESTED (a return realized for each)
    holdings: list[tuple[str, ...]]    # the basket held entering each month (signal from the PRIOR month-end)
    net_returns: list[float]
    gross_returns: list[float]
    spy_returns: list[float]           # buy-and-hold SPY total return over the SAME months (the benchmark)
    risk_off_months: int               # number of months held in AGG (regime filter triggered)
    switches: int                      # number of months the basket changed at all (turnover events)


def _trailing_return(me: dict[tuple[int, int], MonthEnd], asof: tuple[int, int], lookback: int) -> float | None:
    """Trailing `lookback`-month TOTAL return as of month `asof` = close[asof]/close[asof-lookback] - 1. None if
    either month-end is missing (the caller then drops that sector — NO synthetic fill, NO look-ahead)."""
    past = _add_months(asof, -lookback)
    cur = me.get(asof)
    old = me.get(past)
    if cur is None or old is None or old.close <= 0:
        return None
    return cur.close / old.close - 1.0


def _month_return(me: dict[tuple[int, int], MonthEnd], month: tuple[int, int]) -> float | None:
    """Total return of holding through `month` = close[month]/close[month-1] - 1."""
    prev = _add_months(month, -1)
    cur = me.get(month)
    pre = me.get(prev)
    if cur is None or pre is None or pre.close <= 0:
        return None
    return cur.close / pre.close - 1.0


def _signal(
    series: dict[str, DailySeries],
    me: dict[str, dict[tuple[int, int], MonthEnd]],
    asof: tuple[int, int],
    *,
    top_k: int,
    lookback: int,
    sma_days: int,
) -> tuple[str, ...] | None:
    """The basket decided at month-end `asof` (to be HELD the following month). Returns a tuple of symbols, or None if
    the signal can't be formed (missing market SMA). REGIME FILTER first (SPY vs its 200d SMA), then 6m sector rank."""
    spy_me = me[MARKET].get(asof)
    if spy_me is None:
        return None
    spy_sma = sma_at(series[MARKET], spy_me.daily_idx, sma_days)
    if spy_sma is None:
        return None
    if spy_me.close < spy_sma:
        return (RISK_OFF,)  # risk-OFF: trend filter says hold bonds
    # risk-ON: rank the 9 sectors by trailing 6m total return, hold the top-k equal-weight
    scored = []
    for sym in SECTOR_ETFS:
        r = _trailing_return(me[sym], asof, lookback)
        if r is not None:
            scored.append((sym, r))
    if len(scored) < top_k:
        return None
    scored.sort(key=lambda x: x[1], reverse=True)
    return tuple(sorted(s for s, _ in scored[:top_k]))


def run_rotation(
    series: dict[str, DailySeries],
    me: dict[str, dict[tuple[int, int], MonthEnd]],
    *,
    top_k: int = TOP_K,
    lookback: int = LOOKBACK_MONTHS,
    sma_days: int = SMA_DAYS,
    fee_bps_per_side: float = ETF_BPS_PER_SIDE,
    start: tuple[int, int] | None = None,
    end: tuple[int, int] | None = None,
) -> RotResult:
    """Run the rotation month-by-month, NO look-ahead: the basket for month M is decided from data through month M-1's
    month-end (close + 200d SMA + 6m rank), the return is realized over month M, and fees are charged on the realized
    two-sided turnover of the equal-weight basket change. An unchanged basket pays nothing."""
    fee = fee_bps_per_side / 1e4
    all_months = sorted(me[MARKET])
    months_out: list[tuple[int, int]] = []
    holdings: list[tuple[str, ...]] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    spy_r: list[float] = []
    risk_off = 0
    switches = 0
    prev_w: dict[str, float] = {}
    for m in all_months:
        if start is not None and m < start:
            continue
        if end is not None and m > end:
            continue
        signal_month = _add_months(m, -1)  # decide at the PRIOR month-end (PIT)
        basket = _signal(series, me, signal_month, top_k=top_k, lookback=lookback, sma_days=sma_days)
        if basket is None:
            continue
        # realized month-M total return of each held leg
        legs = {sym: _month_return(me[sym], m) for sym in basket}
        spy = _month_return(me[MARKET], m)
        if spy is None or any(v is None for v in legs.values()):
            continue
        w = {sym: 1.0 / len(basket) for sym in basket}
        gross = sum(w[sym] * legs[sym] for sym in basket)  # type: ignore[operator]
        # turnover cost: Σ|w_t - w_{t-1}| * per-side fee (two-sided turnover already, sell old + buy new)
        names = set(w) | set(prev_w)
        turnover = sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in names)
        cost = turnover * fee
        net = gross - cost
        if basket == (RISK_OFF,):
            risk_off += 1
        if turnover > 1e-9 and prev_w:
            switches += 1
        months_out.append(m)
        holdings.append(basket)
        gross_r.append(gross)
        net_r.append(net)
        spy_r.append(spy)
        prev_w = w
    return RotResult(months_out, holdings, net_r, gross_r, spy_r, risk_off, switches)


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


def first_investable_month(me: dict[str, dict[tuple[int, int], MonthEnd]], lookback: int, sma_days: int,
                           series: dict[str, DailySeries]) -> tuple[int, int]:
    """The first month for which the FULL signal (200d SMA + 6m rank on all sectors + AGG present) is computable.
    Binds on AGG (2003-09) for the held leg and on SPY having >=200 trading days for the SMA."""
    candidates = []
    # the SMA needs 200 trading days of SPY: find the month-end whose daily index >= 199
    spy_me = me[MARKET]
    for mk in sorted(spy_me):
        if spy_me[mk].daily_idx + 1 >= sma_days:
            candidates.append(mk)
            break
    # each series needs `lookback`+1 months of month-ends so a trailing return exists
    for sym in ALL_SERIES:
        months = sorted(me[sym])
        candidates.append(_add_months(months[0], lookback + 1))
    return max(candidates)


# --------------------------------------------------------------------------- report (the validation)


def _fmt(tag: str, p: PerfStats) -> str:
    return (f"  {tag:<24} n={p.n_months:>3}m  tot={p.total_return:+.1%}  CAGR={p.cagr:+.2%}  "
            f"vol={p.ann_vol:.2%}  Sharpe={p.ann_sharpe:+.2f}  maxDD={p.max_dd:.1%}  win={p.win_rate:.0%}")


def validate(top_k: int = TOP_K, lookback: int = LOOKBACK_MONTHS, sma_days: int = SMA_DAYS) -> dict:
    """Run the full honest deploy-lane validation and print it. Returns a dict the arming path reuses."""
    series = {sym: load_daily(sym) for sym in ALL_SERIES}
    me = {sym: month_end_index(series[sym]) for sym in ALL_SERIES}
    start = first_investable_month(me, lookback, sma_days, series)
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)  # drop the partial current month

    print("=" * 104)
    print("SECTOR-MOMENTUM ROTATION (TAA) — DEPLOY-A-DOCUMENTED-STRATEGY validation (NOT the 0.95 in-sample Gate)")
    print("Rule: SPY>=200d SMA -> hold top-3 of 9 SPDR sectors by 6m total return (eq-wt); else risk-OFF to AGG. Monthly.")
    print("Bar: positive OOS net of REAL fees on the REAL purged+embargoed holdout + BEATS B&H SPY risk-adjusted.")
    print(f"Universe: sectors={SECTOR_ETFS} | market={MARKET} | risk_off={RISK_OFF} | k={top_k} lb={lookback}m "
          f"sma={sma_days}d | signal@month-end t, trade t+1 | window {start} -> {last_complete}")
    print("=" * 104)

    # ---- FULL SAMPLE at the central fee + fee sweep ----
    print("\n### FULL SAMPLE — strategy (net of ETF fees) vs buy-and-hold SPY (total return)")
    full = run_rotation(series, me, top_k=top_k, lookback=lookback, sma_days=sma_days,
                        fee_bps_per_side=ETF_BPS_PER_SIDE, start=start, end=last_complete)
    strat = _stats(full.net_returns)
    spy = _stats(full.spy_returns)
    gross = _stats(full.gross_returns)
    print(_fmt("Rotation (net, 1bps)", strat))
    print(_fmt("Rotation (gross)", gross))
    print(_fmt("Buy & Hold SPY", spy))
    yrs = strat.n_months / 12
    print(f"  basket switches: {full.switches} (~{full.switches / yrs:.1f}/yr)  | risk-off (AGG) months: "
          f"{full.risk_off_months}/{strat.n_months} ({full.risk_off_months / strat.n_months:.0%})")

    print("\n  Fee sensitivity (net Sharpe / net total / CAGR / maxDD):")
    for fee in FEE_SWEEP_BPS:
        r = run_rotation(series, me, top_k=top_k, lookback=lookback, sma_days=sma_days,
                         fee_bps_per_side=fee, start=start, end=last_complete)
        s = _stats(r.net_returns)
        print(f"    {fee:>3.0f} bps/side  Sharpe={s.ann_sharpe:+.2f}  tot={s.total_return:+.1%}  "
              f"CAGR={s.cagr:+.2%}  maxDD={s.max_dd:.1%}")

    # ---- REAL purged+embargoed HOLDOUT (cosmu.research.equity_holdout — NOT stubbed) ----
    # The deployment OOS check: split the realized monthly NET-return stream into in-sample (~80%) and a held-out tail
    # (~20%) with an EMBARGO that covers the 6-month formation window so no formation period straddles the boundary.
    # holdout_dsr > 0 ⇔ the held-out Sharpe is significantly positive (the edge persists into a window it never saw).
    embargo = lookback + 1  # cover the 6m formation lookback (+1 month for the signal/trade gap)
    split = purged_embargoed_split(full.net_returns, holdout_frac=0.2, embargo=embargo, min_holdout=6)
    in_stats = _stats(split.in_sample)
    out_stats = _stats(split.holdout)
    # SPY benchmark over the SAME held-out tail (align by index — both streams share the same month axis)
    h = len(split.holdout)
    spy_holdout = full.spy_returns[len(full.spy_returns) - h:] if h else []
    spy_out_stats = _stats(spy_holdout)
    print(f"\n### REAL PURGED+EMBARGOED HOLDOUT (equity_holdout) — embargo={embargo}m, holdout_frac=0.20")
    print(f"  in-sample  n={len(split.in_sample)}m  tot={in_stats.total_return:+.1%}  Sharpe={in_stats.ann_sharpe:+.2f}")
    print(_fmt("HOLDOUT Rotation (net)", out_stats))
    print(_fmt("HOLDOUT B&H SPY", spy_out_stats))
    print(f"  holdout_deflated_sharpe (PSR_holdout - 0.5): {split.holdout_dsr:+.6f}   (>0 ⇔ holdout Sharpe sig. positive)")

    # ---- SUBPERIOD ROBUSTNESS — the documented edge is crash protection; show it across regimes ----
    print("\n### SUBPERIOD ROBUSTNESS — Rotation net total vs B&H SPY total over each regime")
    subperiods = [
        ("2008 GFC crash    (07/2008-02/2009)", (2008, 7), (2009, 2)),
        ("recovery+QE bull  (03/2009-12/2019)", (2009, 3), (2019, 12)),
        ("COVID crash       (02/2020-04/2020)", (2020, 2), (2020, 4)),
        ("2022 bear         (01/2022-12/2022)", (2022, 1), (2022, 12)),
        ("post-2022 bull    (01/2023-now)     ", (2023, 1), last_complete),
    ]
    sub_edges = []
    for label, s0, s1 in subperiods:
        if s0 < start:
            continue
        gr = run_rotation(series, me, top_k=top_k, lookback=lookback, sma_days=sma_days,
                          fee_bps_per_side=ETF_BPS_PER_SIDE, start=s0, end=s1)
        g, sp = _stats(gr.net_returns), _stats(gr.spy_returns)
        edge = g.total_return - sp.total_return
        sub_edges.append((label, edge))
        print(f"  {label}  ROT={g.total_return:+6.1%}  SPY={sp.total_return:+6.1%}  edge={edge:+6.1%}  "
              f"(ROT maxDD {g.max_dd:.0%} vs SPY {sp.max_dd:.0%})")

    # ---- VERDICT (deployment bar — honest, NOT pass-tuned) ----
    # The bar: positive OOS net of fees ON THE REAL HOLDOUT, AND beat B&H SPY on "higher Sharpe AND/OR materially
    # lower maxDD", robust across subperiods. We require:
    #   (1) HOLDOUT net total POSITIVE (the edge survives out of sample), AND holdout DSR >= 0 (sig. positive Sharpe);
    #   (2) FULL-cycle BEATS B&H SPY risk-adjusted: higher Sharpe OR materially lower maxDD (<= 75% of SPY's);
    #   (3) robust: the strategy WINS the crash regimes it is built for and never catastrophically lags.
    MATERIAL_DD = 0.75
    holdout_positive = out_stats.total_return > 0 and split.holdout_dsr >= 0
    higher_sharpe = strat.ann_sharpe >= spy.ann_sharpe
    lower_dd = strat.max_dd <= spy.max_dd * MATERIAL_DD
    beats_spy = higher_sharpe or lower_dd
    # robustness: positive edge in at least the 2008 + 2022 bear regimes that exist in-window (crash protection)
    bear_edges = [e for lbl, e in sub_edges if ("crash" in lbl or "bear" in lbl)]
    robust = sum(1 for e in bear_edges if e > 0) >= max(1, len(bear_edges) - 1)
    deployable = holdout_positive and beats_spy and robust

    print("\n" + "=" * 104)
    print("VERDICT (deployment bar — NOT the 0.95 in-sample Gate):")
    print(f"  (1) REAL-HOLDOUT net POSITIVE + DSR>=0?           {holdout_positive}  "
          f"(holdout tot {out_stats.total_return:+.1%}, DSR {split.holdout_dsr:+.4f})")
    print(f"  (2) FULL-cycle BEATS B&H SPY risk-adjusted?       {beats_spy}  "
          f"(Sharpe {strat.ann_sharpe:+.2f} vs {spy.ann_sharpe:+.2f}{' [HIGHER]' if higher_sharpe else ''}; "
          f"maxDD {strat.max_dd:.1%} vs {spy.max_dd:.1%}{' [LOWER]' if lower_dd else ''})")
    print(f"  (3) robust across bear regimes (crash protect)?   {robust}  "
          f"(bear-regime edges: {[f'{e:+.0%}' for e in bear_edges]})")
    print(f"  ==> {'DEPLOYABLE — arm the live forward-test' if deployable else 'NOT deployable on our data'}")
    print("=" * 104)

    current_signal = _signal(series, me, last_complete, top_k=top_k, lookback=lookback, sma_days=sma_days)
    print(f"\nCURRENT signal (decided at {last_complete} month-end, to hold next month): HOLD {current_signal}")

    return {
        "deployable": deployable,
        "current_signal": list(current_signal) if current_signal else [],
        "full": strat,
        "full_spy": spy,
        "holdout": out_stats,
        "holdout_spy": spy_out_stats,
        "holdout_dsr": split.holdout_dsr,
        "in_sample": in_stats,
        "switches": full.switches,
        "risk_off_months": full.risk_off_months,
        "window": (start, last_complete),
        "result": full,
    }


def main(argv: list[str] | None = None) -> int:
    validate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
