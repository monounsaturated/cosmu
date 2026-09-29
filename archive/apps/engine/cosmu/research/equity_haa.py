# intent: DEPLOY-A-DOCUMENTED-STRATEGY track — Wouter Keller & Jan Willem Keuning's HYBRID ASSET ALLOCATION
# (HAA), from "Relative and Absolute Momentum in Times of Rising/Low Yields: Hybrid Asset Allocation (HAA)" (2023),
# the successor to their DAA/BAA. Externally validated, published, widely replicated. A documented monthly
# cross-asset rotation — it does NOT need our in-sample 0.95 Gate to "discover" it; the appropriate validators are
# (a) the external literature, (b) a positive OOS-net-of-fees check that beats B&H SPY risk-adjusted, (c) the live
# paper. This module composes DAA's PIT primitives (load_monthly / _trailing_return / _realized_return /
# _add_months / _stats — never re-derives a price) and is what `equity_taa_cohort` routes through the strict Gate.
#
# THE RULE (monthly; signal at month-end t from completed-month closes, trade t+1 — NO look-ahead):
#   OFFENSIVE universe (N=8): {SPY, IWM, EFA, EEM, VNQ, DBC, IEF, TLT}   (EFA≈VEA, EEM≈VWO proxies, as our siblings)
#   CANARY (single): TIP        # the crash detector — HAA uses ONE canary (inflation-protected Treasuries)
#   CASH/DEFENSIVE: {BIL, IEF}  # park here when risk-off or a slot's own momentum is non-positive (best by score)
#   Momentum score = mean of the trailing 1/3/6/12-month TOTAL returns  (Keller's HAA SIMPLE-average momentum,
#                                                                        NOT DAA's 13612W weighting — the distinction).
#   1. If the CANARY (TIP) momentum <= 0  ->  risk-OFF: 100% into the best CASH asset (max score of {BIL, IEF}).
#   2. Else risk-ON: hold the TOP_T offensive assets by score, equal-weight (1/T each). For EACH selected slot, if
#      that asset's OWN momentum is <= 0 the slot goes to the best CASH asset instead (absolute-momentum filter).
#   This is canonical HAA-Balanced (T=4): a single inflation canary gates risk-on/off, relative momentum picks the
#   strongest real-asset basket, and per-slot absolute momentum bleeds individual losers to cash. The documented
#   payoff is a high full-cycle Sharpe with a shallow drawdown across both rising- and low-yield regimes.
#
# DATA: TOTAL-RETURN (adjusted-close) MONTHLY bars from the equities cache `*_tr.json`. FEES: REAL IBKR ~1 bp/side
#   on liquid ETFs, charged on one-sided turnover. Propose/measure-only — moves no money.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime

from cosmu.research.equity_daa import (
    IBKR_ETF_BPS_PER_SIDE,
    MonthlySeries,
    PerfStats,
    _add_months,
    _realized_return,
    _stats,
    _trailing_return,
    load_monthly,
)

# HAA-Balanced universe.
RISK_UNIVERSE = ["SPY", "IWM", "EFA", "EEM", "VNQ", "DBC", "IEF", "TLT"]  # offensive (8)
CANARY = "TIP"                  # single inflation canary
CASH = ["BIL", "IEF"]           # defensive cash proxies (hold the best by score)
BENCHMARK = "SPY"
TOP_T = 4                       # HAA-Balanced holds the top-4 offensive (HAA-Simple = 1)
HAA_SERIES = sorted(set([*RISK_UNIVERSE, CANARY, *CASH, BENCHMARK]))

LOOKBACKS = [1, 3, 6, 12]       # simple-average momentum (Keller HAA): mean of trailing 1/3/6/12-mo total returns
MAX_LOOKBACK = 12
FEE_SWEEP_BPS = [1.0, 2.0, 3.0, 5.0]


def _score(series: dict[str, MonthlySeries], symbol: str, asof: tuple[int, int]) -> float | None:
    """HAA momentum: the MEAN of the trailing 1/3/6/12-month total returns at month-end `asof`. None if ANY of the
    four trailing windows is unavailable (no fabricated partial score — fail closed)."""
    s = series[symbol]
    parts: list[float] = []
    for lb in LOOKBACKS:
        r = _trailing_return(s, asof, lb)
        if r is None:
            return None
        parts.append(r)
    return statistics.fmean(parts)


def _best_cash(series: dict[str, MonthlySeries], asof: tuple[int, int]) -> str | None:
    best, best_score = None, -math.inf
    for sym in CASH:
        sc = _score(series, sym, asof)
        if sc is None:
            return None
        if sc > best_score:
            best_score, best = sc, sym
    return best


def _target_weights(series: dict[str, MonthlySeries], asof: tuple[int, int]) -> dict[str, float] | None:
    """HAA target weights decided at month-end `asof` (held next month). {symbol: weight} summing to ~1, or None
    if any required score is unavailable (fail closed — no partial book, no synthetic fill)."""
    canary = _score(series, CANARY, asof)
    if canary is None:
        return None
    best_cash = _best_cash(series, asof)
    if best_cash is None:
        return None

    weights: dict[str, float] = {}
    if canary <= 0:  # risk-OFF: fully into the best cash asset
        weights[best_cash] = 1.0
        return weights

    # risk-ON: rank the offensive universe by score, hold the top-T equal-weight.
    scores: dict[str, float] = {}
    for sym in RISK_UNIVERSE:
        sc = _score(series, sym, asof)
        if sc is None:
            return None
        scores[sym] = sc
    held = sorted(RISK_UNIVERSE, key=lambda s: scores[s], reverse=True)[:TOP_T]
    per = 1.0 / TOP_T
    for sym in held:
        # per-slot absolute-momentum filter: a selected asset with non-positive own momentum -> that slot to cash.
        target = sym if scores[sym] > 0 else best_cash
        weights[target] = weights.get(target, 0.0) + per
    return weights


