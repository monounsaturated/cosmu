# intent: persist EVERY correlation_scan finding to `correlation_findings` so the machine's correlation memory is
# TRACKED over time, not just printed to a terminal. The correlation engine "finds correlations (even non-causal)";
# THIS is the layer that keeps them — one row per (run × feature × source × asset × horizon) carrying the PIT IC,
# its n / p / FDR-survival, and an HONEST non-causal note read from the feature_registry prior. The persist mirrors
# verdict_log.py: BEST-EFFORT + offline-safe (a persist failure NEVER raises into the research/scan path — the scan
# also prints, so a DB hiccup must not crash a run), ZERO LLM, PROPOSE-ONLY (tracking — this NEVER gates or moves
# money; the deterministic Gate is the disposal layer). The read side (latest-per-feature + per-feature history)
# lets the UI and decay-tracking see how a correlation's IC moves across runs — a strong IC that decays run-over-run
# is the tell the scan can't show from a single print. One-way dependency: ledger -> store (+ feature_registry for
# the non-causal prior); the scan opts in by passing a CorrelationPersist, exactly like the cohort opts into
# verdict_log. Deterministic for a fixed store + findings.

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cosmu.config.feature_registry import FEATURE_REGISTRY
from cosmu.knowledge.store import Store, utcnow

log = logging.getLogger(__name__)

# Markers in a feature_registry prior that flag a feature as KNOWN non-causal — an orthogonality / known-false
# baseline wired honestly so the Gate has a noise floor to kill. A finding on such a feature is recorded with a
# `deflated_note` so the UI never lets a non-causal control masquerade as an edge (a strong IC on a non-causal
# feature is a data-snooping red flag, NOT a hypothesis to promote).
_NONCAUSAL_PRIOR_MARKERS = ("non-causal", "orthogonality control", "known-false")
_LOWCONF_PRIOR_MARKERS = ("low-confidence", "low confidence", "must earn its place")


def _prior_by_feature() -> dict[str, str]:
    """feature name → its registry prior text (the single source of truth for causal honesty)."""
    return {f.name: f.prior for f in FEATURE_REGISTRY}


def deflated_note_for(feature: str, priors: dict[str, str] | None = None) -> str:
    """An HONEST one-line causal-trust note for a feature, derived from its feature_registry prior. A KNOWN
    non-causal / orthogonality-control feature is flagged so a strong IC on it reads as a data-snooping red flag,
    not an edge; a low-confidence feature is flagged as must-earn-it-OOS; everything else is plain. Read-only —
    this NEVER changes the IC; it only annotates how much to trust it."""
    priors = priors if priors is not None else _prior_by_feature()
    prior = (priors.get(feature) or "").lower()
    if any(m in prior for m in _NONCAUSAL_PRIOR_MARKERS):
        return "NON-CAUSAL CONTROL — known-false baseline; a strong IC here is a data-snooping red flag, not an edge."
    if any(m in prior for m in _LOWCONF_PRIOR_MARKERS):
        return "low-confidence prior — must earn its place out-of-sample; the Gate disposes."
    return ""


@dataclass(frozen=True)
class CorrelationPersist:
    """The opt-in persistence spec the correlation scan hands to `persist_findings`. `store` is the DURABLE store
    the findings land in (prod Postgres on Modal/Railway, local SQLite otherwise). `run_id` ties every row of one
    scan together so a run is queryable as a unit and runs are comparable over time (decay-tracking). `data_source`
    tags whether the scan ran on live or fixture data so a test never pollutes the live correlation memory."""

    store: Store
    run_id: str
    data_source: str = "live"


def durable_persist(*, run_id: str, data_source: str = "live") -> CorrelationPersist:
    """One-liner factory: build a CorrelationPersist pointed at the REAL configured store (prod Postgres on
    Modal/Railway where the alt_data + findings live, local SQLite otherwise). Lets the scan opt into durable
    correlation memory with `persist=durable_persist(run_id=...)`, exactly like verdict_log.durable_persist."""
    from cosmu.config.settings import get_settings

    return CorrelationPersist(store=Store(get_settings()), run_id=run_id, data_source=data_source)


