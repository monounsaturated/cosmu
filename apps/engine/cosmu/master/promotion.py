# intent: the live-replication FREEZE — turn a gate-passing Version into ONE durable `strategy_promotions` row
# that snapshots EVERYTHING needed to reproduce in live exactly what the Gate judged: the fitted params + their
# hash (so live runs THESE, never a drifting re-fit), the venue fee model the edge was proven against, the
# data/feature-registry version, the universe, the gate score, and the proven-regime passport. inputs: a Store +
# a promoted strategy_version_id (the row must already be committed) + the venue catalog; outputs: the persisted
# promotion id. invariants: deterministic + keyless (no LLM, no network); idempotent per version (re-freezing
# updates in place); READ-ONLY over existing tables besides its own row; missing evidence degrades to honest
# nulls (never fabricates a fee or a regime) — the LLM never writes this, the deterministic gate alone promotes.

from __future__ import annotations

import hashlib
import json
from typing import Any

from cosmu.config.feature_registry import registry_version
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.live_eligibility import (
    paper_clock_origin,
    paper_net_return_pct,
    proven_regimes_for,
)
from cosmu.spine.venue import VenueCatalog, default_catalog


def params_hash(params: dict[str, Any]) -> str:
    """sha256 over the canonical NUMERIC params (sorted keys, floats rounded first) — the drift pin. Only the
    numeric knobs are hashed because that is exactly what the live/paper step uses (it drops non-numeric keys like
    `config_tag` before fitting); pinning those means a mismatch is a real param drift, not a label change. Live
    runs the FROZEN params; a hash mismatch is a detectable re-fit, not a silent re-derivation. Mirrors the
    staleness-pin pattern in research/summary_facts."""
    canonical = {
        k: round(float(v), 8)
        for k, v in sorted(params.items())
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def fee_model_snapshot(venues: list[str], *, catalog: VenueCatalog | None = None) -> dict[str, dict[str, float]]:
    """The {venue_id: {maker_bps, taker_bps}} the gate priced against, read off the catalog at promotion time.
    An unknown venue is skipped (honest — no fabricated fee). This is what live compares its FRESH fee against to
    detect a repricing the edge was never proven through."""
    catalog = catalog or default_catalog()
    out: dict[str, dict[str, float]] = {}
    for vid in venues:
        try:
            v = catalog.venue(vid)
        except KeyError:
            continue
        out[v.id] = {"maker_bps": float(v.maker_fee_bps), "taker_bps": float(v.taker_fee_bps)}
    return out


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value) if isinstance(value, str) else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _best_screen(store: Store, version_id: str) -> dict[str, Any] | None:
    """The gate score to freeze: the best screen backtest (gate-passed first, then highest deflated Sharpe).
    None when never screened — the freeze then records a null gate_score (honest)."""
    row = store.row(
        """
        SELECT oos_return, deflated_sharpe, passed_gates, holdout_passed
        FROM backtests
        WHERE strategy_version_id = ? AND kind = 'screen'
        ORDER BY passed_gates DESC, CAST(deflated_sharpe AS REAL) DESC, created_at DESC
        LIMIT 1
        """,
        (version_id,),
    )
    if row is None:
        return None

    def _num(x: Any) -> float | None:
        try:
            return round(float(x), 6)
        except (TypeError, ValueError):
            return None

    return {
        "oos_return": _num(row["oos_return"]),
        "deflated_sharpe": _num(row["deflated_sharpe"]),
        "passed_gates": bool(row["passed_gates"]),
        "holdout_passed": bool(row["holdout_passed"]),
    }


def freeze_promotion(store: Store, version_id: str, *, catalog: VenueCatalog | None = None) -> str | None:
    """Freeze ONE promoted version into the `strategy_promotions` record — the single source of truth live reads
    to replicate the Gate's verdict. The version row must already be COMMITTED (call after the persist batch, not
    inside it). Idempotent per version_id (re-freezing updates in place). Returns the promotion id, or None when
    the version doesn't exist (nothing to freeze). Deterministic, keyless, READ-ONLY besides its own row."""
    row = store.row("SELECT id, spec, params FROM strategy_versions WHERE id = ?", (version_id,))
    if row is None:
        return None
    spec = _loads(row["spec"])
    params = _loads(row["params"])
    universe = spec.get("universe") if isinstance(spec.get("universe"), dict) else {}
    venues = [v for v in (universe.get("venues") or []) if isinstance(v, str)]

    record = {
        "strategy_version_id": version_id,
        "lane": spec.get("lane") or "gate",
        "params_hash": params_hash(params),
        "params": json.dumps(params, sort_keys=True),
        "feature_registry_version": registry_version(),
        "universe_snapshot": json.dumps(
            {"venues": sorted(venues), "asset_classes": sorted(universe.get("asset_classes") or [])},
            sort_keys=True,
        ),
        "fee_model_snapshot": json.dumps(fee_model_snapshot(venues, catalog=catalog), sort_keys=True),
        "gate_score": json.dumps(_best_screen(store, version_id), sort_keys=True),
        "proven_regimes": json.dumps(sorted(proven_regimes_for(store, version_id)), sort_keys=True),
        "forward_clock_origin": paper_clock_origin(store, version_id),
        "net_return_pct": str(round(paper_net_return_pct(store, version_id), 6)),
        "promoted_at": utcnow(),
    }

    existing = store.row("SELECT id FROM strategy_promotions WHERE strategy_version_id = ?", (version_id,))
    if existing:
        cols = ", ".join(f"{k} = ?" for k in record if k != "strategy_version_id")
        vals = [v for k, v in record.items() if k != "strategy_version_id"]
        store.rows(f"UPDATE strategy_promotions SET {cols} WHERE strategy_version_id = ?", (*vals, version_id))
        store.append_event(actor="master", kind="promotion_frozen", ref_type="strategy_version", ref_id=version_id, payload={"lane": record["lane"], "refrozen": True})
        return str(existing["id"])
    pid = store.insert("strategy_promotions", record)
    store.append_event(actor="master", kind="promotion_frozen", ref_type="strategy_version", ref_id=version_id, payload={"lane": record["lane"], "params_hash": record["params_hash"]})
    return pid


def promotion_record(store: Store, version_id: str) -> dict[str, Any] | None:
    """Read a version's frozen promotion record (JSON fields parsed back to objects). None when the version was
    never promoted — the live lane reads this as 'not frozen → not armable' (fail-safe)."""
    row = store.row("SELECT * FROM strategy_promotions WHERE strategy_version_id = ?", (version_id,))
    if row is None:
        return None
    out = dict(row)
    for k in ("params", "universe_snapshot", "fee_model_snapshot", "gate_score", "proven_regimes"):
        if isinstance(out.get(k), str):
            try:
                out[k] = json.loads(out[k])
            except json.JSONDecodeError:
                pass
    return out
