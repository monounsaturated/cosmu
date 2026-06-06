# intent: research surface — the deterministic edge Gate, cross-asset ablation, brain snapshot, alpha-decay; inputs: none/POST triggers; outputs: typed verdicts/snapshots; invariants: LLM-free gate/money path; synthetic data is always labelled.

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from cosmu.api._shared import _brain_reference_bars, _json, settings, store
from cosmu.api.models import (
    BrainGated,
    BrainGraveyard,
    BrainRanking,
    BrainRegime,
    BrainResponse,
    BrainSource,
    BrainSurvivor,
    CrossAssetVerdict,
    DriftResponse,
    DriftTrack,
    DropOneClass,
    DropOneSource,
    GateStatusResponse,
    GateVerdictResponse,
)
from cosmu.knowledge.store import utcnow

router = APIRouter()


def _gate_to_response(verdict: Any, *, data_source: str) -> GateVerdictResponse:
    return GateVerdictResponse(
        decision=verdict.decision,
        passed=verdict.passed,
        best_signal=verdict.best_signal,
        deflated_sharpe_prob=verdict.deflated_sharpe_prob,
        cscv_pbo=verdict.cscv_pbo,
        buy_and_hold_return=verdict.buy_and_hold_return,
        best_return=verdict.best_return,
        regimes_positive=verdict.regimes_positive,
        num_trades=verdict.num_trades,
        max_drawdown=verdict.max_drawdown,
        attempts=verdict.attempts,
        reasons=verdict.reasons,
        bar=verdict.bar,
        data_source=data_source,
        ts=utcnow(),
    )


@router.get("/research/gate", response_model=GateStatusResponse)
def gate_status() -> GateStatusResponse:
    from cosmu.research.gate import PREREGISTERED_BAR

    row = store.row("SELECT payload FROM gate_verdicts ORDER BY id DESC LIMIT 1")
    verdict = GateVerdictResponse(**_json(row["payload"])) if row else None
    return GateStatusResponse(verdict=verdict, preregistered_bar=dict(PREREGISTERED_BAR))


@router.post("/research/gate", response_model=GateVerdictResponse)
def run_gate() -> GateVerdictResponse:
    # Until live LunarCrush + bars are wired, the gate runs on a labelled synthetic fixture so the
    # machinery is monitorable. The data_source flag keeps that honest in the UI.
    from cosmu.research.fixtures import synthetic_gate_inputs
    from cosmu.research.gate import evaluate_gate

    market, provider = synthetic_gate_inputs()
    verdict = evaluate_gate(market, provider, store)
    response = _gate_to_response(verdict, data_source="synthetic")
    store.rows(
        "INSERT INTO gate_verdicts(ts, decision, data_source, payload) VALUES (?, ?, ?, ?)",
        (response.ts, response.decision, response.data_source, json.dumps(response.model_dump(), sort_keys=True)),
    )
    store.append_event(actor="master", kind="edge_gate_run", ref_type="gate", payload={"decision": verdict.decision, "data_source": "synthetic"})
    return response


def _alt_store():  # noqa: ANN202 - returns AltDataStore
    """The append-only point-in-time JSONL alt-data store a scheduled worker fills from the free sources."""
    from cosmu.data.altdata import AltDataStore

    return AltDataStore()


def _has_cross_asset_data(alt_store) -> bool:  # noqa: ANN001
    """True once the two cross-asset transfer series (prediction-market risk_on + FRED macro_regime) have
    been ingested — that is exactly what the cross-asset gate's arm (3) needs to differ from price-only.
    The prediction-market series is stored under its CANONICAL name `pm_risk_on` (ingest run_once); reading
    the old `risk_on` name here made this predicate always False on real data, so the UI silently fell back
    to the synthetic fixture and never ran the live gate. Mirrors cosmu/research/loop._has_cross_asset_data."""
    return bool(alt_store.read_all("polymarket", "MARKET", "pm_risk_on")) and bool(alt_store.read_all("fred", "MARKET", "macro_regime"))


