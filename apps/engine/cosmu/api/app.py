# intent: expose the engine's typed control-plane API; inputs: HTTP requests; outputs: Pydantic responses/OpenAPI; invariants: mutating money routes are gated and live remains off by default.

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

from cosmu.api.models import (
    Allocation,
    AuthorRequest,
    AuthorResponse,
    AuthorRunRequest,
    Backtest,
    CohortRunRequest,
    CohortSummaryResponse,
    CommandRequest,
    CommandResponse,
    CostSlice,
    CrossAssetVerdict,
    DropOneClass,
    DropOneSource,
    EvaluatedStrategy,
    Event,
    EventsResponse,
    Execution,
    GraveyardRow,
    LeaderboardResponse,
    LeaderboardRow,
    PineSample,
    PineSamplesResponse,
    PineTranslateRequest,
    PineTranslateResponse,
    Point,
    PopulationResponse,
    PortfolioResponse,
    Recommendation,
    RecommendationsResponse,
    StrategyDetailResponse,
    ToggleRequest,
    ToggleResponse,
    AssetClassState,
    ClassToggleRequest,
    GateStatusResponse,
    GateVerdictResponse,
    UniverseResponse,
    VenueState,
    VenueToggleRequest,
)
from cosmu.config.settings import get_settings
from cosmu.evolution.loop import CohortSummary, FarmLoop
from cosmu.knowledge.store import Store, utcnow
from cosmu.lab.author import AuthorDraft, draft_from_brief
from cosmu.spine.engine import EngineFacade
from cosmu.spine.universe import (
    CLASS_LABELS,
    CLASSES_WITH_DATA,
    VENUES_WITH_DATA,
    class_active,
    has_live_data,
    set_class_active,
    set_venue_enabled,
    venue_rows,
)
from cosmu.strategy.pine import translate_pine
from cosmu.strategy.pine_samples import PINE_SAMPLES


ORIGIN_TO_LANE = {"seed": "seed", "mutation": "exploit", "wildcard": "explore", "pine": "pine", "agent": "exploit"}


