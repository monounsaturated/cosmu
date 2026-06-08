# intent: correlation engine read-out for the frontend; inputs: none; outputs: CorrelationsResponse from the
# correlation_ledger; invariants: read-only + propose-only (NEVER a Gate/money action), PIT-honest, honest-empty
# (no findings → empty arrays + null heatmap horizon, never fabricated). The deterministic Gate disposes; this
# surface only DISPLAYS what the scan PROPOSED and how each correlation moves run-over-run (stability/decay).

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cosmu.api._shared import store
from cosmu.api.models import (
    CorrelationFinding,
    CorrelationHeatmap,
    CorrelationHeatmapCell,
    CorrelationsResponse,
    CorrelationStability,
    CorrelationStabilityPoint,
)
from cosmu.master.correlation_ledger import latest_findings

router = APIRouter()

# How many of the most-recent findings to surface (bounded so the contract stays compact). The latest set is then
# narrowed to "the latest run" via run_id, so the page shows one coherent scan, not a smear across runs.
_LATEST_LIMIT = 500
# A non-causal/orthogonality-control finding is flagged in the ledger's deflated_note (single source of truth).
_NONCAUSAL_MARKER = "NON-CAUSAL"


def _is_non_causal(row: dict[str, Any]) -> bool:
    """True iff this finding is on a registered NON-CAUSAL control feature — read from the ledger's deflated_note
    (written by correlation_ledger.deflated_note_for from the feature_registry prior, the single source of truth).
    Surfaced so the UI greys-out a known-false baseline; a strong IC there is a data-snooping red flag, not an edge."""
    return _NONCAUSAL_MARKER in str(row.get("deflated_note") or "")


def _finding(row: dict[str, Any]) -> CorrelationFinding:
    """Map one correlation_findings row → the typed contract. Every numeric is coerced so a NUMERIC column that
    reads back as a string (some drivers) never breaks the TS contract; fdr_survived is an int flag → bool."""
    return CorrelationFinding(
        run_id=str(row["run_id"]),
        ts=str(row["ts"]),
        feature=str(row["feature"]),
        source=str(row["source"]),
        asset=str(row["asset"]),
        horizon=int(row["horizon"]),
        ic=float(row["ic"]),
        n=int(row["n"]),
        p=float(row["p"]),
        fdr_survived=bool(int(row["fdr_survived"])),
        non_causal=_is_non_causal(row),
        deflated_note=str(row.get("deflated_note") or ""),
        data_source=str(row.get("data_source") or ""),
    )


def _pick_heatmap_horizon(rows: list[dict[str, Any]]) -> int | None:
    """The horizon the compact feature × asset heatmap is pinned to: the one the latest run measured MOST (most
    cells), tie-broken by the smaller horizon for determinism. None when there are no findings (honest empty)."""
    if not rows:
        return None
    counts: dict[int, int] = {}
    for r in rows:
        h = int(r["horizon"])
        counts[h] = counts.get(h, 0) + 1
    # most-populated horizon wins; ties → smaller horizon (deterministic).
    return max(counts, key=lambda h: (counts[h], -h))


def _heatmap(rows: list[dict[str, Any]]) -> CorrelationHeatmap:
    """A compact IC heatmap for ONE horizon (the most-measured one): sorted feature + asset axes and the sparse
    cells the latest run actually measured at that horizon. If a (feature, asset) pair recurs at this horizon
    (shouldn't within one run), the strongest-|IC| cell wins. Honest empty: no findings → null horizon, no cells."""
    horizon = _pick_heatmap_horizon(rows)
    if horizon is None:
        return CorrelationHeatmap(horizon=None, features=[], assets=[], cells=[])
    at_h = [r for r in rows if int(r["horizon"]) == horizon]
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for r in at_h:
        key = (str(r["feature"]), str(r["asset"]))
        prev = best.get(key)
        if prev is None or abs(float(r["ic"])) > abs(float(prev["ic"])):
            best[key] = r
    cells = [
        CorrelationHeatmapCell(
            feature=str(r["feature"]),
            asset=str(r["asset"]),
            ic=float(r["ic"]),
            fdr_survived=bool(int(r["fdr_survived"])),
            non_causal=_is_non_causal(r),
        )
        for r in best.values()
    ]
    cells.sort(key=lambda c: (c.feature, c.asset))
    features = sorted({c.feature for c in cells})
    assets = sorted({c.asset for c in cells})
    return CorrelationHeatmap(horizon=horizon, features=features, assets=assets, cells=cells)


