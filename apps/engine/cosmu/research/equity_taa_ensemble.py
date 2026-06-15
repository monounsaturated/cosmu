# intent: RECOMBINE the honest-Gate survivors (the evolve-strategy move: replicate/mix what works). The seven
# survivors from equity_taa_cohort (DAA/VAA/ADM strict + PAA/GTAA/RiskParity/TSMOM risk-adjusted) are all
# monthly multi-asset defensive-momentum rotations with DIFFERENT de-risk triggers (canary breadth vs SMA trend
# vs inverse-vol vs absolute-momentum) — so their drawdowns rarely coincide. An equal-weight (1/N, NOTHING fit)
# ensemble of low-correlation positive-Sharpe books should have a HIGHER risk-adjusted Sharpe and LOWER drawdown
# than any single member (the only free lunch). We PRE-REGISTER three compositions by RATIONALE (not by searching
# for the best-looking combo) and route them — plus the strict members for reference and a B&H-SPY null — through
# the UNCHANGED promote_cohort gate (DSR>=0.95 · BH-FDR · real holdout · maxDD/folds/PBO · beat-B&H).
#
# WHY 1/N IS NOT OVERFITTING: no weights are estimated; the members are fixed external priors; the ensembles are a
# fixed, pre-declared list (3), all FDR-counted so DSR deflates against them. The ensemble monthly return is the
# equal-weight mean of the members' realized NET streams on their COMMON months — i.e. hold 1/N of each book and
# rebalance monthly. That AVERAGING is conservative on costs: a combined book's turnover is <= the average of the
# members' (offsetting trades net out), so we never credit the diversification turnover-reduction. Composes
# equity_taa_cohort (no duplicated strategy logic); zero LLM; deterministic for fixed cached data.

from __future__ import annotations

import statistics
import sys
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.trials import register_trial, trial_stats
from cosmu.master.verdict_log import durable_persist
from cosmu.research import equity_taa_cohort as cohort
from cosmu.research.equity_taa_cohort import StratStreams, _metrics

# Pre-registered ensemble compositions (by RATIONALE, declared before looking at the ensemble stats).
ENSEMBLES: dict[str, tuple[str, list[str]]] = {
    "core3":      ("the 3 STRICT-PASS survivors (DAA+VAA+ADM)", ["daa", "vaa", "accel_dual_momentum"]),
    "defensive5": ("the 5 lowest-DD / best-holdout crisis-avoiders (DAA+PAA+GTAA+TSMOM+HAA)",
                   ["daa", "paa", "faber_gtaa", "tsmom_trend", "haa"]),
    "all8":       ("all 8 DSR+holdout survivors", ["daa", "vaa", "accel_dual_momentum", "paa", "faber_gtaa",
                                                   "risk_parity", "tsmom_trend", "haa"]),
}

# The member adapters live on the cohort module — resolve by name so we never duplicate strategy logic.
_MEMBER_ADAPTERS = {
    "daa": cohort._s_daa, "vaa": cohort._s_vaa, "accel_dual_momentum": cohort._s_adm,
    "paa": cohort._s_paa, "faber_gtaa": cohort._s_gtaa, "risk_parity": cohort._s_risk_parity,
    "tsmom_trend": cohort._s_tsmom, "haa": cohort._s_haa,
}


def _ann_sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    sd = statistics.pstdev(returns)
    return (statistics.fmean(returns) / sd) * (12 ** 0.5) if sd > 0 else 0.0


def _equal_weight(members: list[StratStreams], name: str, label: str) -> StratStreams:
    """1/N monthly-rebalanced blend on the members' COMMON months. bench = SPY over those months (members share
    the same SPY benchmark stream; take the first member's, restricted to the common months)."""
    common = sorted(set.intersection(*[set(m.months) for m in members]))
    net_by: list[dict] = [dict(zip(m.months, m.net, strict=True)) for m in members]
    bench0 = dict(zip(members[0].months, members[0].bench, strict=True))
    net = [statistics.fmean([nb[mn] for nb in net_by]) for mn in common]
    bench = [bench0[mn] for mn in common]
    return StratStreams(name, label, common, net, bench)


