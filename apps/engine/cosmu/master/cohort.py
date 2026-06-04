# intent: the cohort promotion gate — the single place many DISTINCT candidates (RD-Agent/Qlib/AutoML/RL/the
# evolution loop) are judged together; inputs: candidate metrics + net-of-cost profit + the store; outputs: ranked
# Promotions; invariants: every candidate is registered as a trial (FDR validity), promotion needs BOTH per-candidate
# significance (Deflated Sharpe / PBO / gates via score()) AND surviving Benjamini-Hochberg FDR across the cohort,
# and survivors are RANKED by net-of-cost profit (the money), never by Sharpe. The LLM cannot touch any of this.

from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.config.settings import GateSettings
from cosmu.knowledge.store import Store
from cosmu.master.fdr import benjamini_hochberg, dsr_pvalue
from cosmu.master.scorer import BacktestMetrics, TrialStats, score
from cosmu.master.trials import register_trial, trial_stats


@dataclass(frozen=True)
class Candidate:
    """One distinct strategy candidate from any generator. `net_profit` is net-of-cost (fees+slippage+impact)
    return — the ranking metric. `source` flows to the trial ledger so FDR counts every generator's output."""

    id: str
    metrics: BacktestMetrics
    net_profit: float
    source: str
    label: str | None = None
    return_variance: float = 1.0   # variance of the strategy's per-period net returns (per-period net-return variance)


@dataclass(frozen=True)
class Promotion:
    candidate_id: str
    promoted: bool
    rank: int | None              # 1 = best by net-of-cost profit among promoted; None if not promoted
    net_profit: float
    deflated_sharpe_prob: float
    survived_fdr: bool
    reasons: list[str] = field(default_factory=list)


def promote_cohort(
    store: Store,
    candidates: list[Candidate],
    gates: GateSettings,
    *,
    fdr_q: float = 0.10,
    register: bool = True,
    trials: TrialStats | None = None,
) -> list[Promotion]:
    """Judge a cohort of DISTINCT candidates together. Steps: (1) register every candidate as a trial — the
    deflation/FDR math is invalid if any bypasses this; (2) score each on stats vs the trial-inflated benchmark;
    (3) apply Benjamini-Hochberg FDR across the cohort's p-values; (4) promote iff it passes the stats gate AND
    survives FDR; (5) rank promoted by net-of-cost profit. Deterministic and out of any agent's reach.

    `register=False` + `trials=...` lets a caller that has ALREADY registered the full (possibly larger,
    correlated) trial population own the ledger itself — e.g. the finder registers EVERY grid variant as a
    trial (so deflation sees the true count) but then dedupes the correlated grid down to DISTINCT cluster
    representatives before handing them here, honoring this gate's "distinct candidates, not correlated
    param-variants" contract. Defaults reproduce the prior behaviour exactly (the deployed FarmLoop path)."""
    if not candidates:
        return []

    # 1. register all trials FIRST, so significance deflates against the full cohort + history.
    if register:
        for c in candidates:
            register_trial(store, float(c.metrics.sharpe_per_obs), source=c.source, label=c.label or c.id)
    trials = trials if trials is not None else trial_stats(store)

    # 2. per-candidate statistical verdict (Deflated Sharpe / PBO / folds / drawdown / holdout).
    verdicts = [score(c.metrics, gates, trials=trials) for c in candidates]

    # 3. Benjamini-Hochberg across the cohort of DISTINCT candidates (not correlated param-variants).
    pvalues = [dsr_pvalue(float(v.deflated_sharpe_prob)) for v in verdicts]
    fdr_mask = benjamini_hochberg(pvalues, q=fdr_q)

    # 4. promote iff stats-gate passes AND FDR survives; collect reasons otherwise.
    prelim: list[tuple[Candidate, object, bool, list[str]]] = []  # noqa: type — internal
    for c, v, survived in zip(candidates, verdicts, fdr_mask, strict=True):
        reasons = list(v.reasons)
        if not survived:
            reasons.append("fdr")
        prelim.append((c, v, v.passed and survived, reasons))

    # 5. rank promoted by net-of-cost profit (the money), descending.
    promoted_sorted = sorted(
        [p for p in prelim if p[2]], key=lambda p: p[0].net_profit, reverse=True
    )
    rank_of = {p[0].id: i + 1 for i, p in enumerate(promoted_sorted)}

    return [
        Promotion(
            candidate_id=c.id,
            promoted=ok,
            rank=rank_of.get(c.id),
            net_profit=round(c.net_profit, 6),
            deflated_sharpe_prob=float(v.deflated_sharpe_prob),
            survived_fdr=("fdr" not in reasons),
            reasons=reasons,
        )
        for c, v, ok, reasons in prelim
    ]