def _stability(rows: list[dict[str, Any]]) -> list[CorrelationStability]:
    """Per-feature stability/decay. For each feature in the latest run we pin its STRONGEST-|IC| (asset, horizon)
    series and read that series across runs (oldest-first) from the ledger — the decay tell a single print can't
    show. delta_ic = latest - first (negative = decaying); a single-run series carries delta_ic 0.0. Sorted by
    largest decay first (most-negative delta) so the UI surfaces fading correlations at the top."""
    # one representative (asset, horizon) per feature: the strongest-|IC| cell in the latest run.
    rep: dict[str, dict[str, Any]] = {}
    for r in rows:
        f = str(r["feature"])
        cur = rep.get(f)
        if cur is None or abs(float(r["ic"])) > abs(float(cur["ic"])):
            rep[f] = r
    out: list[CorrelationStability] = []
    # Batched history: ONE query + group in Python. The per-feature feature_history() loop was an N+1 — fine on
    # the SQLite test store, but on prod Postgres each call is a network round-trip, so dozens of features hung
    # the endpoint past its timeout. The bounded LIMIT keeps this cheap as runs accrue (stability is approximate).
    hist_by_key: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for h in store.rows(
        "SELECT run_id, ts, feature, asset, horizon, ic, fdr_survived FROM correlation_findings "
        "ORDER BY ts ASC LIMIT 50000"
    ):
        key = (str(h["feature"]), str(h["asset"]), int(h["horizon"]))
        hist_by_key.setdefault(key, []).append(h)
    for feature, r in rep.items():
        asset = str(r["asset"])
        horizon = int(r["horizon"])
        hist_rows = hist_by_key.get((feature, asset, horizon))
        if not hist_rows:  # shouldn't happen (the latest row IS in the table) but stay offline-safe.
            hist_rows = [r]
        points = [
            CorrelationStabilityPoint(
                run_id=str(h["run_id"]),
                ts=str(h["ts"]),
                ic=float(h["ic"]),
                fdr_survived=bool(int(h["fdr_survived"])),
            )
            for h in hist_rows
        ]
        first_ic = points[0].ic
        latest_ic = points[-1].ic
        out.append(
            CorrelationStability(
                feature=feature,
                asset=asset,
                horizon=horizon,
                non_causal=_is_non_causal(r),
                latest_ic=latest_ic,
                first_ic=first_ic,
                delta_ic=latest_ic - first_ic,
                n_runs=len(points),
                history=points,
            )
        )
    # most-decaying first (most-negative delta), then by feature for a stable order.
    out.sort(key=lambda s: (s.delta_ic, s.feature))
    return out


@router.get("/correlations", response_model=CorrelationsResponse)
def correlations() -> CorrelationsResponse:
    """The correlation engine, made visible: (a) the LATEST run's findings (feature, source, asset, horizon, IC,
    n, p, FDR-survival, non-causal flag), (b) the BH-FDR survivors (candidate hypotheses), (c) a compact IC
    heatmap (feature × asset for one horizon), (d) per-feature stability/decay (IC history across runs). All from
    the correlation_ledger — PIT-honest. HONEST EMPTY STATE: no findings yet → empty arrays + a null heatmap
    horizon, never fabricated. Read-only, propose-only — the deterministic Gate is the disposal layer; this NEVER
    gates or moves money."""
    # One held connection for all reads (latest + survivors + the stability scan). Each store.rows() otherwise
    # opens a fresh Supabase connection (~2s of Railway→Supabase latency each) — the same N+1-connection trap
    # fixed across the other routers; here it kept /correlations over the 5s SSR budget.
    with store.reading():
        recent = latest_findings(store, limit=_LATEST_LIMIT)
        if not recent:
            return CorrelationsResponse(
                latest_run_id=None,
                latest=[],
                survivors=[],
                heatmap=CorrelationHeatmap(horizon=None, features=[], assets=[], cells=[]),
                stability=[],
            )
        # latest_findings is newest-first → the first row's run_id IS the latest run. Show ONE coherent run, not a
        # smear across runs (a heatmap mixing runs would silently compare ICs from different scans).
        latest_run_id = str(recent[0]["run_id"])
        latest_rows = [r for r in recent if str(r["run_id"]) == latest_run_id]
        latest = [_finding(r) for r in latest_rows]
        # Survivors are the SIGNAL — query them directly (survived_only) rather than subsetting the ts-limited
        # `latest`: the FDR-survivors are spread through a big run and would otherwise fall outside the top-N window
        # (a full sweep can persist >1k findings; the survivors are the few that matter).
        survivor_rows = [r for r in latest_findings(store, limit=_LATEST_LIMIT, survived_only=True)
                         if str(r["run_id"]) == latest_run_id]
        survivors = [_finding(r) for r in survivor_rows]
        return CorrelationsResponse(
            latest_run_id=latest_run_id,
            latest=latest,
            survivors=survivors,
            heatmap=_heatmap(latest_rows),
            stability=_stability(latest_rows),
        )