def _finding_columns(run_id: str, ts: str, data_source: str, result: Any, priors: dict[str, str]) -> tuple[Any, ...]:
    """Flatten one scan ICResult (duck-typed to avoid importing research.correlation_scan — keeps the dependency
    one-way: ledger never imports the scanner) into the `correlation_findings` column order."""
    feature = str(result.feature)
    return (
        run_id,
        ts,
        feature,
        str(result.source),
        str(result.asset),
        int(result.horizon),
        float(result.ic),
        int(result.n_obs),
        float(result.p_value),
        1 if bool(result.survived_fdr) else 0,
        deflated_note_for(feature, priors),
        data_source,
    )


_COLUMNS = ["run_id", "ts", "feature", "source", "asset", "horizon", "ic", "n", "p", "fdr_survived", "deflated_note", "data_source"]


def persist_findings(persist: CorrelationPersist, results: list[Any]) -> int:
    """Write one `correlation_findings` row PER scan result (batched in one transaction) + emit a
    `correlation_scan_run` event. Returns the number of rows written (0 on empty or on ANY failure, which it
    swallows + logs — a findings-persist must NEVER break a scan run). PROPOSE-ONLY: these rows are tracked
    correlation memory, never a gate decision and never money. Best-effort + offline-safe, mirrors verdict_log."""
    if not results:
        return 0
    try:
        ts = utcnow()
        priors = _prior_by_feature()
        rows = [_finding_columns(persist.run_id, ts, persist.data_source, r, priors) for r in results]
        with persist.store.batch() as writer:
            writer.insert_many("correlation_findings", _COLUMNS, rows)
            n_survived = sum(1 for r in rows if r[_COLUMNS.index("fdr_survived")] == 1)
            writer.append_event(
                actor="master",
                kind="correlation_scan_run",
                ref_type="correlation_scan",
                ref_id=persist.run_id,
                payload={"n_findings": len(rows), "n_survived_fdr": n_survived, "data_source": persist.data_source},
            )
        return len(rows)
    except Exception:  # noqa: BLE001 — a findings-persist failure must never break the research/scan path.
        log.warning("persist_findings failed for run_id=%s (%d results)", persist.run_id, len(results), exc_info=True)
        return 0


def latest_findings(store: Store, *, limit: int = 200, survived_only: bool = False) -> list[dict[str, Any]]:
    """The most-recent correlation findings across all features, newest first (one row per finding). Drives the
    UI's "what the scan found last" view. `survived_only` restricts to BH-FDR survivors (the candidate
    hypotheses). Read-only; offline-safe (empty list if the table is absent or the read fails)."""
    where = "WHERE fdr_survived = 1 " if survived_only else ""
    try:
        return store.rows(
            f"SELECT run_id, ts, feature, source, asset, horizon, ic, n, p, fdr_survived, deflated_note, data_source "
            f"FROM correlation_findings {where}ORDER BY ts DESC, id DESC LIMIT ?",
            (int(limit),),
        )
    except Exception:  # noqa: BLE001 — a read failure must never break the caller (UI/decay-tracking).
        log.warning("latest_findings read failed", exc_info=True)
        return []


def feature_history(store: Store, feature: str, *, asset: str | None = None, horizon: int | None = None,
                    limit: int = 100) -> list[dict[str, Any]]:
    """The IC history for ONE feature across runs, OLDEST first, so the caller can see how the correlation moves
    run-over-run — the decay signal a single print can't show (a strong IC that fades is the tell). Optionally
    pin one asset / horizon for a clean single series. Read-only; offline-safe (empty on any failure)."""
    clauses = ["feature = ?"]
    params: list[Any] = [feature]
    if asset is not None:
        clauses.append("asset = ?")
        params.append(asset)
    if horizon is not None:
        clauses.append("horizon = ?")
        params.append(int(horizon))
    params.append(int(limit))
    try:
        return store.rows(
            "SELECT run_id, ts, feature, source, asset, horizon, ic, n, p, fdr_survived, deflated_note, data_source "
            f"FROM correlation_findings WHERE {' AND '.join(clauses)} ORDER BY ts ASC, id ASC LIMIT ?",
            tuple(params),
        )
    except Exception:  # noqa: BLE001 — a read failure must never break the caller.
        log.warning("feature_history read failed for feature=%s", feature, exc_info=True)
        return []
