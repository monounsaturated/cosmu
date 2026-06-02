# intent: global multiple-testing ledger so the Deflated Sharpe deflates against every hypothesis ever run, not just one strategy's params; inputs: per-trial per-observation Sharpe samples; outputs: cumulative TrialStats; invariants: the trial counter is monotonic and out of any LLM's reach.

from __future__ import annotations

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
