# intent: assemble the full Mind payload — KNOWS (data sources grouped by perspective + freshness), THINKS (the
# analyst panel + debate), LEARNED (memory, the ML survival model, regime coverage, gate efficiency) — in one
# standardized shape the API serializes. `reflect()` persists a point-in-time snapshot so the agent accrues a
# MEMORY OF HOW IT THOUGHT over time. inputs: the Store + an optional real reference series; outputs: a dict /
# a persisted mind_reflections row. invariants: read-only when building; offline/LLM-optional; never fabricates
# (a source with no data reports honestly); the railguard holds — nothing here funds or fires.

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from cosmu.config.feature_registry import FEATURE_REGISTRY
from cosmu.knowledge.store import Store, utcnow
from cosmu.mind.analysts import ALL_ANALYSTS, gather_context
from cosmu.mind.debate import RAILGUARD, debate

# Map each registry source to the analyst perspective that reads it, so "what it knows" lines up with "how it
# thinks". Substring match on the feature's `source` (then a few name overrides) keeps this short and stable.
_PERSPECTIVE_BY_SOURCE: tuple[tuple[str, str], ...] = (
    ("parquet_bars", "Technical"),
    ("alternative.me", "Sentiment"),
    ("news", "Social & News"),
    ("opensky", "OSINT"),
    ("ccxt", "Positioning"),
    ("exchange", "Positioning"),
    ("coinglass", "Positioning"),
    ("cftc", "Positioning"),
    ("polymarket", "Prediction"),
    ("fred", "Macro"),
    ("cboe", "Macro"),
    ("defillama", "Macro"),
    ("fundamentals", "Macro"),
    ("sec_edgar", "Macro"),
)
_PERSPECTIVE_ORDER = ("Technical", "Macro", "Sentiment", "Social & News", "Positioning", "OSINT", "Prediction")


def _perspective_for(feature) -> str:
    for needle, perspective in _PERSPECTIVE_BY_SOURCE:
        if needle in feature.source:
            return perspective
    return "Other"


def build_mind(store: Store, *, reference_bars=None) -> dict[str, Any]:
    """The full Mind snapshot. Computes the panel once, debates a consensus, and bundles what the agent knows
    and has learned alongside it. Read-only and offline-safe; a perspective with no ingested data abstains.
    All reads share ONE connection (store.reading()) — opening one per query timed out the web on remote PG."""
    with store.reading():
        return _build_mind(store, reference_bars=reference_bars)


def _build_mind(store: Store, *, reference_bars=None) -> dict[str, Any]:
    ctx = gather_context(store, reference_bars=reference_bars)
    snap = debate([analyst(ctx) for analyst in ALL_ANALYSTS])
    return {
        "as_of": snap.as_of,
        "railguard": RAILGUARD,
        "consensus": snap.consensus,
        "conviction": snap.conviction,
        "agreement": snap.agreement,
        "contested": snap.contested,
        "narrative": snap.narrative,
        "stances": [asdict(s) for s in snap.stances],
        "bull_case": snap.bull_case,
        "bear_case": snap.bear_case,
        "knows": _knows(ctx),
        "learnings": _learnings(store, ctx),
    }


def reflect(store: Store, *, reference_bars=None) -> dict[str, Any] | None:
    """Persist ONE point-in-time reflection (the consensus + the full payload) so the agent builds a memory of
    how it thought over time. Defensive: the audit event always writes; the mind_reflections insert is wrapped
    so a prod database that has not yet had the additive table applied degrades gracefully (no crash)."""
    mind = build_mind(store, reference_bars=reference_bars)
    payload = {"consensus": mind["consensus"], "conviction": mind["conviction"], "agreement": mind["agreement"]}
    try:
        store.append_event(actor="master", kind="mind_reflection", ref_type="mind", payload=payload)
    except Exception:  # noqa: BLE001
        pass
    try:
        # Raw INSERT with an explicit column list (like gate_verdicts/events/trials): the table's id is an
        # auto-identity, so we must NOT inject one the way store.insert() does for uuid-keyed tables.
        store.rows(
            "INSERT INTO mind_reflections(ts, as_of, consensus, conviction, agreement, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                utcnow(),
                mind["as_of"],
                mind["consensus"],
                float(mind["conviction"]),
                float(mind["agreement"]),
                json.dumps(mind, sort_keys=True),
            ),
        )
    except Exception:  # noqa: BLE001 — additive table not applied to prod yet; the event above still records it
        return mind
    return mind


