# intent: persist EVERY cohort Gate verdict to `gate_verdicts` so the machine's FULL experiment-memory is
# queryable (the Mind page + a "have we already tested this?" dedup), not just logged to docs/DECISIONS.md +
# ephemeral run-logs. Inputs: the DURABLE store (prod Postgres on Modal/Railway, local SQLite otherwise) + the
# cohort's candidates + the promote_cohort verdict. Output: one `gate_verdicts` row (payload kind='cohort')
# carrying every candidate's deflated-Sharpe / net-profit / FDR-survival / promote decision + a `cohort_gate_run`
# event. Invariants: BEST-EFFORT + offline-safe — a persist failure NEVER raises into the research/gate path
# (the verdict is also in DECISIONS.md + the run-log, so a DB hiccup must not crash a run); ZERO LLM on this path;
# the `store` carried here is a SEPARATE durable handle from the tempfile trial-ledger the cohort isolates for
# the FDR math — persisting the verdict never touches the deflation. One-way dependency: cohort -> verdict_log
# -> store (candidates/promotions are duck-typed via attribute access to avoid a circular import).

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from cosmu.knowledge.store import Store, utcnow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CohortPersist:
    """The opt-in persistence spec a cohort caller hands to `promote_cohort` (or to `persist_cohort_verdict`
    directly). `store` is the DURABLE store the verdict lands in — distinct from the tempfile store the runner
    isolates for trial-counting. `run_id` ties the row back to the run-log/DECISIONS entry; `hypothesis` is the
    plain-language edge claim; `source` is the generator string (FDR cohort key). `audit_trustworthy` records
    whether the run self-audited clean; `holdout` carries the real purged+embargoed OOS summary if the runner
    has it; `extra` is any run-specific scalars worth keeping (fees, universe size, window)."""

    store: Store
    run_id: str
    hypothesis: str
    source: str
    data_source: str = "live"
    audit_trustworthy: str | None = None
    holdout: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def durable_persist(*, run_id: str, hypothesis: str, source: str, data_source: str = "live", **extra: Any) -> CohortPersist:
    """One-liner factory for a research runner: build a CohortPersist pointed at the REAL configured store
    (prod Postgres on Modal/Railway via DATABASE_URL, local SQLite otherwise). Lets any cohort runner opt into
    durable experiment-memory with `persist=durable_persist(run_id=..., hypothesis=..., source=...)`."""
    from cosmu.config.settings import get_settings

    return CohortPersist(
        store=Store(get_settings()),
        run_id=run_id,
        hypothesis=hypothesis,
        source=source,
        data_source=data_source,
        extra=dict(extra),
    )


def _candidate_rows(candidates: list[Any], promotions: list[Any]) -> list[dict[str, Any]]:
    """Join each Candidate to its Promotion (by id) into one flat, queryable verdict row. Duck-typed so this
    module never imports `cohort` (keeps the dependency one-way)."""
    by_id = {c.id: c for c in candidates}
    rows: list[dict[str, Any]] = []
    for p in promotions:
        c = by_id.get(p.candidate_id)
        # the REAL purged+embargoed OOS holdout DSR lives on the candidate's metrics — persist it so the stored
        # experiment-memory shows OOS decay (positive in-sample dSR + negative holdout = overfit) without a re-run.
        holdout = None
        metrics = getattr(c, "metrics", None) if c is not None else None
        if metrics is not None and getattr(metrics, "holdout_deflated_sharpe", None) is not None:
            holdout = float(metrics.holdout_deflated_sharpe)
        rows.append(
            {
                "id": p.candidate_id,
                "label": getattr(c, "label", None) if c is not None else None,
                "promoted": bool(p.promoted),
                "rank": p.rank,
                "net_profit": float(p.net_profit),
                "deflated_sharpe_prob": float(p.deflated_sharpe_prob),
                "holdout_deflated_sharpe": holdout,
                "survived_fdr": bool(p.survived_fdr),
                "reasons": list(p.reasons),
            }
        )
    return rows


def persist_cohort_verdict(persist: CohortPersist, candidates: list[Any], promotions: list[Any]) -> bool:
    """Write ONE `gate_verdicts` row (kind='cohort') capturing the full cohort verdict + emit a
    `cohort_gate_run` event. Returns True on success, False on any failure (which it swallows + logs — a
    verdict-persist must never break a research run). `decision` column = 'PASS' iff ANY candidate promoted."""
    try:
        cand_rows = _candidate_rows(candidates, promotions)
        promoted = [r for r in cand_rows if r["promoted"]]
        best_dsr = max((r["deflated_sharpe_prob"] for r in cand_rows), default=0.0)
        decision = "PASS" if promoted else "FAIL"
        payload: dict[str, Any] = {
            "kind": "cohort",
            "run_id": persist.run_id,
            "hypothesis": persist.hypothesis,
            "source": persist.source,
            "passed": bool(promoted),
            "n_candidates": len(cand_rows),
            "n_promoted": len(promoted),
            "promoted_ids": [r["id"] for r in promoted],
            "best_deflated_sharpe_prob": best_dsr,
            "candidates": cand_rows,
            "holdout": persist.holdout,
            "audit_trustworthy": persist.audit_trustworthy,
            "data_source": persist.data_source,
            **(persist.extra or {}),
        }
        persist.store.rows(
            "INSERT INTO gate_verdicts(ts, decision, data_source, payload) VALUES (?, ?, ?, ?)",
            (utcnow(), decision, persist.data_source, json.dumps(payload, sort_keys=True)),
        )
        persist.store.append_event(
            actor="master",
            kind="cohort_gate_run",
            ref_type="gate",
            ref_id=persist.run_id,
            payload={"source": persist.source, "decision": decision, "n_promoted": len(promoted)},
        )
        return True
    except Exception:  # noqa: BLE001 — a verdict-persist failure must never break the research/gate path.
        log.warning("persist_cohort_verdict failed for run_id=%s source=%s", persist.run_id, persist.source, exc_info=True)
        return False
