# intent: REPLICABILITY pass on the honest-Gate survivors (DAA/VAA/ADM from equity_taa_cohort). A real "snipe"
# must survive its own PARAMETER NEIGHBOURHOOD — an edge that clears only at one fee / one start-date / one top-N
# is knife-edge overfit, not replicable. For each survivor we sweep ONE clean axis at a time around the canonical
# config (fee bps, in-sample START shift, and DAA's structural top-N), Gate EVERY variant, and — critically —
# deflate each variant's Deflated-Sharpe against the ENTIRE perturbation search registered as trials (the most
# conservative honest bar: if a variant clears DSR>=0.95 + positive real holdout even when penalised for all ~40
# perturbations we tried, the pass is robust, not a fluke of one knob). The metric is the FRACTION of the
# neighbourhood that still clears: high = a replicable snipe; low = cost/sample/structure-fragile.
#
# This LOOSENS NOTHING and FISHES FOR NOTHING: it does not search for a better config to promote (the canonical
# specs are fixed external priors); it MEASURES how fragile the already-won pass is. Every variant is a counted
# trial, so the deflation is if anything harsher than the original 12-candidate cohort. Composes the existing
# strategy modules + equity_taa_cohort helpers; zero LLM; deterministic for fixed cached data.

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.scorer import score
from cosmu.master.trials import register_trial, trial_stats
from cosmu.research import equity_accel_dual_momentum as adm
from cosmu.research import equity_daa as daa
from cosmu.research import equity_vaa as vaa
from cosmu.research.equity_taa_cohort import (
    EMBARGO_MONTHS,
    HOLDOUT_FRAC,
    PERIODS_PER_YEAR,
    StratStreams,
    _last_complete_month,
)
from cosmu.research.equity_holdout import metrics_with_holdout, purged_embargoed_split

# One-axis-at-a-time neighbourhood around each canonical config (canonical = fee 1bps, start shift 0).
FEE_SWEEP = [1.0, 2.0, 3.0, 5.0]
START_SHIFTS = [0, 12, 24, 36]      # months to push the in-sample start forward (sample-start sensitivity)
DAA_TOP_N = [3, 4, 5, 6, 7, 8]      # DAA's structural risk-basket breadth (canonical 6)


def _streams_from(months, net, bench, name, label) -> StratStreams:
    return StratStreams(name, label, list(months), list(net), list(bench))


# --- variant generators: call each survivor's REAL run fn with perturbed clean knobs (restore globals after) ----


def _daa_variant(*, fee: float, start_shift: int, top_n: int | None) -> StratStreams:
    series = {s: daa.load_monthly(s) for s in daa.DAA_SERIES}
    start = daa._add_months(daa.first_investable_month(series), start_shift)
    saved = daa.TOP_N
    try:
        if top_n is not None:
            daa.TOP_N = top_n
        r = daa.run_daa(series, fee_bps_per_side=fee, start=start, end=_last_complete_month())
    finally:
        daa.TOP_N = saved
    tn = top_n if top_n is not None else saved
    return _streams_from(r.months, r.net_returns, r.spy_returns, "daa", f"DAA fee={fee:.0f} shift={start_shift} topN={tn}")


def _vaa_variant(*, fee: float, start_shift: int) -> StratStreams:
    series = {s: vaa.load_monthly(s) for s in vaa.VAA_SERIES}
    start = vaa._add_months(vaa.first_investable_month(series), start_shift)
    r = vaa.run_vaa(series, fee_bps_per_side=fee, start=start, end=_last_complete_month())
    return _streams_from(r.months, r.net_returns, r.spy_returns, "vaa", f"VAA fee={fee:.0f} shift={start_shift}")


def _adm_variant(*, fee: float, start_shift: int, bonds: str | None = None) -> StratStreams:
    b = bonds or adm._choose_bonds()
    series = {s: adm.load_monthly(s) for s in adm._series_symbols(b)}
    start = adm._add_months(adm._first_investable_month(series, b), start_shift)
    r = adm.run_adm(series, bonds=b, fee_bps_per_side=fee, start=start, end=_last_complete_month())
    return _streams_from(r.months, r.net_returns, r.spy_returns, "adm", f"ADM fee={fee:.0f} shift={start_shift} bonds={b}")


def _build_grid() -> dict[str, list[StratStreams]]:
    """One-axis-at-a-time around each canonical config. The canonical (fee=1, shift=0[, topN=6]) appears once."""
    grid: dict[str, list[StratStreams]] = {"daa": [], "vaa": [], "adm": []}
    # DAA: fee axis, start axis, top-N axis
    for fee in FEE_SWEEP:
        grid["daa"].append(_daa_variant(fee=fee, start_shift=0, top_n=None))
    for sh in START_SHIFTS[1:]:
        grid["daa"].append(_daa_variant(fee=1.0, start_shift=sh, top_n=None))
    for tn in DAA_TOP_N:
        if tn != daa.TOP_N:
            grid["daa"].append(_daa_variant(fee=1.0, start_shift=0, top_n=tn))
    # VAA + ADM: fee axis, start axis
    for fee in FEE_SWEEP:
        grid["vaa"].append(_vaa_variant(fee=fee, start_shift=0))
        grid["adm"].append(_adm_variant(fee=fee, start_shift=0))
    for sh in START_SHIFTS[1:]:
        grid["vaa"].append(_vaa_variant(fee=1.0, start_shift=sh))
        grid["adm"].append(_adm_variant(fee=1.0, start_shift=sh))
    # ADM bond-sleeve robustness (AGG vs TLT — the documented alternative)
    grid["adm"].append(_adm_variant(fee=1.0, start_shift=0, bonds="TLT"))
    return grid