@dataclass
class HaaResult:
    months: list[tuple[int, int]]
    weights: list[dict[str, float]]
    net_returns: list[float]
    gross_returns: list[float]
    spy_returns: list[float]
    turnover: float


def run_haa(series: dict[str, MonthlySeries], *, fee_bps_per_side: float = IBKR_ETF_BPS_PER_SIDE,
            start: tuple[int, int] | None = None, end: tuple[int, int] | None = None) -> HaaResult:
    """Run HAA month-by-month, no look-ahead: weights for month M decided from data through M-1 (signal@M-1,
    trade@M); month-M return = weighted blend of held assets' realized returns; fee on one-sided turnover."""
    fee = fee_bps_per_side / 1e4
    months_out: list[tuple[int, int]] = []
    weights_out: list[dict[str, float]] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    spy_r: list[float] = []
    total_turnover = 0.0
    prev_w: dict[str, float] | None = None
    for m in series[BENCHMARK].months:
        if start is not None and m < start:
            continue
        if end is not None and m > end:
            continue
        w = _target_weights(series, _add_months(m, -1))  # decide at the PRIOR month-end (PIT)
        if w is None:
            continue
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
        if prev_w is None:
            turnover = 1.0
        else:
            symbols = set(w) | set(prev_w)
            turnover = 0.5 * sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in symbols)
        total_turnover += turnover
        net = gross - turnover * fee
        months_out.append(m)
        weights_out.append(w)
        gross_r.append(gross)
        net_r.append(net)
        spy_r.append(spy)
        prev_w = w
    return HaaResult(months_out, weights_out, net_r, gross_r, spy_r, total_turnover)


def first_investable_month(series: dict[str, MonthlySeries]) -> tuple[int, int]:
    """First month every HAA series has a full MAX_LOOKBACK trailing window. Binds on the youngest ETF."""
    return max(_add_months(series[sym].months[0], MAX_LOOKBACK + 1) for sym in HAA_SERIES)


def current_weights() -> dict[str, float]:
    series = {sym: load_monthly(sym) for sym in HAA_SERIES}
    today = datetime.now(tz=UTC).date()
    return _target_weights(series, _add_months((today.year, today.month), -1)) or {}


MATERIAL_DD_REDUCTION = 0.75  # "materially lower" drawdown = <= 75% of SPY's, for the deployment-bar risk-adjusted beat


def validate() -> dict:
    """The DEPLOYMENT-bar validation (NOT the 0.95 in-sample Gate). Returns the dict the sibling arm reads:
    `deployable`, `current_weights`, `full`/`oos` PerfStats (+ their SPY benchmarks), `window`, `turnover`."""
    series = {sym: load_monthly(sym) for sym in HAA_SERIES}
    start = first_investable_month(series)
    today = datetime.now(tz=UTC).date()
    last_complete = _add_months((today.year, today.month), -1)
    full = run_haa(series, start=start, end=last_complete)
    haa_stats: PerfStats = _stats(full.net_returns)
    spy_stats = _stats(full.spy_returns)
    n = haa_stats.n_months
    is_end = full.months[n // 2]
    oos_start = _add_months(is_end, MAX_LOOKBACK)
    oos_run = run_haa(series, start=oos_start, end=last_complete)
    oos = _stats(oos_run.net_returns)
    oos_spy = _stats(oos_run.spy_returns)
    # Deployment bar (same as the Keller siblings): OOS positive net of fees, AND OOS risk-adjusted beat of B&H SPY,
    # AND full-cycle risk-adjusted beat. risk-adjusted beat = higher Sharpe OR materially (<=75%) lower maxDD.
    oos_beat = oos.ann_sharpe >= oos_spy.ann_sharpe or oos.max_dd <= oos_spy.max_dd * MATERIAL_DD_REDUCTION
    full_beat = haa_stats.ann_sharpe >= spy_stats.ann_sharpe or haa_stats.max_dd <= spy_stats.max_dd * MATERIAL_DD_REDUCTION
    deployable = (oos.total_return > 0) and oos_beat and full_beat
    cur = _target_weights(series, last_complete) or {}
    print(f"HAA (Hybrid Asset Allocation, Keller 2023, top-{TOP_T}) — window {start} -> {last_complete}")
    print(f"  FULL  net Sharpe {haa_stats.ann_sharpe:+.2f}  tot {haa_stats.total_return:+.1%}  "
          f"maxDD {haa_stats.max_dd:.1%}  vs B&H SPY Sharpe {spy_stats.ann_sharpe:+.2f} maxDD {spy_stats.max_dd:.1%}")
    print(f"  OOS   net Sharpe {oos.ann_sharpe:+.2f}  tot {oos.total_return:+.1%}  maxDD {oos.max_dd:.1%}")
    print(f"  turnover {full.turnover:.1f} (~{full.turnover/(n/12):.1f}/yr)  ==> {'DEPLOYABLE' if deployable else 'NOT deployable'}")
    return {"deployable": deployable, "current_weights": cur, "full": haa_stats, "full_spy": spy_stats,
            "oos": oos, "oos_spy": oos_spy, "window": (start, last_complete), "turnover": full.turnover, "result": full}


def main() -> int:
    validate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
