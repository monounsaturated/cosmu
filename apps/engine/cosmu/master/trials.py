# intent: global multiple-testing ledger so the Deflated Sharpe deflates against every hypothesis ever run, not just one strategy's params; inputs: per-trial per-observation Sharpe samples; outputs: cumulative TrialStats; invariants: the trial counter is monotonic and out of any LLM's reach.

from __future__ import annotations

from statistics import pvariance

from cosmu.knowledge.store import Store, utcnow
from cosmu.master.scorer import TrialStats


def record_trial(store: Store, sharpe_per_obs: float, *, source: str, label: str | None = None) -> None:
    store.rows(
        "INSERT INTO trials(ts, source, label, sharpe_per_obs) VALUES (?, ?, ?, ?)",
        (utcnow(), source, label, float(sharpe_per_obs)),
    )


def trial_stats(store: Store) -> TrialStats:
    rows = store.rows("SELECT sharpe_per_obs FROM trials")
    sharpes = [float(r["sharpe_per_obs"]) for r in rows]
    count = max(1, len(sharpes))
    variance = pvariance(sharpes) if len(sharpes) > 1 else None
    return TrialStats(count=count, sr_variance=variance)