@router.post("/research/cross-asset-gate", response_model=CrossAssetVerdict)
def run_cross_asset_gate() -> CrossAssetVerdict:
    """Run the four-arm cross-asset ablation from the UI. If the append-only alt-data store has the
    ingested cross-asset transfer series, run the SAME gate against a StoreBackedAltProvider (data_source
    "live", news read as a pre-standardized numeric series — zero LLM). Otherwise fall back to the labelled
    synthetic fixture (data_source "synthetic") so the machinery stays monitorable with no keys/network."""
    from cosmu.data.altdata import StoreBackedAltProvider
    from cosmu.data.sources.multiasset import MULTIASSET_METRICS
    from cosmu.research.fixtures import synthetic_cross_asset_inputs
    from cosmu.research.gate import evaluate_cross_asset_ablation

    market_by_class, synth_alt, synth_news = synthetic_cross_asset_inputs()
    alt_store = _alt_store()
    if _has_cross_asset_data(alt_store):
        # Canonical market-wide set, mirroring cosmu/research/loop.run_once: the gate requests the
        # transfer feature as "risk_on" but it is STORED + routed as "pm_risk_on" (the StoreBackedAltProvider
        # rewrites the request), so pm_risk_on — not risk_on — must be flagged market-wide here. Include the
        # multiasset price-level series too so the cross-market composite reads under the MARKET key.
        provider = StoreBackedAltProvider(alt_store, market_wide=frozenset({"pm_risk_on", "macro_regime", "putcall_ratio", *MULTIASSET_METRICS}))
        verdict = evaluate_cross_asset_ablation(market_by_class, provider, None, store)
        data_source = "live"
    else:
        verdict = evaluate_cross_asset_ablation(market_by_class, synth_alt, synth_news, store)
        data_source = "synthetic"

    response = CrossAssetVerdict(
        decision=verdict.decision,
        passed=verdict.passed,
        price_only_return=verdict.price_only_return,
        single_alt_return=verdict.single_alt_return,
        xasset_return=verdict.xasset_return,
        buy_and_hold_return=verdict.buy_and_hold_return,
        xasset_dsr=verdict.xasset_dsr,
        single_alt_dsr=verdict.single_alt_dsr,
        cscv_pbo=verdict.cscv_pbo,
        regimes_positive=verdict.regimes_positive,
        num_trades=verdict.num_trades,
        max_drawdown=verdict.max_drawdown,
        attempts=verdict.attempts,
        drop_one_source=[DropOneSource(source=d.source, sharpe_without=d.sharpe_without, delta=d.delta) for d in verdict.drop_one_source],
        drop_one_class=[DropOneClass(asset_class=c.asset_class, sharpe_without=c.sharpe_without, delta=c.delta) for c in verdict.drop_one_class],
        reasons=verdict.reasons,
        bar=verdict.bar,
        data_source=data_source,
    )
    store.rows(
        "INSERT INTO gate_verdicts(ts, decision, data_source, payload) VALUES (?, ?, ?, ?)",
        (utcnow(), response.decision, data_source, json.dumps(response.model_dump(), sort_keys=True)),
    )
    store.append_event(actor="master", kind="cross_asset_gate_run", ref_type="gate", payload={"decision": verdict.decision, "data_source": data_source})
    return response


@router.get("/research/brain", response_model=BrainResponse)
def research_brain() -> BrainResponse:
    """The live brain snapshot: LLM on/off, the latest research pass's gated counts + survivors + graveyard,
    the propose-only sources/tools, the current market regime, and the survival model's validation-queue
    ranking. If no real pass has run yet, the snapshot is empty (we never seed a synthetic pass into prod). The
    survival ranking ORDERS the queue — it is never a veto; the deterministic gate alone decided who passed."""
    from cosmu.config.feature_registry import FEATURE_REGISTRY
    from cosmu.lab.tools.research_tools import research_tool_bus
    from cosmu.ml.regime import current_regime

    # Read the latest REAL research pass (written by the 4h cron / POST /autonomy/tick on live Binance data).
    # If none has run yet we return an honest empty snapshot — we never seed a synthetic pass into prod just to
    # populate a page (the app must not display fabricated edge).
    row = store.row("SELECT payload FROM events WHERE kind = 'research_pass' ORDER BY id DESC LIMIT 1")
    payload = _json(row["payload"]) if row else {}

    survivors = [
        BrainSurvivor(version_id=s["version_id"], name=s["name"], net_pct=float(s.get("net_pct", 0.0)), survival_score=float(s.get("survival_score", 0.0)))
        for s in payload.get("survivors", [])
    ]
    graveyard = [BrainGraveyard(name=g["name"], reasons=list(g.get("reasons", []))) for g in payload.get("graveyard", [])]
    ranking = [
        BrainRanking(version_id=r["version_id"], name=r["name"], score=float(r.get("score", 0.0)), trained=bool(r.get("trained", False)))
        for r in payload.get("survival_ranking", [])
    ]
    gated = BrainGated(
        generated=int(payload.get("generated", 0)),
        passed=int(payload.get("passed", 0)),
        killed=int(payload.get("killed", 0)),
        kill_rate=float(payload.get("kill_rate", 0.0)),
    )
    sources = [
        BrainSource(name=f.name, kind=f.source, low_confidence=(f.tier == "tier1"))
        for f in FEATURE_REGISTRY
        if f.enabled
    ]
    tools = [t["name"] for t in research_tool_bus().list_tools()]
    regime = current_regime(_brain_reference_bars())
    return BrainResponse(
        llm="on" if settings.openrouter_api_key else "off",
        gated=gated,
        survivors=survivors,
        graveyard=graveyard,
        sources=sources,
        tools=tools,
        regime=BrainRegime(label=regime.label, vol_bucket=regime.vol_bucket, trend=regime.trend),
        survival_ranking=ranking,
    )


@router.get("/research/drift", response_model=DriftResponse)
def research_drift() -> DriftResponse:
    """Per-funded-track ALPHA-DECAY snapshot (master/drift): edge half-life + how far live has drifted below the
    edge it was funded on, and whether the anticipatory monitor recommends pulling capital BEFORE P&L turns.
    Read-only + deterministic — the monitor only recommends; the deterministic lifecycle + live toggle move money."""
    from cosmu.master.drift import assess_drift, funded_track_ids, track_return_series

    tracks = []
    for vid in funded_track_ids(store):
        v = assess_drift(vid, track_return_series(store, vid))
        tracks.append(
            DriftTrack(
                version_id=vid,
                defund=v.defund,
                reason=v.reason,
                half_life=v.decay.half_life,
                periods_to_zero=v.decay.periods_to_zero,
                realized_edge=v.drift.realized_edge,
                reference_edge=v.drift.reference_edge,
                reference=v.drift.reference,
                z=v.drift.z,
                cusum=v.drift.cusum,
                n=v.drift.n,
            )
        )
    return DriftResponse(tracks=tracks)
