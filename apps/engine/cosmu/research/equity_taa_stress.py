# intent: a WORST-REGIME stress instrument for the equity-TAA Gate survivors (the only full-Gate cohort:
# DAA/VAA/ADM strict + PAA/GTAA/RiskParity/TSMOM/HAA DSR+holdout). The deterministic Gate scores the AVERAGE
# edge of a single realized net-return stream; the killers (cross-disciplinary playbook 2026-06-26, red-team #7
# + #10) live in the WORST volatility regime and in a FORCED exit, neither of which a single-snapshot Sharpe
# can see. This module measures three things the Gate structurally cannot, WITHOUT touching a single Gate
# threshold (it INFORMS — it never disposes, never funds, never moves money):
#
#   (1) WORST-REGIME net-of-fee Sharpe (red-team #7). Split each survivor's realized OOS+holdout months into
#       volatility regimes (calm/normal/stress = terciles of the trailing realized vol of the shared SPY
#       benchmark, PIT) and report the MINIMUM annualized net Sharpe across regimes, NOT the average. A
#       survivor whose worst-regime Sharpe is materially negative is fragile exactly where it must not be.
#
#   (2) LTCM FORCED-EXIT re-pricing (red-team #10). Recover each month's realized rebalance cost as
#       (gross - net), then re-price the cost of the rotations that fall in a stress regime at 3-5x calm
#       slippage into a ONE-SIDED book (an extra adverse-fill penalty, because the whole defensive-TAA cohort
#       de-risks the SAME way at the SAME time when the canary trips). Recompute the stress-regime Sharpe under
#       that forced cost, and — given a book notional + a stress-haircut ADV — confirm the position is exitable
#       within K bars. Flag any survivor whose stressed exit erases its edge or cannot clear within K bars.
#
#   (3) STRESS-regime correlation (red-team #6 + #10). Estimate pairwise survivor correlation on STRESS months
#       only (not calm-blended full-sample), because the ensemble's "diversification" is a calm-data artefact:
#       three differently-triggered defensive rotations that all key off the same momentum + canary breadth
#       collapse toward one trade when the canary trips. Flag clusters whose stress-regime correlation > 0.70.
#
# inputs: the SAME realized monthly net/gross/bench streams the cohort + deploy arms use (equity_taa_cohort.
#         build_streams — total-return, net of REAL IBKR fees, PIT, no look-ahead). NO new data, NO refit.
# outputs: a StressVerdict (per-survivor regime Sharpes, worst regime, forced-exit feasibility, flags) + a
#          cohort stress-correlation report. Optional markdown findings export (--report).
# invariants: Gate constants are LOCKED and untouched (this module imports NO GateSettings, calls NO score()/
#         promote_cohort); deterministic for fixed cached data (no RNG, no network, no clock in the math);
#         all thresholds are NAMED HARNESS parameters (not Gate constants) and overridable per run; propose/
#         measure-only — moves no money, writes no disposition.

from __future__ import annotations

import math
import statistics
import sys
from dataclasses import dataclass, field

from cosmu.master.scorer import sample_moments
from cosmu.master.strategy_correlation import CorrelationReport, pairwise_correlation
from cosmu.research.equity_holdout import _max_drawdown, purged_embargoed_split
from cosmu.research.equity_taa_cohort import (
    EMBARGO_MONTHS,
    HOLDOUT_FRAC,
    PERIODS_PER_YEAR,
    StratStreams,
    build_streams,
)

# --------------------------------------------------------------------------------------------------------------
# HARNESS PARAMETERS — named, documented, overridable. These are the STRESS instrument's own dials; NONE of them
# is a Gate threshold (the Gate is locked elsewhere and unchanged). Tune via run()/CLI, not by editing the Gate.
# --------------------------------------------------------------------------------------------------------------

