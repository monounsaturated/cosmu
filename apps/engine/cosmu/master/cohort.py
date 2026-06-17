# intent: the cohort promotion gate — the single place many DISTINCT candidates (RD-Agent/Qlib/AutoML/RL/the
# evolution loop) are judged together; inputs: candidate metrics + net-of-cost profit + the store; outputs: ranked
# Promotions; invariants: every candidate is registered as a trial (FDR validity), promotion needs BOTH per-candidate
# significance (Deflated Sharpe / PBO / gates via score()) AND surviving Benjamini-Hochberg FDR across the cohort,
# and survivors are RANKED by net-of-cost profit (the money), never by Sharpe. The LLM cannot touch any of this.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from cosmu.config.settings import GateSettings
from cosmu.knowledge.store import Store
from cosmu.master.fdr import benjamini_hochberg, dsr_pvalue
from cosmu.master.scorer import BacktestMetrics, TrialStats, cscv_pbo, score
from cosmu.master.trials import register_trial, trial_stats
from cosmu.master.verdict_log import CohortPersist, persist_cohort_verdict

# Two validation return streams with Pearson correlation >= this are treated as the SAME hypothesis: one is the
# cluster representative, the rest are near-duplicates. Deduping to representatives BEFORE BH-FDR is what stops a
# dense correlated grid (or a cohort of near-identical mutants) from gaming the false-discovery cutoff — the
# "distinct candidates, not correlated param-variants" contract this gate depends on. The single source of truth
# for that threshold across BOTH the finder sweep (lab/finder.py) and the autonomous loop (evolution/loop.py).
CLUSTER_CORRELATION = 0.95


# --------------------------------------------------------------------------- correlation / clustering / CSCV
# The shared multiple-testing-honesty primitives. Both the Strategy Finder (a grid of param-variants over one
# spec) and the autonomous FarmLoop (a cohort of correlated mutants) feed correlated return streams into the
# Gate; both MUST collapse those near-duplicates to DISTINCT representatives before BH-FDR and certify the cohort
# with a REAL CSCV-PBO (not a per-candidate proxy). Factoring them here (instead of finder importing the loop or
# vice-versa) avoids a lab.finder <-> evolution.loop import cycle while keeping the math byte-identical.


def corr(a: list[float], b: list[float]) -> float | None:
    """Pearson correlation of two return streams aligned on their common tail. None when undefined (fewer than
    2 common points, or either side has zero variance)."""
    n = min(len(a), len(b))
    if n < 2:
        return None
    aa, bb = a[-n:], b[-n:]
    ma, mb = statistics.fmean(aa), statistics.fmean(bb)
    va = sum((x - ma) ** 2 for x in aa)
    vb = sum((y - mb) ** 2 for y in bb)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((aa[k] - ma) * (bb[k] - mb) for k in range(n))
    return cov / math.sqrt(va * vb)


def cluster_representatives(
    ordered_tags: list[str], returns_by_tag: dict[str, list[float]], *, threshold: float
) -> list[str]:
    """Greedy correlation clustering over a list of tags the CALLER has already ordered best-first. Walk the
    ordered tags and fold each into the first existing representative it correlates with at >= `threshold`;
    otherwise it starts a new cluster as its own representative. Returns the representative tags — one DISTINCT
    hypothesis per cluster — so BH-FDR is never fed a family of near-duplicates. Tags without a usable (>= 2
    point) return stream are skipped (they cannot clear the trade gate anyway)."""
    reps: list[str] = []
    for tag in ordered_tags:
        stream = returns_by_tag.get(tag)
        if stream is None or len(stream) < 2:
            continue
        if any((corr(stream, returns_by_tag[rep]) or 0.0) >= threshold for rep in reps):
            continue
        reps.append(tag)
    return reps


def cohort_cscv_pbo(reps: list[str], returns_by_tag: dict[str, list[float]]) -> float:
    """Real CSCV-PBO across the DISTINCT representatives' return streams (a legitimate, diverse config
    population). < 2 representatives → 1.0 (maximally overfit: CSCV cannot certify a single config), matching
    the gate's convention. This is the REAL combinatorial-cross-validation overfit estimate the cohort must be
    judged on — never a per-candidate proxy (which a correlated family could trivially keep low)."""
    streams = [returns_by_tag[t] for t in reps if len(returns_by_tag.get(t, [])) >= 2]
    return cscv_pbo(streams) if len(streams) >= 2 else 1.0


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
    persist: CohortPersist | None = None,
    check_holdout: bool = True,
) -> list[Promotion]:
    """Judge a cohort of DISTINCT candidates together. Steps: (1) register every candidate as a trial — the
    deflation/FDR math is invalid if any bypasses this; (2) score each on stats vs the trial-inflated benchmark;
    (3) apply Benjamini-Hochberg FDR across the cohort's p-values; (4) promote iff it passes the stats gate AND
    survives FDR; (5) rank promoted by net-of-cost profit. Deterministic and out of any agent's reach.

    `register=False` + `trials=...` lets a caller that has ALREADY registered the full (possibly larger,
    correlated) trial population own the ledger itself — e.g. the finder registers EVERY grid variant as a
    trial (so deflation sees the true count) but then dedupes the correlated grid down to DISTINCT cluster
    representatives before handing them here, honoring this gate's "distinct candidates, not correlated
    param-variants" contract. Defaults reproduce the prior behaviour exactly (the deployed FarmLoop path).

    `persist=CohortPersist(...)` opts the caller into durable experiment-memory: after the verdict is computed
    it is written to `gate_verdicts` (one row per cohort run, payload kind='cohort') so every run is queryable,
    not just logged to DECISIONS.md. The persist store is a SEPARATE durable handle from the (possibly tempfile)
    trial-ledger `store`, so persisting NEVER touches the deflation math; it is best-effort (a DB failure logs +
    is swallowed, never breaking the run). Default None = pure, side-effect-free (the math is unchanged)."""
    if not candidates:
        return []

    # 1. register all trials FIRST, so significance deflates against the full cohort + history.
    if register:
        for c in candidates:
            register_trial(store, float(c.metrics.sharpe_per_obs), source=c.source, label=c.label or c.id)
    trials = trials if trials is not None else trial_stats(store)

    # 2. per-candidate statistical verdict (Deflated Sharpe / PBO / folds / drawdown / holdout).
    # `check_holdout=False` = screening-lane mode (see scorer.score): the caller selects on validation-only
    # evidence and applies the one-shot holdout to its promoted champions AFTERWARDS — never as a retryable
    # per-variant filter inside the cohort verdict.
    verdicts = [score(c.metrics, gates, trials=trials, check_holdout=check_holdout) for c in candidates]

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

    promotions = [
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

    # 6. (opt-in) persist the full cohort verdict to durable experiment-memory — best-effort, never raises.
    if persist is not None:
        persist_cohort_verdict(persist, candidates, promotions)

    return promotions
