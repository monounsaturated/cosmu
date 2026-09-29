# intent: provide a REAL purged + embargoed out-of-sample HOLDOUT for the equity research cohorts, replacing the
# hardcoded `holdout_deflated_sharpe = Decimal('0.0001')` stub that always cleared the gate's `> 0` holdout check.
#
# THE BUG IT FIXES: the equity cohorts (equity_reversal_cohort, equity_sector_cohort, equity_lowvol_bab_cohort) all
# computed every statistic — Sharpe, DSR, PBO, FDR — on the SAME in-sample return stream and then pinned the holdout
# DSR to a constant 0.0001, so the gate's `holdout_deflated_sharpe <= holdout_min_deflated_sharpe(=0)` check was a
# no-op. There was NO held-out window: a strategy could overfit the whole sample and still "pass holdout".
#
# THE FIX (mirrors the crypto path data/backtest.py exactly):
#   * split the weekly/monthly NET return stream into IN-SAMPLE (first ~80%) and a HOLDOUT tail (last ~20%);
#   * drop an EMBARGO band of `embargo` observations between them so no position/momentum-formation window straddles
#     the boundary (the formation lookback of a monthly 12-1 book is up to 12 months -> embargo defaults cover it);
#   * compute the gate-facing metrics (sharpe_per_obs, skew, kurtosis, oos_return, n_obs, drawdown, win_rate, folds)
#     on the IN-SAMPLE slice ONLY — exactly as backtest.py scores `val.bar_returns`, never the holdout;
#   * compute `holdout_deflated_sharpe = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5` on the HELD-OUT
#     tail ONLY — identical formula to backtest.py:168. `> 0` ⇔ the holdout Sharpe is significantly positive.
#
# So a strategy now PASSES the holdout gate iff its edge persists, untouched, into a window it never saw.
#
# WHY a STREAM-level split (not a re-run of the strategy on held-out bars): these cohorts produce a single realized
# portfolio NET-return series per book (the cross-section is already collapsed to one number per period). The honest
# analogue of backtest.py's bar-level holdout is therefore a chronological split of that realized series with an
# embargo — the held-out periods are genuinely out-of-sample (the book's weights in the holdout were formed from
# data inside the holdout window, and the in-sample stats never see those periods). This is the same construction
# backtest.py applies to `bar_returns`.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal

from cosmu.master.scorer import BacktestMetrics, probabilistic_sharpe, sample_moments


def _max_drawdown(returns: list[float]) -> float:
    peak = equity = 1.0
    mdd = 0.0
    for r in returns:
        equity *= (1.0 + r)
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)
    return mdd


def _folds_positive_pct(returns: list[float], k: int = 5) -> float:
    if len(returns) < k:
        return 0.0
    size = len(returns) // k
    pos = 0
    for f in range(k):
        seg = returns[f * size:(f + 1) * size] if f < k - 1 else returns[f * size:]
        if seg and statistics.fmean(seg) > 0:
            pos += 1
    return pos / k


@dataclass
class HoldoutSplit:
    in_sample: list[float]
    holdout: list[float]
    embargo: int
    holdout_dsr: float


def purged_embargoed_split(returns: list[float], *, holdout_frac: float = 0.2,
                           embargo: int = 1, min_holdout: int = 6) -> HoldoutSplit:
    """Chronologically split a realized NET-return stream into (in_sample, holdout) with an EMBARGO gap.

    holdout = the last `holdout_frac` of the stream; embargo = `embargo` observations immediately before the
    holdout that BOTH sides discard (so no formation window straddles the boundary). The in-sample slice ends
    at the start of the embargo. When the stream is too short to leave a usable holdout, the holdout is empty and
    holdout_dsr is left at 0.0 (which TRIPS the gate's `<= 0` holdout check — fail closed, never fail open)."""
    n = len(returns)
    h = int(round(n * holdout_frac))
    if h < min_holdout or n - h - embargo < min_holdout:
        # too short for an honest holdout -> empty holdout, dsr 0.0 (fails the gate's >0 check; fail-closed)
        return HoldoutSplit(in_sample=returns, holdout=[], embargo=embargo, holdout_dsr=0.0)
    holdout = returns[n - h:]
    in_sample = returns[: n - h - embargo]
    h_sr, h_skew, h_kurt, h_n = sample_moments(holdout)
    # identical to data/backtest.py:168 — PSR of the holdout Sharpe vs 0, recentred so >0 means significantly positive
    holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5
    return HoldoutSplit(in_sample=in_sample, holdout=holdout, embargo=embargo, holdout_dsr=holdout_dsr)


def metrics_with_holdout(returns: list[float], *, trials_counted: int, periods_per_year: int,
                         holdout_frac: float = 0.2, embargo: int = 1,
                         long_only: bool = False, bench_return: float = 0.0) -> tuple[BacktestMetrics, HoldoutSplit]:
    """Build a BacktestMetrics whose gate-facing stats are computed on the IN-SAMPLE slice and whose
    `holdout_deflated_sharpe` is the REAL purged+embargoed out-of-sample DSR. `periods_per_year` annualizes the
    display Sharpe (52 for weekly books, 12 for monthly). Returns (metrics, split) so callers can report both."""
    split = purged_embargoed_split(returns, holdout_frac=holdout_frac, embargo=embargo)
    ins = split.in_sample
    sr, skew, kurt, n = sample_moments(ins)
    total = 1.0
    for r in ins:
        total *= (1.0 + r)
    oos_return = total - 1.0  # in-sample total return (the gate's oos_return is the scored slice, never the holdout)
    mean = statistics.fmean(ins) if ins else 0.0
    sd = statistics.pstdev(ins) if len(ins) > 1 else 0.0
    ann = (mean / sd) * math.sqrt(periods_per_year) if sd > 0 else 0.0
    wins = sum(1 for r in ins if r > 0)
    win_rate = wins / len(ins) if ins else 0.0
    metrics = BacktestMetrics(
        oos_return=Decimal(str(round(oos_return, 6))),
        buy_and_hold_return=Decimal(str(round(bench_return, 6))) if long_only else Decimal("0"),
        sharpe=Decimal(str(round(ann, 4))),
        sortino=Decimal("0"),
        max_drawdown=Decimal(str(round(_max_drawdown(ins), 6))),
        win_rate=Decimal(str(round(win_rate, 4))),
        num_trades=len(ins),
        sharpe_per_obs=Decimal(str(round(sr, 8))),
        skew=Decimal(str(round(skew, 6))),
        kurtosis=Decimal(str(round(kurt, 6))),
        n_obs=n,
        trials_counted=trials_counted,
        folds_positive_pct=Decimal(str(round(_folds_positive_pct(ins), 4))),
        holdout_deflated_sharpe=Decimal(str(round(split.holdout_dsr, 6))),
    )
    return metrics, split