VOL_WINDOW = 6                  # trailing months used to estimate the regime's realized vol (PIT, ends at t-1)
REGIME_NAMES: tuple[str, str, str] = ("calm", "normal", "stress")  # terciles of trailing vol (low -> high)
STRESS_REGIME = "stress"        # the high-vol tercile — the regime the Gate's averaging hides

# LTCM forced-exit (red-team #10): calm IBKR all-in on liquid ETFs ~1 bp/side; under a forced de-risk the
# SLIPPAGE leg blows out 3-5x and the book crosses a ONE-SIDED book (everyone selling the same risk assets).
SLIP_MULT_BAND: tuple[float, float, float] = (3.0, 4.0, 5.0)
DEFAULT_SLIP_MULT = 4.0         # midpoint of the 3-5x band, used for the headline row
ONE_SIDED_PENALTY = 1.5         # extra adverse-fill multiplier when the cohort de-risks the same way at once
STRESS_LIQUIDITY_HAIRCUT = 0.5  # a stress regime trades at ~half the calm ADV (documented; override per run)
DEFAULT_PARTICIPATION_CAP = 0.10  # max fraction of a bar's ADV you can take in one bar without further impact
DEFAULT_K_BARS = 1              # a MONTHLY rotation must be fully exitable within K monthly bars

# Flag thresholds (harness, not Gate). "materially negative" => annualized Sharpe below -WORST_REGIME_MATERIALITY.
WORST_REGIME_MATERIALITY = 0.25  # |annualized SR| beyond which a negative worst-regime Sharpe is "material"
CROWDING_RHO = 0.70             # red-team #6/#10: a stress-regime cluster above this is "one trade under stress"
MIN_REGIME_MONTHS = 6           # below this a per-regime Sharpe is noise (reported, not flagged)
MIN_CORR_OVERLAP = 20           # below this overlap a stress-regime correlation is NaN (mirrors strategy_correlation)


# --------------------------------------------------------------------------------------------------------------
# Volatility-regime labelling (point-in-time)
# --------------------------------------------------------------------------------------------------------------


def _trailing_vol(returns: list[float], t: int, window: int) -> float:
    """Realized vol the market is IN as month `t` OPENS — pstdev of the `window` benchmark returns BEFORE t (PIT,
    no look-ahead into month t itself). For the first months (no trailing window yet) fall back to the earliest
    estimable 2-month window so every month gets a value and none is dropped."""
    seg = returns[max(0, t - window):t]
    if len(seg) < 2:
        seg = returns[:2]
    return statistics.pstdev(seg) if len(seg) >= 2 else 0.0


