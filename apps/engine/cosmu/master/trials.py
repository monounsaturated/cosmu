# intent: global multiple-testing ledger so the Deflated Sharpe deflates against every hypothesis ever run, not just one strategy's params; inputs: per-trial per-observation Sharpe samples; outputs: cumulative TrialStats; invariants: the trial counter is monotonic and out of any LLM's reach.

from __future__ import annotations

import math
from statistics import pvariance

from cosmu.knowledge.store import Store, utcnow
from cosmu.master.scorer import TrialStats


def register_trial(store: Store, sharpe_per_obs: float, *, source: str, label: str | None = None) -> None:
    """THE single choke point every candidate-generating engine (RD-Agent, Qlib, AutoML, RL, the evolution
    loop) must route through. If a trial bypasses this, the Deflated Sharpe / FDR deflation is invalid —
    family-wise error is the #1 overfit risk once an LLM generates unlimited ideas."""
    store.rows(
        "INSERT INTO trials(ts, source, label, sharpe_per_obs) VALUES (?, ?, ?, ?)",
        (utcnow(), source, label, float(sharpe_per_obs)),
    )


# Back-compat alias — `register_trial` is the canonical name going forward.
record_trial = register_trial


def trial_stats(store: Store) -> TrialStats:
    rows = store.rows("SELECT sharpe_per_obs FROM trials")
    sharpes = [float(r["sharpe_per_obs"]) for r in rows]
    count = max(1, len(sharpes))
    variance = pvariance(sharpes) if len(sharpes) > 1 else None
    return TrialStats(count=count, sr_variance=variance)


def trial_stats_for_cohort(store: Store, k: int, rho_bar: float | None) -> TrialStats:
    """Effective trial stats when K correlated strategies just registered their trials.

    A correlated grid of K near-duplicate variants is NOT K independent tests. This function replaces the
    raw K contribution in the global count with its effective count K_eff = K/(1+(K-1)*rho_bar), so the
    total effective trials becomes N_hist + K_eff instead of N_hist + K. Makes the gate FAIRER on correlated
    grids (less Type-II over-rejection) without loosening it for independent hypotheses (rho_bar≈0 → no change).

    `rho_bar` = average pairwise Spearman correlation of the K strategies' return streams — compute it with
    `strategy_correlation.pairwise_correlation(...).average_pairwise_correlation`. Pass None/NaN to fall back
    to plain `trial_stats` (conservative-safe, no haircut).

    PRECONDITION: all K trials must already be registered before calling so they are included in the DB count.
    """
    rows = store.rows("SELECT sharpe_per_obs FROM trials")
    sharpes = [float(r["sharpe_per_obs"]) for r in rows]
    n_global = max(1, len(sharpes))
    variance = pvariance(sharpes) if len(sharpes) > 1 else None

    if rho_bar is None or math.isnan(rho_bar) or k <= 1:
        return TrialStats(count=n_global, sr_variance=variance)

    rho = min(1.0, max(0.0, rho_bar))
    k_eff = float(k) / (1.0 + (k - 1) * rho) if rho > 0.0 else float(k)
    # N_hist = global count minus the K we just registered; replace them with their effective count
    n_hist = max(0, n_global - k)
    n_adjusted = n_hist + k_eff
    return TrialStats(count=max(1, int(round(n_adjusted))), sr_variance=variance)