def _metrics_for(s: StratStreams, *, trials_counted: int):
    split = purged_embargoed_split(s.bench, holdout_frac=HOLDOUT_FRAC, embargo=EMBARGO_MONTHS)
    bench_total = 1.0
    for r in split.in_sample:
        bench_total *= (1.0 + r)
    m, _ = metrics_with_holdout(
        s.net, trials_counted=trials_counted, periods_per_year=PERIODS_PER_YEAR,
        holdout_frac=HOLDOUT_FRAC, embargo=EMBARGO_MONTHS, long_only=True, bench_return=bench_total - 1.0)
    return m


@dataclass
class VariantVerdict:
    label: str
    dsr: float
    holdout_dsr: float
    max_dd: float
    clears: bool          # DSR>=0.95 AND holdout>0 AND maxDD/folds/pbo (every overfit guard; beat-B&H set aside)
    reasons: list[str] = field(default_factory=list)


@dataclass
class StrategyRobustness:
    name: str
    n_variants: int
    n_clear: int
    replicability: float       # fraction of the neighbourhood that still clears, deflated against the FULL search
    canonical_clears: bool
    variants: list[VariantVerdict] = field(default_factory=list)


def run() -> dict[str, StrategyRobustness]:
    grid = _build_grid()
    all_variants = [(strat, s) for strat, streams in grid.items() for s in streams]
    total_trials = len(all_variants)

    # Register EVERY variant of EVERY survivor as a trial first -> deflation sees the whole perturbation search.
    store = Store(Settings(database_url=f"sqlite:///{tempfile.mkdtemp(prefix='cosmu-taa-robust-')}/g.sqlite3",
                           openrouter_api_key=None))
    metrics = {}
    for strat, s in all_variants:
        m = _metrics_for(s, trials_counted=total_trials)
        metrics[(strat, s.label)] = m
        register_trial(store, float(m.sharpe_per_obs), source=f"taa_robust_{strat}", label=s.label)
    trials = trial_stats(store)
    gates = store.settings.gates

    out: dict[str, StrategyRobustness] = {}
    for strat, streams in grid.items():
        vvs: list[VariantVerdict] = []
        for s in streams:
            m = metrics[(strat, s.label)]
            v = score(m, gates, trials=trials)
            # replicability bar = every OVERFIT guard intact; the raw-return-vs-SPY hurdle is set aside (same
            # rationale as the cohort's DSR+HOLDOUT bar — SPY isn't a rotation's native basket).
            reasons = [r for r in v.reasons if r != "buy_and_hold"]
            vvs.append(VariantVerdict(s.label, round(float(v.deflated_sharpe_prob), 4),
                                      round(float(m.holdout_deflated_sharpe), 4), round(float(m.max_drawdown), 4),
                                      clears=not reasons, reasons=reasons))
        n_clear = sum(1 for v in vvs if v.clears)
        canonical = next((v for v in vvs if "fee=1 " in v.label and "shift=0" in v.label), vvs[0])
        out[strat] = StrategyRobustness(strat, len(vvs), n_clear,
                                        round(n_clear / len(vvs), 3) if vvs else 0.0,
                                        canonical.clears, vvs)
    return out


def _print(out: dict[str, StrategyRobustness]) -> None:
    print("\n" + "=" * 104)
    print("EQUITY TAA — REPLICABILITY (does each survivor's Gate-pass survive its PARAMETER NEIGHBOURHOOD?)")
    print(f"  every variant deflated against the FULL {sum(r.n_variants for r in out.values())}-variant search "
          f"(harsher than the 12-candidate cohort) · bar = DSR>=0.95 + positive real holdout + maxDD/folds/PBO")
    print("=" * 104)
    for r in out.values():
        verdict = ("REPLICABLE" if r.replicability >= 0.7 else
                   "PARTIAL" if r.replicability >= 0.4 else "FRAGILE")
        print(f"\n  {r.name.upper()}: {r.n_clear}/{r.n_variants} variants clear  "
              f"(replicability {r.replicability:.0%}) · canonical clears: {r.canonical_clears}  -> {verdict}")
        for v in r.variants:
            mark = "✓" if v.clears else "✗"
            extra = f"  reasons={','.join(v.reasons)}" if v.reasons else ""
            print(f"    {mark} {v.label:<34} DSR={v.dsr:.3f} holdout={v.holdout_dsr:+.3f} maxDD={v.max_dd:.3f}{extra}")
    print("\n" + "=" * 104)
    repl = [r.name for r in out.values() if r.replicability >= 0.7]
    print(f"  REPLICABLE SNIPES (>=70% of the param neighbourhood clears the strict overfit bar): "
          f"{', '.join(repl) if repl else 'none'}")
    print("=" * 104)


def main() -> int:
    _print(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