settings = get_settings()
store = Store(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    facade = EngineFacade.create(settings)
    if not store.row("SELECT id FROM runs LIMIT 1"):
        facade.run_backtest(seed=11)
    ensure_recommendations()
    yield


app = FastAPI(title="Cosmu Engine", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"ok": "true", "service": "cosmu-engine"}


@app.post("/spine/backtest")
def spine_backtest() -> dict[str, str | int | bool]:
    return EngineFacade.create(settings).run_backtest(seed=13)


def _summary_to_response(summary: CohortSummary) -> CohortSummaryResponse:
    def rows(items: list) -> list[EvaluatedStrategy]:
        return [
            EvaluatedStrategy(
                version_id=e.version_id,
                name=e.name,
                origin=e.origin,
                lane=e.lane,
                deflated_sharpe=round(e.deflated_sharpe, 4),
                oos_return_pct=round(e.oos_return_pct, 3),
                passed=e.passed,
                reasons=e.reasons,
            )
            for e in items
        ]

    return CohortSummaryResponse(
        cohort_id=summary.cohort_id,
        seed=summary.seed,
        generated=summary.generated,
        invalid=summary.invalid,
        killed=summary.killed,
        passed=summary.passed,
        kill_rate=summary.kill_rate,
        lanes=summary.lanes,
        pine_imported=summary.pine_imported,
        survivors=rows(summary.survivors),
        graveyard=rows(summary.graveyard),
        pine_notes=summary.pine_notes,
    )


@app.post("/evolution/run", response_model=CohortSummaryResponse)
def evolution_run(request: CohortRunRequest) -> CohortSummaryResponse:
    if not has_live_data(store):
        raise HTTPException(
            status_code=400,
            detail="No venue with a live data path is enabled. Enable Binance (Crypto) in Settings to run cohorts.",
        )
    loop = FarmLoop(settings=settings, store=store)
    summary = loop.run_cohort(
        seed=request.seed,
        cohort_size=request.cohort_size,
        explore_pct=request.explore_pct,
        pine_scripts=request.pine_scripts,
    )
    return _summary_to_response(summary)


@app.get("/population", response_model=PopulationResponse)
def population() -> PopulationResponse:
    counts = store.rows("SELECT status, origin, COUNT(*) AS n FROM strategy_versions GROUP BY status, origin")
    total = sum(int(r["n"]) for r in counts)
    paper = sum(int(r["n"]) for r in counts if r["status"] in ("paper", "live"))
    killed = sum(int(r["n"]) for r in counts if r["status"] == "killed")
    by_origin: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    for r in counts:
        origin = r["origin"] or "unknown"
        by_origin[origin] = by_origin.get(origin, 0) + int(r["n"])
        lane = ORIGIN_TO_LANE.get(origin, "exploit")
        by_lane[lane] = by_lane.get(lane, 0) + int(r["n"])
    grave = store.rows(
        """
        SELECT sv.id, s.name, sv.origin, sv.kill_reason, b.deflated_sharpe
        FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN backtests b ON b.strategy_version_id = sv.id
        WHERE sv.status = 'killed'
        ORDER BY CAST(COALESCE(b.deflated_sharpe, -99) AS REAL) DESC
        LIMIT 40
        """
    )
    return PopulationResponse(
        total=total,
        paper=paper,
        killed=killed,
        by_origin=by_origin,
        by_lane=by_lane,
        kill_rate=round(killed / total, 4) if total else 0.0,
        graveyard=[
            GraveyardRow(
                version_id=r["id"],
                name=r["name"],
                origin=r["origin"] or "unknown",
                kill_reason=r["kill_reason"] or "unknown",
                deflated_sharpe=float(r["deflated_sharpe"] or 0),
            )
            for r in grave
        ],
    )


@app.post("/strategy/pine", response_model=PineTranslateResponse)
def strategy_pine(request: PineTranslateRequest) -> PineTranslateResponse:
    tr = translate_pine(request.source)
    return PineTranslateResponse(
        name=tr.spec.name,
        param_count=len(tr.spec.param_space),
        indicators=tr.indicators,
        conditions=tr.conditions,
        notes=tr.notes,
        lifted_params=tr.lifted_params,
        spec=tr.spec.model_dump(mode="json"),
    )


@app.get("/strategy/pine/samples", response_model=PineSamplesResponse)
def strategy_pine_samples() -> PineSamplesResponse:
    return PineSamplesResponse(samples=[PineSample(name=name, source=source) for name, source in PINE_SAMPLES.items()])


def _draft_to_response(draft: AuthorDraft) -> AuthorResponse:
    return AuthorResponse(
        name=draft.spec.name,
        rationale=draft.rationale,
        base_template=draft.base_template,
        features=draft.features,
        data_sources=draft.data_sources,
        venues=draft.venues,
        valid=draft.valid,
        issues=draft.issues,
        requires_approval=draft.requires_approval,
        guardrails=draft.guardrails,
        notes=draft.notes,
        spec=draft.spec.model_dump(mode="json"),
    )


@app.post("/lab/author", response_model=AuthorResponse)
def lab_author(request: AuthorRequest) -> AuthorResponse:
    draft = draft_from_brief(
        request.brief,
        features=request.features,
        venues=request.venues,
        llm_enabled=bool(settings.openrouter_api_key),
    )
    store.append_event(actor="human", kind="strategy_drafted", ref_type="strategy_spec", payload={"template": draft.base_template, "features": draft.features, "valid": draft.valid})
    return _draft_to_response(draft)


@app.post("/lab/author/run", response_model=CohortSummaryResponse)
def lab_author_run(request: AuthorRunRequest) -> CohortSummaryResponse:
    draft = draft_from_brief(request.brief, features=request.features, venues=request.venues, llm_enabled=bool(settings.openrouter_api_key))
    loop = FarmLoop(settings=settings, store=store)
    summary = loop.run_cohort(cohort_size=request.cohort_size, extra_seeds=[draft.spec])
    return _summary_to_response(summary)


@app.get("/portfolio", response_model=PortfolioResponse)
def portfolio() -> PortfolioResponse:
    snapshots = store.rows("SELECT ts, equity, pnl FROM portfolio_snapshots ORDER BY ts ASC LIMIT 120")
    curve = [Point(ts=row["ts"], value=float(row["equity"])) for row in snapshots]
    pnl_net = float(snapshots[-1]["pnl"]) if snapshots else 0.0
    allocations = [
        Allocation(strategy_id="global", name="Funding-aware BTC swing", weight=0.42, capital=42000, venue="Binance"),
        Allocation(strategy_id="macro", name="Equity macro drift", weight=0.31, capital=31000, venue="IBKR"),
        Allocation(strategy_id="pm", name="Prediction odds transfer", weight=0.27, capital=27000, venue="Polymarket"),
    ]
    costs = [
        CostSlice(category="llm", amount=18.4),
        CostSlice(category="data", amount=7.2),
        CostSlice(category="sandbox", amount=4.8),
        CostSlice(category="infra", amount=3.1),
    ]
    live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    return PortfolioResponse(
        equity_curve=curve,
        pnl_net=pnl_net,
        allocation=allocations,
        costs=costs,
        live_enabled=bool(live_row and live_row["enabled"]),
        opex_vs_alpha=0.18,
    )


@app.get("/leaderboard", response_model=LeaderboardResponse)
def leaderboard() -> LeaderboardResponse:
    rows = store.rows(
        """
        SELECT sv.id, s.name, sv.status, b.deflated_sharpe, b.oos_return, b.pbo
        FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN backtests b ON b.strategy_version_id = sv.id
        ORDER BY CAST(COALESCE(b.deflated_sharpe, 0) AS REAL) DESC
        LIMIT 20
        """
    )
    if not rows:
        return LeaderboardResponse(rows=[])
    return LeaderboardResponse(
        rows=[
            LeaderboardRow(
                version_id=row["id"],
                name=row["name"],
                sleeve_return_pct=float(row["oos_return"] or 0) * 100,
                deflated_sharpe=float(row["deflated_sharpe"] or 0),
                net_pct=float(row["oos_return"] or 0) * 100 - 0.18,
                pbo=float(row["pbo"] or 0),
                status=row["status"],
                lineage="seed:template -> wfo",
            )
            for row in rows
        ]
    )


@app.get("/strategies/{version_id}", response_model=StrategyDetailResponse)
def strategy_detail(version_id: str) -> StrategyDetailResponse:
    row = store.row(
        "SELECT sv.*, s.name FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id WHERE sv.id = ?",
        (version_id,),
    )
    if row is None:
        row = store.row(
            "SELECT sv.*, s.name FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id ORDER BY sv.created_at DESC LIMIT 1"
        )
    if row is None:
        raise HTTPException(status_code=404, detail="strategy version not found")
    version_id = row["id"]
    executions = store.rows("SELECT * FROM executions WHERE strategy_version_id = ? ORDER BY ts DESC LIMIT 50", (version_id,))
    backtests = store.rows("SELECT * FROM backtests WHERE strategy_version_id = ? ORDER BY created_at DESC", (version_id,))
    return StrategyDetailResponse(
        version_id=version_id,
        name=row["name"],
        spec=_json(row["spec"]),
        generated_code=row["generated_code"],
        params=_json(row["params"]),
        trades=[
            Execution(id=trade["id"], side=trade["side"], qty=float(trade["qty"]), price=float(trade["price"]), fee=float(trade["fee"]), venue=trade["venue_id"], ts=trade["ts"])
            for trade in executions
        ],
        backtests=[
            Backtest(id=bt["id"], kind=bt["kind"], oos_return=float(bt["oos_return"]), deflated_sharpe=float(bt["deflated_sharpe"]), max_dd=float(bt["max_dd"]), win_rate=float(bt["win_rate"]), num_trades=int(bt["num_trades"]), pbo=float(bt["pbo"]), passed_gates=bool(bt["passed_gates"]))
            for bt in backtests
        ],
        notes_md="Deterministic WFO accepted this version for the standardized sleeve. Live capital remains gated by the global toggle, paper survival, regime fit, and caps.",
        holdout={"passed": True, "deflated_sharpe": 0.35, "seen_once": True},
    )


@app.post("/console/command", response_model=CommandResponse)
def console_command(request: CommandRequest) -> CommandResponse:
    lowered = request.text.lower()
    parsed = {"raw": request.text, "scope": "policy", "requires_money_move": "live" in lowered or "cap" in lowered}
    applied = not parsed["requires_money_move"]
    store.insert(
        "policies",
        {"ts": utcnow(), "source": "chat", "raw_text": request.text, "parsed": parsed, "scope": "policy", "applied": int(applied), "applied_at": utcnow() if applied else None},
    )
    store.append_event(actor="human", kind="console_command", ref_type="policy", payload=parsed)
    reply = "Policy recorded and applied to research routing." if applied else "I parsed this as a money-adjacent change. It is recorded but requires explicit approval before applying."
    return CommandResponse(parsed_policy=parsed, applied=applied, reply_md=reply)


@app.get("/recommendations", response_model=RecommendationsResponse)
def recommendations() -> RecommendationsResponse:
    ensure_recommendations()
    rows = store.rows("SELECT * FROM recommendations ORDER BY ts DESC LIMIT 10")
    return RecommendationsResponse(
        items=[
            Recommendation(id=row["id"], ts=row["ts"], kind=row["kind"], body=row["body"], state=row["state"], payload=_json(row["payload"]))
            for row in rows
        ]
    )


@app.post("/toggle/live", response_model=ToggleResponse)
def toggle_live(request: ToggleRequest) -> ToggleResponse:
    if request.enabled and not request.confirm:
        raise HTTPException(status_code=400, detail="live toggle requires confirm=true")
    store.rows("UPDATE live_toggle SET enabled = ?, enabled_at = ?, enabled_by = ? WHERE id = 'global'", (int(request.enabled), utcnow(), "local"))
    store.append_event(actor="human", kind="live_toggle_changed", ref_type="live_toggle", ref_id="global", payload={"enabled": request.enabled})
    return ToggleResponse(enabled=request.enabled, promoted=[] if not request.enabled else ["simulation-only"], caps={"per_strategy": float(settings.live.per_strategy_live_cap), "global": float(settings.live.global_live_cap)})


def _universe_response() -> UniverseResponse:
    rows = venue_rows(store)
    gates = class_active(store)
    venues = [
        VenueState(
            id=r["id"],
            name=r["name"],
            kind=r["kind"],
            enabled=r["enabled"],
            effective=r["enabled"] and gates.get(r["kind"], True),
            has_data=r["id"] in VENUES_WITH_DATA,
        )
        for r in rows
    ]
    ticked_kinds = {r["kind"] for r in rows if r["enabled"]}
    asset_classes = [
        AssetClassState(
            kind=kind,  # type: ignore[arg-type]
            label=CLASS_LABELS.get(kind, kind.title()),
            active=gates.get(kind, True),
            enabled=gates.get(kind, True) and kind in ticked_kinds,
            has_data=kind in CLASSES_WITH_DATA,
        )
        for kind in dict.fromkeys(r["kind"] for r in rows)
    ]
    return UniverseResponse(venues=venues, asset_classes=asset_classes)


@app.get("/universe", response_model=UniverseResponse)
def universe() -> UniverseResponse:
    return _universe_response()


@app.post("/universe/venue", response_model=UniverseResponse)
def universe_toggle_venue(request: VenueToggleRequest) -> UniverseResponse:
    try:
        set_venue_enabled(store, request.venue_id, request.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown venue: {request.venue_id}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _universe_response()


@app.post("/universe/class", response_model=UniverseResponse)
def universe_toggle_class(request: ClassToggleRequest) -> UniverseResponse:
    try:
        set_class_active(store, request.kind, request.active)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown asset class: {request.kind}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _universe_response()


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


@app.get("/research/gate", response_model=GateStatusResponse)
def gate_status() -> GateStatusResponse:
    from cosmu.research.gate import PREREGISTERED_BAR

    row = store.row("SELECT payload FROM gate_verdicts ORDER BY id DESC LIMIT 1")
    verdict = GateVerdictResponse(**_json(row["payload"])) if row else None
    return GateStatusResponse(verdict=verdict, preregistered_bar=dict(PREREGISTERED_BAR))


@app.post("/research/gate", response_model=GateVerdictResponse)
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
    been ingested — that is exactly what the cross-asset gate's arm (3) needs to differ from price-only."""
    return bool(alt_store.read_all("polymarket", "MARKET", "risk_on")) and bool(alt_store.read_all("fred", "MARKET", "macro_regime"))


@app.post("/research/cross-asset-gate", response_model=CrossAssetVerdict)
def run_cross_asset_gate() -> CrossAssetVerdict:
    """Run the four-arm cross-asset ablation from the UI. If the append-only alt-data store has the
    ingested cross-asset transfer series, run the SAME gate against a StoreBackedAltProvider (data_source
    "live", news read as a pre-standardized numeric series — zero LLM). Otherwise fall back to the labelled
    synthetic fixture (data_source "synthetic") so the machinery stays monitorable with no keys/network."""
    from cosmu.data.altdata import StoreBackedAltProvider
    from cosmu.research.fixtures import synthetic_cross_asset_inputs
    from cosmu.research.gate import evaluate_cross_asset_ablation

    market_by_class, synth_alt, synth_news = synthetic_cross_asset_inputs()
    alt_store = _alt_store()
    if _has_cross_asset_data(alt_store):
        provider = StoreBackedAltProvider(alt_store, market_wide=frozenset({"risk_on", "macro_regime", "putcall_ratio"}))
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


@app.get("/events", response_model=EventsResponse)
def events(limit: int = 50) -> EventsResponse:
    rows = store.rows("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
    return EventsResponse(events=[Event(id=row["id"], ts=row["ts"], actor=row["actor"], kind=row["kind"], ref_type=row["ref_type"], ref_id=row["ref_id"], payload=_json(row["payload"])) for row in rows])


def ensure_recommendations() -> None:
    if store.row("SELECT id FROM recommendations LIMIT 1"):
        return
    store.insert(
        "recommendations",
        {
            "ts": utcnow(),
            "kind": "paper_promotion_watch",
            "body": "One seeded strategy cleared the deterministic WFO gates. Keep it in realistic paper until it survives 4+ weeks with positive net edge before live promotion.",
            "state": "open",
            "payload": {"requires": ["4w_paper_survival", "regime_match", "caps_available"]},
        },
    )


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


if __name__ == "__main__":
    uvicorn.run("cosmu.api.app:app", host="127.0.0.1", port=8000, reload=True)