def vol_regime_labels(bench_returns: list[float], *, window: int = VOL_WINDOW,
                      names: tuple[str, str, str] = REGIME_NAMES) -> list[str]:
    """Label each month by the volatility regime it opened in, from the trailing realized vol of the SHARED
    benchmark (SPY). Each month's vol VALUE is PIT (trailing, ends at t-1); the tercile CUTS that turn the vol
    series into calm/normal/stress are taken over the whole window — a retrospective DIAGNOSTIC partition (this
    is a stress attribution, not a tradeable signal), so using the full vol distribution to define "what counts
    as a stress month" is the standard regime-conditional construction. Returns one label per input month."""
    n = len(bench_returns)
    if n == 0:
        return []
    vols = [_trailing_vol(bench_returns, t, window) for t in range(n)]
    ordered = sorted(vols)
    q1 = ordered[n // 3] if n >= 3 else ordered[0]
    q2 = ordered[(2 * n) // 3] if n >= 3 else ordered[-1]
    out: list[str] = []
    for v in vols:
        if v <= q1:
            out.append(names[0])
        elif v <= q2:
            out.append(names[1])
        else:
            out.append(names[2])
    return out


# --------------------------------------------------------------------------------------------------------------
# Per-regime net-of-fee Sharpe
# --------------------------------------------------------------------------------------------------------------


def _ann_sharpe(returns: list[float], periods_per_year: int) -> float:
    """Annualized net Sharpe, identical convention to equity_holdout.metrics_with_holdout / scorer.sample_moments
    (per-observation mean/pstdev, annualized by sqrt(periods)). 0.0 when fewer than 2 obs or zero dispersion."""
    sr, _skew, _kurt, n = sample_moments(returns)
    return sr * math.sqrt(periods_per_year) if n >= 2 else 0.0


def _total_return(returns: list[float]) -> float:
    total = 1.0
    for r in returns:
        total *= (1.0 + r)
    return total - 1.0


@dataclass(frozen=True)
class RegimeSharpe:
    regime: str
    n_months: int
    ann_sharpe: float
    mean_monthly: float
    total_return: float
    max_drawdown: float


def regime_sharpes(returns: list[float], labels: list[str], *, periods_per_year: int = PERIODS_PER_YEAR,
                   names: tuple[str, str, str] = REGIME_NAMES) -> list[RegimeSharpe]:
    """Split `returns` by `labels` (parallel arrays) and compute the annualized net Sharpe WITHIN each regime.
    A regime with no months is omitted; one with <2 months has ann_sharpe 0.0 (reported, never flagged)."""
    if len(returns) != len(labels):
        raise ValueError(f"returns ({len(returns)}) and labels ({len(labels)}) must be parallel")
    out: list[RegimeSharpe] = []
    for regime in names:
        seg = [r for r, lab in zip(returns, labels, strict=True) if lab == regime]
        if not seg:
            continue
        out.append(RegimeSharpe(
            regime=regime,
            n_months=len(seg),
            ann_sharpe=round(_ann_sharpe(seg, periods_per_year), 4),
            mean_monthly=round(statistics.fmean(seg), 6),
            total_return=round(_total_return(seg), 6),
            max_drawdown=round(_max_drawdown(seg), 6),
        ))
    return out


def worst_regime(regimes: list[RegimeSharpe], *, min_months: int = MIN_REGIME_MONTHS) -> RegimeSharpe | None:
    """The regime with the MINIMUM annualized net Sharpe, restricted to regimes with enough months to be a real
    estimate (>= min_months). None when no regime qualifies."""
    eligible = [r for r in regimes if r.n_months >= min_months]
    return min(eligible, key=lambda r: r.ann_sharpe) if eligible else None


# --------------------------------------------------------------------------------------------------------------
# LTCM forced-exit re-pricing (red-team #10)
# --------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ForcedExit:
    slip_mult: float
    one_sided_penalty: float
    stress_months: int
    calm_cost_annualized: float       # the calm rebalance drag already inside `net`, annualized (diagnostic)
    extra_drag_annualized: float      # ADDITIONAL annualized drag from re-pricing stress-month exits
    stress_sharpe_base: float         # stress-regime ann net Sharpe at calm cost (the baseline `net` carries)
    stress_sharpe_forced: float       # stress-regime ann net Sharpe AFTER the forced-exit re-pricing
    bars_to_exit: float               # bars needed to liquidate the book at stress ADV (nan if no capacity input)
    feasible_within_k: bool | None    # bars_to_exit <= k_bars; None when capacity inputs were not supplied


def reprice_forced_exit(net: list[float], gross: list[float], labels: list[str], *,
                        slip_mult: float = DEFAULT_SLIP_MULT, one_sided_penalty: float = ONE_SIDED_PENALTY,
                        periods_per_year: int = PERIODS_PER_YEAR, stress_regime: str = STRESS_REGIME,
                        k_bars: int = DEFAULT_K_BARS, book_notional_usd: float | None = None,
                        adv_usd: float | None = None, participation_cap: float = DEFAULT_PARTICIPATION_CAP,
                        stress_liquidity_haircut: float = STRESS_LIQUIDITY_HAIRCUT) -> ForcedExit | None:
    """Re-price the EXITS (the rotation cost) that fall in a stress regime.

    The realized monthly rebalance cost is recovered as cost_t = max(0, gross_t - net_t) — the calm slippage+fee
    the backtest already charged. In a stress month, re-price that cost at `slip_mult`x into a ONE-SIDED book:
        extra_t = cost_t * (slip_mult - 1) * one_sided_penalty   (calm/normal months unchanged)
        forced_net_t = net_t - extra_t
    Then recompute the STRESS-regime annualized net Sharpe under `forced_net`. Returns None when no aligned gross
    stream is available (e.g. a disconfirmer) so the caller can skip the row.

    K-bar feasibility: when a book notional + an ADV are supplied, bars_to_exit = ceil(notional / (cap * ADV *
    haircut)); feasible iff <= k_bars. Without those inputs (this cloud env has no equity ADV feed — Yahoo is
    policy-denied) bars_to_exit is nan and feasible_within_k is None (cannot measure -> never falsely flagged)."""
    if not gross or len(gross) != len(net) or len(net) != len(labels):
        return None
    forced_net: list[float] = []
    extras: list[float] = []
    costs: list[float] = []
    for n_r, g_r, lab in zip(net, gross, labels, strict=True):
        cost = max(0.0, g_r - n_r)
        costs.append(cost)
        if lab == stress_regime:
            extra = cost * (slip_mult - 1.0) * one_sided_penalty
        else:
            extra = 0.0
        extras.append(extra)
        forced_net.append(n_r - extra)

    stress_base = [n_r for n_r, lab in zip(net, labels, strict=True) if lab == stress_regime]
    stress_forced = [n_r for n_r, lab in zip(forced_net, labels, strict=True) if lab == stress_regime]

    bars_to_exit = float("nan")
    feasible: bool | None = None
    if book_notional_usd is not None and adv_usd is not None:
        per_bar = participation_cap * adv_usd * stress_liquidity_haircut
        bars_to_exit = math.ceil(book_notional_usd / per_bar) if per_bar > 0 else float("inf")
        feasible = bars_to_exit <= k_bars

    return ForcedExit(
        slip_mult=slip_mult,
        one_sided_penalty=one_sided_penalty,
        stress_months=len(stress_base),
        calm_cost_annualized=round(statistics.fmean(costs) * periods_per_year, 6) if costs else 0.0,
        extra_drag_annualized=round(statistics.fmean(extras) * periods_per_year, 6) if extras else 0.0,
        stress_sharpe_base=round(_ann_sharpe(stress_base, periods_per_year), 4),
        stress_sharpe_forced=round(_ann_sharpe(stress_forced, periods_per_year), 4),
        bars_to_exit=bars_to_exit,
        feasible_within_k=feasible,
    )


# --------------------------------------------------------------------------------------------------------------
# Stress-regime correlation (red-team #6 + #10)
# --------------------------------------------------------------------------------------------------------------


def regime_correlation(streams_on_common: dict[str, list[float]], labels: list[str], regime: str, *,
                       redundancy_threshold: float = CROWDING_RHO,
                       min_overlap: int = MIN_CORR_OVERLAP) -> CorrelationReport:
    """Pairwise correlation among survivors RESTRICTED to `regime` months. Each value in `streams_on_common` is a
    survivor's net stream already aligned index-for-index to `labels` (the common-month calendar). Filtering to
    the regime keeps every survivor's list the same length and index-aligned, so strategy_correlation's
    trailing-suffix overlap is an exact same-month join. Uses the crowding threshold (0.70), NOT the 0.85
    redundancy default — a stress cluster above 0.70 is the 'one trade under stress' failure mode."""
    filtered = {
        name: [r for r, lab in zip(series, labels, strict=True) if lab == regime]
        for name, series in streams_on_common.items()
    }
    return pairwise_correlation(filtered, redundancy_threshold=redundancy_threshold, min_overlap=min_overlap)


# --------------------------------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StressRow:
    name: str
    label: str
    is_disconfirmer: bool
    n_months: int
    full_sample_sharpe: float          # the AVERAGE edge the Gate effectively scores (whole net stream, annualized)
    regimes: list[RegimeSharpe]
    worst_regime_name: str
    worst_regime_sharpe: float
    holdout_worst_regime_name: str     # worst regime WITHIN the embargoed holdout tail (the unseen window)
    holdout_worst_regime_sharpe: float
    forced_exit: ForcedExit | None
    flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StressVerdict:
    n_strategies: int
    window: str
    slip_mult: float
    k_bars: int
    rows: list[StressRow]
    calm_avg_corr: float
    stress_avg_corr: float
    stress_crowded_pairs: list[tuple[str, str, float]]  # (a, b, rho) with rho >= CROWDING_RHO under stress
    flagged: list[str]                  # survivor names flagged fragile (worst-regime / forced-exit)
    verdict: str
    headline: str


# Flag tokens (stable strings the report + tests assert on).
F_WORST_NEG = "WORST_REGIME_NEGATIVE"            # worst-regime ann Sharpe materially below 0
F_WORST_SUBZERO = "WORST_REGIME_SUBZERO"         # worst-regime ann Sharpe negative but within the materiality band
F_EXIT_ERODES = "STRESS_EXIT_ERODES_EDGE"        # forced-exit re-pricing drives the stress Sharpe materially < 0
F_EXIT_INFEASIBLE = "STRESS_EXIT_INFEASIBLE_K_BARS"  # book not exitable within K bars at stress ADV
F_CROWDED = "CROWDED_UNDER_STRESS"               # in a stress cluster with pairwise corr >= CROWDING_RHO


def _flags_for(row_worst: float, holdout_worst: float, fe: ForcedExit | None, *,
               materiality: float) -> list[str]:
    flags: list[str] = []
    worst = min(row_worst, holdout_worst)
    if worst < -materiality:
        flags.append(F_WORST_NEG)
    elif worst < 0.0:
        flags.append(F_WORST_SUBZERO)
    if fe is not None:
        if fe.stress_sharpe_forced < -materiality:
            flags.append(F_EXIT_ERODES)
        if fe.feasible_within_k is False:
            flags.append(F_EXIT_INFEASIBLE)
    return flags


def analyze_streams(streams: list[StratStreams], *, slip_mult: float = DEFAULT_SLIP_MULT,
                    one_sided_penalty: float = ONE_SIDED_PENALTY, k_bars: int = DEFAULT_K_BARS,
                    vol_window: int = VOL_WINDOW, materiality: float = WORST_REGIME_MATERIALITY,
                    crowding_rho: float = CROWDING_RHO,
                    adv_usd_by_name: dict[str, float] | None = None,
                    capital_by_name: dict[str, float] | None = None,
                    participation_cap: float = DEFAULT_PARTICIPATION_CAP,
                    stress_liquidity_haircut: float = STRESS_LIQUIDITY_HAIRCUT) -> StressVerdict:
    """Pure analysis over already-loaded streams (so tests can drive it with synthetic streams, no cache/network).
    `run()` is just build_streams() + this."""
    adv_usd_by_name = adv_usd_by_name or {}
    capital_by_name = capital_by_name or {}

    # One canonical regime label per calendar month from the shared SPY benchmark (merge the bench maps; all SPY).
    spy_by_month: dict[tuple[int, int], float] = {}
    for s in streams:
        for m, b in zip(s.months, s.bench, strict=True):
            spy_by_month.setdefault(m, b)
    all_months = sorted(spy_by_month)
    bench_seq = [spy_by_month[m] for m in all_months]
    label_by_month = dict(zip(all_months, vol_regime_labels(bench_seq, window=vol_window), strict=True))

    rows: list[StressRow] = []
    flagged: list[str] = []
    for s in streams:
        labels = [label_by_month[m] for m in s.months]
        regimes = regime_sharpes(s.net, labels)
        wr = worst_regime(regimes)
        wr_name, wr_sharpe = (wr.regime, wr.ann_sharpe) if wr else ("n/a", 0.0)

        # holdout-tail worst regime: the embargoed last ~20% — the window the strategy never saw.
        split = purged_embargoed_split(s.net, holdout_frac=HOLDOUT_FRAC, embargo=EMBARGO_MONTHS)
        h = len(split.holdout)
        if h:
            hold_labels = labels[len(s.net) - h:]
            hold_regimes = regime_sharpes(split.holdout, hold_labels)
            hwr = worst_regime(hold_regimes, min_months=2)
            hwr_name, hwr_sharpe = (hwr.regime, hwr.ann_sharpe) if hwr else ("n/a", 0.0)
        else:
            hwr_name, hwr_sharpe = ("n/a", 0.0)

        fe = None
        if not s.is_disconfirmer and s.gross:
            fe = reprice_forced_exit(
                s.net, s.gross, labels, slip_mult=slip_mult, one_sided_penalty=one_sided_penalty, k_bars=k_bars,
                book_notional_usd=capital_by_name.get(s.name), adv_usd=adv_usd_by_name.get(s.name),
                participation_cap=participation_cap, stress_liquidity_haircut=stress_liquidity_haircut,
            )

        flags = [] if s.is_disconfirmer else _flags_for(wr_sharpe, hwr_sharpe, fe, materiality=materiality)
        if flags and not s.is_disconfirmer:
            flagged.append(s.name)
        rows.append(StressRow(
            name=s.name, label=s.label, is_disconfirmer=s.is_disconfirmer, n_months=len(s.net),
            full_sample_sharpe=round(_ann_sharpe(s.net, PERIODS_PER_YEAR), 4),
            regimes=regimes, worst_regime_name=wr_name, worst_regime_sharpe=wr_sharpe,
            holdout_worst_regime_name=hwr_name, holdout_worst_regime_sharpe=hwr_sharpe,
            forced_exit=fe, flags=flags,
        ))

    # Cohort stress correlation among the FUNDED survivors (disconfirmers excluded — they are not funded combos).
    survivors = [s for s in streams if not s.is_disconfirmer]
    common = sorted(set.intersection(*[set(s.months) for s in survivors])) if survivors else []
    calm_avg = stress_avg = float("nan")
    crowded: list[tuple[str, str, float]] = []
    if len(survivors) >= 2 and len(common) >= MIN_CORR_OVERLAP:
        common_labels = [label_by_month[m] for m in common]
        streams_on_common = {
            s.name: [dict(zip(s.months, s.net, strict=True))[m] for m in common] for s in survivors
        }
        calm_rep = regime_correlation(streams_on_common, common_labels, "calm", redundancy_threshold=crowding_rho)
        stress_rep = regime_correlation(streams_on_common, common_labels, STRESS_REGIME,
                                        redundancy_threshold=crowding_rho)
        calm_avg = calm_rep.average_pairwise_correlation
        stress_avg = stress_rep.average_pairwise_correlation
        crowded = [(p.strategy_a, p.strategy_b, round(p.correlation, 4))
                   for p in stress_rep.pairs
                   if not math.isnan(p.correlation) and p.correlation >= crowding_rho]
        crowded_names = {n for pair in crowded for n in pair[:2]}
        # attach the crowding flag to each member of a stress cluster (cohort-level finding).
        rows = [
            (r if (r.name not in crowded_names or r.is_disconfirmer)
             else StressRow(**{**r.__dict__, "flags": [*r.flags, F_CROWDED]}))
            for r in rows
        ]
        for r in rows:
            if F_CROWDED in r.flags and r.name not in flagged:
                flagged.append(r.name)

    window = (f"{all_months[0][0]}-{all_months[0][1]:02d} .. {all_months[-1][0]}-{all_months[-1][1]:02d}"
              if all_months else "n/a")

    if any(F_WORST_NEG in r.flags or F_EXIT_INFEASIBLE in r.flags or F_EXIT_ERODES in r.flags for r in rows):
        verdict = "FRAGILE-SURVIVORS"
        bad = sorted({r.name for r in rows
                      if {F_WORST_NEG, F_EXIT_INFEASIBLE, F_EXIT_ERODES} & set(r.flags)})
        headline = (f"{len(bad)} Gate survivor(s) FRAGILE under worst-regime / forced-exit stress: {', '.join(bad)} "
                    f"— the Gate's average-edge view does not see this")
    elif crowded:
        verdict = "CROWDING-WARNING"
        headline = (f"survivors diversify in calm data (avg rho {calm_avg:.2f}) but {len(crowded)} pair(s) crowd to "
                    f">= {crowding_rho:.2f} under STRESS (avg rho {stress_avg:.2f}) — one trade when it matters")
    elif any(r.flags and not r.is_disconfirmer for r in rows):
        verdict = "WATCH"
        headline = "no materially-negative worst regime, but soft sub-zero worst-regime Sharpes present (see flags)"
    else:
        verdict = "ROBUST"
        headline = "every survivor holds a non-negative worst-regime Sharpe and an exitable, edge-positive stressed exit"

    return StressVerdict(
        n_strategies=len(streams), window=window, slip_mult=slip_mult, k_bars=k_bars, rows=rows,
        calm_avg_corr=calm_avg, stress_avg_corr=stress_avg, stress_crowded_pairs=crowded,
        flagged=sorted(set(flagged)), verdict=verdict, headline=headline,
    )


def run(*, slip_mult: float = DEFAULT_SLIP_MULT, k_bars: int = DEFAULT_K_BARS,
        adv_usd_by_name: dict[str, float] | None = None,
        capital_by_name: dict[str, float] | None = None) -> StressVerdict:
    """Load the cohort's realized streams (same loader the Gate cohort + deploy arms use) and stress them.
    Returns INSUFFICIENT-DATA when the equities cache is not present (e.g. this cloud env has no Yahoo egress)."""
    streams = build_streams()
    if len(streams) < 2:
        return StressVerdict(len(streams), "n/a", slip_mult, k_bars, [], float("nan"), float("nan"), [], [],
                             "INSUFFICIENT-DATA",
                             "fewer than 2 strategies loaded (no equities cache on this machine) — reproduce with "
                             "COSMU_EQUITY_CACHE set on the M2 / Modal")
    return analyze_streams(streams, slip_mult=slip_mult, k_bars=k_bars,
                           adv_usd_by_name=adv_usd_by_name, capital_by_name=capital_by_name)


# --------------------------------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------------------------------


def _fmt_regimes(regimes: list[RegimeSharpe]) -> str:
    return "  ".join(f"{r.regime}:{r.ann_sharpe:+.2f}(n={r.n_months})" for r in regimes)


def _print(v: StressVerdict) -> None:
    bar = "=" * 122
    print("\n" + bar)
    print("EQUITY-TAA WORST-REGIME STRESS — minimum (not average) net Sharpe · LTCM forced-exit · stress correlation")
    print(f"  strategies={v.n_strategies}  window={v.window}  slip_mult={v.slip_mult:g}x  K-bars={v.k_bars}  "
          f"(Gate constants LOCKED — this informs, never disposes)")
    print(bar)
    print(f"  {'strategy':<34} {'n':>4} {'avgSR':>6} {'WORST(regime)':>20} {'holdoutWORST':>14} "
          f"{'stressSR→forced':>16} {'bars':>5}  flags")
    for r in v.rows:
        fe = r.forced_exit
        stress_cell = (f"{fe.stress_sharpe_base:+.2f}→{fe.stress_sharpe_forced:+.2f}" if fe else "n/a")
        bars_cell = ("-" if fe is None or math.isnan(fe.bars_to_exit) else f"{fe.bars_to_exit:g}")
        tag = " [disconf]" if r.is_disconfirmer else ""
        worst_cell = f"{r.worst_regime_sharpe:+.2f}({r.worst_regime_name})"
        hold_cell = f"{r.holdout_worst_regime_sharpe:+.2f}({r.holdout_worst_regime_name})"
        print(f"  {r.label[:34]:<34} {r.n_months:>4} {r.full_sample_sharpe:>+6.2f} {worst_cell:>20} "
              f"{hold_cell:>14} {stress_cell:>16} {bars_cell:>5}  {','.join(r.flags)}{tag}")
        if r.regimes:
            print(f"  {'':<34} {_fmt_regimes(r.regimes)}")
    print("-" * 122)
    print(f"  stress-regime correlation: calm avg rho={v.calm_avg_corr:.3f}  stress avg rho={v.stress_avg_corr:.3f}")
    for a, b, rho in v.stress_crowded_pairs:
        print(f"    crowded under stress: {a} ~ {b}  rho={rho:+.3f}")
    print(f"  VERDICT: {v.verdict}")
    print(f"  {v.headline}")
    if v.flagged:
        print(f"  FLAGGED: {', '.join(v.flagged)}")
    print(bar)


def to_markdown(v: StressVerdict) -> str:
    """Render the verdict as a markdown findings table (so the operator's real-data run regenerates the report)."""
    lines: list[str] = []
    lines.append("| strategy | n | avg SR (Gate sees) | WORST-regime SR | holdout WORST SR | "
                 f"stress SR → forced ({v.slip_mult:g}x) | bars-to-exit | flags |")
    lines.append("|---|---:|---:|---|---|---|---:|---|")
    for r in v.rows:
        fe = r.forced_exit
        stress_cell = f"{fe.stress_sharpe_base:+.2f} → {fe.stress_sharpe_forced:+.2f}" if fe else "n/a"
        bars_cell = "—" if fe is None or math.isnan(fe.bars_to_exit) else f"{fe.bars_to_exit:g}"
        worst_cell = f"**{r.worst_regime_sharpe:+.2f}** ({r.worst_regime_name})"
        hold_cell = f"{r.holdout_worst_regime_sharpe:+.2f} ({r.holdout_worst_regime_name})"
        tag = " _(disconfirmer)_" if r.is_disconfirmer else ""
        lines.append(f"| {r.label}{tag} | {r.n_months} | {r.full_sample_sharpe:+.2f} | {worst_cell} | "
                     f"{hold_cell} | {stress_cell} | {bars_cell} | {', '.join(r.flags) or '—'} |")
    lines.append("")
    lines.append(f"- **Window:** {v.window} · **slip multiplier:** {v.slip_mult:g}x · **K bars:** {v.k_bars}")
    lines.append(f"- **Stress-regime correlation:** calm avg ρ = {v.calm_avg_corr:.3f} · "
                 f"stress avg ρ = {v.stress_avg_corr:.3f}")
    if v.stress_crowded_pairs:
        pairs = "; ".join(f"{a}~{b} ρ={rho:+.3f}" for a, b, rho in v.stress_crowded_pairs)
        lines.append(f"- **Crowded under stress (ρ ≥ {CROWDING_RHO:.2f}):** {pairs}")
    lines.append(f"- **Verdict:** {v.verdict} — {v.headline}")
    if v.flagged:
        lines.append(f"- **Flagged survivors:** {', '.join(v.flagged)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    slip_mult = DEFAULT_SLIP_MULT
    k_bars = DEFAULT_K_BARS
    report_path: str | None = None
    for i, a in enumerate(argv):
        if a == "--mult" and i + 1 < len(argv):
            slip_mult = float(argv[i + 1])
        elif a == "--k-bars" and i + 1 < len(argv):
            k_bars = int(argv[i + 1])
        elif a == "--report" and i + 1 < len(argv):
            report_path = argv[i + 1]
    v = run(slip_mult=slip_mult, k_bars=k_bars)
    _print(v)
    if report_path:
        from pathlib import Path
        Path(report_path).write_text(to_markdown(v))
        print(f"  wrote markdown findings table -> {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