# --------------------------------------------------------------------------- KNOWS (sources + freshness)


def _knows(ctx) -> list[dict[str, Any]]:
    """The data the agent reads, grouped by perspective, each tagged with whether it is ingested + fresh.
    Honest: a registry source with no point-in-time value shows as 'not ingested yet', never as live."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for f in FEATURE_REGISTRY:
        if not f.enabled:
            continue
        perspective = _perspective_for(f)
        hit = ctx.values.get(f.name)
        item = {
            "name": f.name,
            "source": f.source,
            "tier": f.tier,
            "prior": f.prior,
            "ingested": hit is not None,
            "last_at": hit[1] if hit else None,
            "value": round(hit[0], 4) if hit else None,
            "low_confidence": f.tier == "tier1",
        }
        groups.setdefault(perspective, []).append(item)
    ordered: list[dict[str, Any]] = []
    for perspective in [*_PERSPECTIVE_ORDER, "Other"]:
        items = groups.get(perspective)
        if not items:
            continue
        items.sort(key=lambda i: (not i["ingested"], i["name"]))
        ordered.append({
            "perspective": perspective,
            "ingested": sum(1 for i in items if i["ingested"]),
            "total": len(items),
            "items": items,
        })
    return ordered


# --------------------------------------------------------------------------- LEARNED (memory + ML + regimes)


def _learnings(store: Store, ctx) -> dict[str, Any]:
    from cosmu.knowledge.memory import memory_insights

    ml = ctx.ml
    insights = memory_insights(store, limit=12)
    gate = _gate_efficiency(store)
    regimes = _regime_coverage(store)
    return {
        "insights": insights,
        "ml_trained": ml.trained,
        "ml_backend": ml.backend,
        "ml_auroc": ml.auroc,
        "ml_labels": ml.n_labels,
        "dead_ends": ctx.memory["dead_ends"],
        "winners": ctx.memory["winners"],
        "skills": ctx.memory["skills"],
        "gate_rate": gate["current"],
        "gate_trend": gate["trend"],
        "gate_improving": gate["improving"],
        "regime_grid": regimes["grid"],
        "regime_covered": regimes["covered"],
        "regime_total": regimes["total"],
    }


def _gate_efficiency(store: Store) -> dict[str, Any]:
    """Gate pass-rate trend over recent ticks — is the author learning from the graveyard? (Mirrors the
    intelligence read, kept here so the Mind has no cross-module private dependency.)"""
    try:
        rows = store.rows(
            "SELECT payload FROM events WHERE kind = 'autonomy_tick_completed' ORDER BY id DESC LIMIT 12"
        )
    except Exception:  # noqa: BLE001
        rows = []
    trend: list[float] = []
    for r in rows:
        payload = _payload(r.get("payload"))
        s = payload.get("summary", {})
        authored = int(s.get("authored", 0))
        passed = int(s.get("gated_passed", 0))
        if authored > 0:
            trend.append(round(passed / authored, 3))
    trend.reverse()
    current = trend[-1] if trend else 0.0
    improving = len(trend) >= 3 and trend[-1] > trend[0]
    return {"current": current, "trend": trend, "improving": improving}


def _regime_coverage(store: Store) -> dict[str, Any]:
    """Which market regimes funded strategies have proven edge in (the live-eligibility passport, aggregated)."""
    try:
        rows = store.rows(
            "SELECT b.regime_label FROM strategy_versions sv "
            "JOIN backtests b ON b.strategy_version_id = sv.id "
            "WHERE sv.status IN ('forward_test', 'live') AND b.passed_gates = 1"
        )
    except Exception:  # noqa: BLE001
        rows = []
    coverage: dict[str, int] = {}
    for r in rows:
        label = r.get("regime_label") or "mixed"
        coverage[label] = coverage.get(label, 0) + 1
    grid: list[dict[str, Any]] = []
    for trend in ("bull", "bear", "chop"):
        for vol in ("low", "mid", "high"):
            key = f"{trend}/{vol}"
            grid.append({"regime": key, "trend": trend, "vol": vol, "strategies": coverage.get(key, 0)})
    covered = sum(1 for g in grid if g["strategies"] > 0)
    return {"grid": grid, "covered": covered, "total": len(grid)}


def _payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}