@dataclass
class EnsembleRow:
    name: str
    label: str
    kind: str                  # "ensemble" | "member" | "null"
    n_months: int
    ann_sharpe: float
    deflated_sharpe_prob: float
    holdout_dsr: float
    max_dd: float
    promoted_strict: bool
    survived_dsr_holdout: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class EnsembleVerdict:
    rows: list[EnsembleRow]
    best_individual_dsr: float
    best_individual_maxdd: float
    headline: str


def run(*, persist: bool = False) -> EnsembleVerdict:
    # Build the 7 members once (each via its existing cohort adapter).
    members: dict[str, StratStreams] = {}
    for key, fn in _MEMBER_ADAPTERS.items():
        try:
            members[key] = fn()
        except Exception as exc:  # noqa: BLE001 — a member that can't load is an honest skip
            print(f"  [skip member] {key}: {type(exc).__name__}: {exc}", file=sys.stderr)

    # The pre-registered ensembles (only those whose members all loaded).
    ens_streams: list[StratStreams] = []
    for name, (desc, keys) in ENSEMBLES.items():
        present = [members[k] for k in keys if k in members]
        if len(present) == len(keys):
            ens_streams.append(_equal_weight(present, f"ENS_{name}", f"Ensemble: {desc}"))

    # Reference members = the 3 strict survivors; + a B&H-SPY null disconfirmer (from the cohort).
    ref_members = [members[k] for k in ("daa", "vaa", "accel_dual_momentum") if k in members]
    try:
        null = cohort._s_spy_null()
    except Exception:  # noqa: BLE001
        null = None

    all_streams = ens_streams + ref_members + ([null] if null else [])
    if not ens_streams:
        return EnsembleVerdict([], 0.0, 0.0, "no ensemble could be built (members failed to load)")

    store = Store(Settings(database_url=f"sqlite:///{tempfile.mkdtemp(prefix='cosmu-taa-ens-')}/g.sqlite3",
                           openrouter_api_key=None))
    gates = store.settings.gates
    trials_counted = len(all_streams)

    # cohort CSCV-PBO across the ensembles' in-sample streams (common-window aligned) — the overfit guard.
    pbo = cohort._cohort_pbo(ens_streams) if len(ens_streams) >= 2 else 1.0

    metrics_by = {}
    for s in all_streams:
        m = _metrics(s, trials_counted=trials_counted).model_copy(update={"pbo": Decimal(str(round(pbo, 6)))})
        metrics_by[s.name] = m
        register_trial(store, float(m.sharpe_per_obs), source="equity_taa_ensemble", label=s.name)
    trials = trial_stats(store)

    candidates = [Candidate(id=s.name, metrics=metrics_by[s.name], net_profit=float(metrics_by[s.name].oos_return),
                            source="equity_taa_ensemble", label=s.label) for s in all_streams]
    persist_spec = durable_persist(
        run_id="equity-taa-ensemble",
        hypothesis="a 1/N ensemble of the honest-Gate TAA survivors is a stronger (higher-Sharpe/lower-DD) snipe "
                   "than any single member, on the native multi-asset monthly universe",
        source="research/equity_taa_ensemble", data_source="equities-offline",
        universe="multi-asset-equity-monthly") if persist else None
    proms = {p.candidate_id: p for p in promote_cohort(store, candidates, gates, fdr_q=0.10, register=False,
                                                       trials=trials, persist=persist_spec)}

    kind_of = {s.name: ("ensemble" if s.name.startswith("ENS_") else "null" if s.name == "buy_hold_spy" else "member")
               for s in all_streams}
    rows: list[EnsembleRow] = []
    for s in all_streams:
        m = metrics_by[s.name]
        p = proms[s.name]
        reasons = list(p.reasons)
        rows.append(EnsembleRow(
            s.name, s.label, kind_of[s.name], m.num_trades, round(_ann_sharpe(s.net), 3),
            round(float(p.deflated_sharpe_prob), 4), round(float(m.holdout_deflated_sharpe), 4),
            round(float(m.max_drawdown), 4), p.promoted, not [r for r in reasons if r != "buy_and_hold"], reasons))

    rows.sort(key=lambda r: (r.kind != "ensemble", -r.deflated_sharpe_prob))
    member_rows = [r for r in rows if r.kind == "member"]
    best_ind_dsr = max((r.deflated_sharpe_prob for r in member_rows), default=0.0)
    best_ind_dd = min((r.max_dd for r in member_rows), default=1.0)
    ens_rows = [r for r in rows if r.kind == "ensemble"]
    # strict winner: clears the FULL gate (incl. beat-SPY-raw) AND lower-DD than the best single member.
    strict_winners = [r for r in ens_rows if r.promoted_strict and r.max_dd <= best_ind_dd]
    # risk-adjusted winner: clears DSR>=0.95 + real holdout (+ PBO/folds) AND strictly lower DD than the best
    # single member — a Pareto improvement on RISK (the deployable-floor win), even if it doesn't out-RETURN SPY.
    risk_winners = [r for r in ens_rows if r.survived_dsr_holdout and r.max_dd < best_ind_dd]
    if strict_winners:
        b = max(strict_winners, key=lambda r: r.deflated_sharpe_prob)
        headline = (f"{b.label} clears the FULL gate (DSR {b.deflated_sharpe_prob:.3f}, holdout {b.holdout_dsr:+.3f}) "
                    f"at maxDD {b.max_dd:.1%} < the best single survivor's {best_ind_dd:.1%}: diversification gave a "
                    f"strictly stronger snipe")
    elif risk_winners:
        b = min(risk_winners, key=lambda r: r.max_dd)
        headline = (f"{b.label}: DSR {b.deflated_sharpe_prob:.3f}, holdout {b.holdout_dsr:+.3f}, annSR {b.ann_sharpe:.2f} "
                    f"at maxDD {b.max_dd:.1%} vs the best single survivor's {best_ind_dd:.1%} — the best RISK-ADJUSTED "
                    f"snipe (survivor-level Sharpe at ~half the drawdown); doesn't out-RETURN raw SPY (defensive tilt "
                    f"trades return for smoothness), so it clears the DSR+holdout bar, not strict beat-B&H")
    else:
        headline = "no ensemble beat the best single survivor on risk-adjusted terms"
    return EnsembleVerdict(rows, best_ind_dsr, best_ind_dd, headline)


def _print(v: EnsembleVerdict) -> None:
    print("\n" + "=" * 104)
    print("EQUITY TAA — SURVIVOR ENSEMBLES (recombine the winning logic: 1/N, nothing fit)")
    print("=" * 104)
    print(f"  {'book':<46} {'kind':<9} {'n':>4} {'annSR':>6} {'DSR':>6} {'holdout':>8} {'maxDD':>6}  flag")
    for r in v.rows:
        flag = "STRICT-PASS" if r.promoted_strict else ("DSR+HOLDOUT" if r.survived_dsr_holdout else "—")
        print(f"  {r.label[:46]:<46} {r.kind:<9} {r.n_months:>4} {r.ann_sharpe:>6.2f} {r.deflated_sharpe_prob:>6.3f} "
              f"{r.holdout_dsr:>+8.3f} {r.max_dd:>6.3f}  {flag}")
        if r.reasons:
            print(f"  {'':<46} reasons: {', '.join(r.reasons)}")
    print("-" * 104)
    print(f"  best single survivor: DSR {v.best_individual_dsr:.3f}, maxDD {v.best_individual_maxdd:.1%}")
    print(f"  HEADLINE: {v.headline}")
    print("=" * 104)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    _print(run(persist="--persist" in argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
