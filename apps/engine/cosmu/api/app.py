# intent: expose the engine's typed control-plane API; inputs: HTTP requests; outputs: Pydantic responses/OpenAPI; invariants: mutating money routes are gated and live remains off by default.

from __future__ import annotations

import json
import math
from contextlib import asynccontextmanager
from typing import Any

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from cosmu.api.models import (
    ActivateRequest,
    ActivateResponse,
    AutonomyPauseResponse,
    AutonomyStatusResponse,
    AutonomyTickResponse,
    AuthorRequest,
    AuthorResponse,
    AuthorRunRequest,
    Backtest,
    BrainGated,
    BrainGraveyard,
    BrainRanking,
    BrainRegime,
    BrainResponse,
    BrainSource,
    BrainSurvivor,
    CohortRunRequest,
    CohortSummaryResponse,
    CommandRequest,
    CommandResponse,
    CostByCategory,
    CostPerStrategy,
    CostSlice,
    CostsResponse,
    InfraLine,
    LlmCallSummary,
    CrossAssetVerdict,
    DefundRequest,
    DefundResponse,
    DriftResponse,
    DriftTrack,
    DropOneClass,
    DropOneSource,
    EligibleStrategy,
    EvaluatedStrategy,
    Event,
    EventsResponse,
    Execution,
    FinderResponse,
    FinderRunRequest,
    FinderVariant,
    InboxIdeaRequest,
    InboxIdeaResponse,
    InboxQueueItem,
    InboxQueueResponse,
    IntelligenceResponse,
    MindResponse,
    NewsEventRow,
    NewsIntelResponse,
    ScoreCategory,
    ScoreSourceRow,
    ScoresResponse,
    SettingsKeyRow,
    SettingsKeysResponse,
    SourceTrustResponse,
    SourceTrustRow,
    GraveyardRow,
    LaunchActivateRequest,
    LaunchActivateResponse,
    MlFeatureWeight,
    MlRankedItem,
    MlRequest,
    MlResponse,
    LeaderboardResponse,
    LeaderboardRow,
    LiveCaps,
    LivePosition,
    LivePositionsResponse,
    LiveVenue,
    LiveVenuesResponse,
    JurisdictionOption,
    JurisdictionsResponse,
    SetJurisdictionRequest,
    PineSample,
    PineSamplesResponse,
    PineTranslateRequest,
    PineTranslateResponse,
    MemoryInsight,
    MemoryInsightsResponse,
    Point,
    PopulationResponse,
    OverviewResponse,
    Recommendation,
    RecommendationActionResponse,
    RecommendationsResponse,
    Skill,
    SkillsResponse,
    StrategyDetailResponse,
    ToggleRequest,
    ToggleResponse,
    AssetClassState,
    ClassToggleRequest,
    GateStatusResponse,
    GateVerdictResponse,
    UniverseResponse,
    VenueCatalogResponse,
    VenueFeeInfo,
    VenueFeeTierInfo,
    VenueInstrumentInfo,
    VenueState,
    VenueToggleRequest,
)
from cosmu.adapters.exec.binance import BinanceSpotExecutionAdapter, resolve_mode
from cosmu.config.settings import get_settings
from cosmu.evolution.loop import CohortSummary, FarmLoop
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.forward_maturity import maturity as forward_maturity
from cosmu.master.portfolio import Portfolio
from cosmu.lab.author import AuthorDraft, draft_from_brief
from cosmu.spine.engine import EngineFacade
from cosmu.spine.venue import SUPPORTED_JURISDICTIONS, default_catalog
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
try:
    store = Store(settings)
except Exception:
    from cosmu.config.settings import Settings as _S
    store = Store(_S(database_url="sqlite:///.cosmu/fallback.sqlite3"))


def _metric(value: object, default: float = 0.0) -> float:
    """Coerce a DB numeric into a real, FINITE float for the typed web contract.

    Several response models (e.g. LeaderboardRow) promise non-null `number` for
    every metric, but the source rows come from a LEFT JOIN on `backtests`:
    a Version with no backtest yields NULL, and a degenerate backtest can yield
    NaN/inf. Both break the contract downstream — NULL becomes `undefined` and
    crashes `x.toFixed()` in the web build, NaN/inf serialize as invalid JSON.
    So we collapse anything null/non-numeric/non-finite to a documented 0.0
    sentinel BEFORE serialization. (Plain `x or 0` is NOT enough: `NaN or 0`
    is NaN, since NaN is truthy.)
    """
    try:
        out = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _portfolio() -> Portfolio:
    return Portfolio(store, bankroll=settings.sim_bankroll, daily_loss_cap=settings.live.daily_loss_cap)


def _live_mode() -> str:
    """The mode GET /live/positions reports — the adapter's resolved mode (testnet/live) or sim if disabled."""
    mode = resolve_mode(settings)
    return mode if mode in ("testnet", "live") else "sim"


def _live_caps_row() -> dict[str, float]:
    row = store.row("SELECT max_notional, max_daily_loss FROM live_caps WHERE id = 'global'")
    if row:
        return {
            "per_strategy_cap": float(settings.live.per_strategy_live_cap),
            "global_cap": float(row["max_notional"]),
            "max_daily_loss": float(row["max_daily_loss"]),
        }
    return {
        "per_strategy_cap": float(settings.live.per_strategy_live_cap),
        "global_cap": float(settings.live.global_live_cap),
        "max_daily_loss": float(settings.live.daily_loss_cap),
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    import threading

    def _boot():
        try:
            facade = EngineFacade.create(settings)
            if not store.row("SELECT id FROM runs LIMIT 1"):
                facade.run_backtest(seed=11)
            ensure_recommendations()
            _scan_inbox_on_startup()
            _fund_tracks_on_startup()
        except Exception:  # noqa: BLE001 — boot tasks are best-effort; never crash the app
            pass

    threading.Thread(target=_boot, daemon=True).start()
    yield


def _fund_tracks_on_startup() -> None:
    """Close the loop on boot: if gate-passed survivors exist with tracks but no sim positions are open yet, open
    a standalone forward-test track for each so GET /overview reflects genuinely funded tracks (no fabricated
    numbers). Best-effort + offline-safe; never blocks startup."""
    try:
        from cosmu.orchestrator import fund_tracks_from_survivors

        if store.row("SELECT id FROM positions WHERE CAST(qty AS REAL) != 0 LIMIT 1"):
            return  # already funded — idempotent, don't double-open
        if not store.row("SELECT sv.id FROM strategy_versions sv JOIN tracks tr ON tr.strategy_version_id = sv.id WHERE sv.status IN ('forward_test','live') LIMIT 1"):
            return  # no survivors yet — honest empty state
        fund_tracks_from_survivors(store, bankroll=settings.sim_bankroll)
    except Exception:  # noqa: BLE001 — funding is best-effort; a data/network hiccup must not break boot
        pass


def _scan_inbox_on_startup() -> None:
    """Scan strategies/inbox/*.{md,pine,json} on boot — idempotent (unchanged files skipped) and offline-safe, so
    a dropped-in strategy is translated into the Lab automatically. Never blocks startup on failure."""
    try:
        from cosmu.lab.inbox import scan_inbox

        scan_inbox(store, run_cohort=has_live_data(store))
    except Exception:  # noqa: BLE001 — inbox import is best-effort; a bad file must not break boot
        pass


app = FastAPI(title="Cosmu Engine", version="0.1.0", lifespan=lifespan)

# Private single-user app behind API_SECRET_KEY — allow all origins so Vercel preview
# deploys (which get new URLs) work without updating CORS_EXTRA_ORIGINS every time.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# NOTE: no API auth — this is a single-user INTERNAL tool. The Next.js proxy still routes browser→engine
# server-side (good for CORS + hiding the engine URL), but the engine enforces no shared secret.


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
    forward_test = sum(int(r["n"]) for r in counts if r["status"] in ("forward_test", "live"))
    live = sum(int(r["n"]) for r in counts if r["status"] == "live")
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
        forward_test=forward_test,
        live=live,
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
        store=store,  # consult long-term memory (graveyard RAG + distilled skills) when proposing
    )
    store.append_event(actor="human", kind="strategy_drafted", ref_type="strategy_spec", payload={"template": draft.base_template, "features": draft.features, "valid": draft.valid})
    return _draft_to_response(draft)


@app.post("/lab/author/run", response_model=CohortSummaryResponse)
def lab_author_run(request: AuthorRunRequest) -> CohortSummaryResponse:
    draft = draft_from_brief(request.brief, features=request.features, venues=request.venues, llm_enabled=bool(settings.openrouter_api_key))
    loop = FarmLoop(settings=settings, store=store)
    summary = loop.run_cohort(cohort_size=request.cohort_size, extra_seeds=[draft.spec])
    return _summary_to_response(summary)


def _finder_variant(r) -> FinderVariant:  # noqa: ANN001 — VariantResult
    return FinderVariant(
        config_tag=r.config_tag,
        version_id=r.version_id,
        profit_factor=round(r.profit_factor, 4),
        deflated_sharpe=round(r.deflated_sharpe, 6),
        net_profit=round(r.net_profit, 6),
        num_trades=r.metrics.num_trades,
        gate_passed=r.gate_passed,
        promoted=r.promoted,
        holdout_passed=r.holdout_passed,
    )


@app.post("/lab/inbox", response_model=InboxIdeaResponse)
def lab_inbox_queue(request: InboxIdeaRequest) -> InboxIdeaResponse:
    """Drop a natural-language strategy 'vibe' into the inbox: write it as a brief in strategies/inbox/ and record
    an audited inbox_queued event. The next boot scan / autonomy tick translates it into a typed StrategySpec and
    routes it through the DETERMINISTIC Gate. This endpoint never authors or funds — it only queues prose."""
    from cosmu.lab.inbox import list_queued, queue_idea

    try:
        idea = queue_idea(store, request.text, name=request.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    pending = sum(1 for i in list_queued(store) if i.status == "queued")
    return InboxIdeaResponse(
        ok=True,
        filename=idea.filename,
        name=idea.name,
        queued=pending,
        note="Queued. The next autonomous tick (or engine boot) translates it into a typed, gated spec — the deterministic Gate alone decides survival.",
    )


@app.get("/lab/inbox", response_model=InboxQueueResponse)
def lab_inbox_list() -> InboxQueueResponse:
    """The operator's queued strategy ideas, newest first — each `queued` until a scan imports it, then `imported`.
    Read off the audited event ledger; honest empty when nothing has been dropped yet."""
    from cosmu.lab.inbox import _INBOX_DIR, list_queued

    items = list_queued(store)
    return InboxQueueResponse(
        items=[InboxQueueItem(filename=i.filename, name=i.name, ts=i.ts, status=i.status) for i in items],
        inbox_dir=str(_INBOX_DIR),
    )


@app.post("/lab/finder", response_model=FinderResponse)
def lab_finder(request: FinderRunRequest) -> FinderResponse:
    """Run the Strategy Finder: grid-search the ORB+FVG seed's param space → screen each variant on REAL Binance
    spot bars (cached, offline-safe) → register every variant as a trial → rank by profit_factor (displayed) while
    the deterministic Gate + FDR + one-shot holdout decide promotion → persist winners to the config library."""
    if not has_live_data(store):
        raise HTTPException(status_code=400, detail="No venue with a live data path is enabled. Enable Binance (Crypto) in Settings to run the Finder.")
    from cosmu.lab.finder import StrategyFinder, seed_real
    from cosmu.evolution.seeder import seed_orb_fvg_spec

    if request.seed_real:
        report = seed_real(store, max_variants=request.max_variants or 64)
    else:
        finder = StrategyFinder(settings=settings, store=store)
        report = finder.find(seed_orb_fvg_spec(), max_variants=request.max_variants or 64, persist=True)
    return FinderResponse(
        strategy_name=report.strategy_name,
        grid_size=report.grid_size,
        screened=report.screened,
        gate_passed=report.gate_passed,
        promoted=report.promoted,
        leaderboard=[_finder_variant(r) for r in report.leaderboard],
        survivors=[_finder_variant(r) for r in report.survivors],
    )


@app.post("/lab/ml", response_model=MlResponse)
def lab_ml(request: MlRequest) -> MlResponse:
    """The ML-through-natural-language seam. A plain-language ML request → (LLM-optional, deterministic fallback)
    intent classification → runs the survival-ranking or feature-importance pass over REAL persisted outcomes →
    returns a result JUDGED by the deterministic scorer (gate verdict per item) but never alters it."""
    from cosmu.lab.ml import run_ml_request

    result = run_ml_request(store, request.request, llm_enabled=bool(settings.openrouter_api_key), limit=request.limit or 24)
    return MlResponse(
        task=result.task,
        request=result.request,
        llm=result.llm,
        trained=result.trained,
        backend=result.backend,
        n_labels=result.n_labels,
        ranking=[MlRankedItem(version_id=i.version_id, name=i.name, score=i.score, gate_passed=i.gate_passed, deflated_sharpe=i.deflated_sharpe) for i in result.ranking],
        feature_importance=[MlFeatureWeight(feature=w.feature, weight=w.weight) for w in result.feature_importance],
        notes=result.notes,
    )


@app.get("/overview", response_model=OverviewResponse)
def overview() -> OverviewResponse:
    """The aggregate read-out for the Overview surface — the Σ of all standalone forward-test tracks. A pure
    read-out: there is NO pooled wallet and no cross-track allocation (each survivor proves on its own track)."""
    snapshots = store.rows("SELECT ts, equity, pnl FROM portfolio_snapshots WHERE scope = 'aggregate' ORDER BY ts ASC LIMIT 120")
    curve = [Point(ts=row["ts"], value=float(row["equity"])) for row in snapshots]
    pnl_net = float(snapshots[-1]["pnl"]) if snapshots else 0.0
    equity = float(_portfolio().equity())
    cost_rows = store.rows("SELECT category, SUM(CAST(amount AS REAL)) AS amount FROM costs GROUP BY category")
    costs = [CostSlice(category=r["category"], amount=float(r["amount"] or 0)) for r in cost_rows]
    live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    return OverviewResponse(
        equity_curve=curve,
        pnl_net=pnl_net,
        costs=costs,
        live_enabled=bool(live_row and live_row["enabled"]),
        opex_vs_alpha=round(sum(c.amount for c in costs) / equity, 6) if equity else 0.0,
    )


@app.get("/leaderboard", response_model=LeaderboardResponse)
def leaderboard() -> LeaderboardResponse:
    # The track's forward-test clock origin = its FIRST `track_opened` event (per-version, written when the
    # deterministic gate opened the standalone track). MIN(ts) is the moment the forward test started ticking;
    # advisory maturity (forward_age_days / live_ready) is computed from it. LEFT JOIN so non-funded rows still
    # appear with a 0-day clock (not yet ready).
    rows = store.rows(
        """
        SELECT sv.id, s.name, sv.status, b.deflated_sharpe, b.oos_return, b.pbo, ev.funded_at
        FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN backtests b ON b.strategy_version_id = sv.id
        LEFT JOIN (
            SELECT ref_id, MIN(ts) AS funded_at FROM events WHERE kind = 'track_opened' GROUP BY ref_id
        ) ev ON ev.ref_id = sv.id
        ORDER BY CAST(COALESCE(b.deflated_sharpe, 0) AS REAL) DESC
        LIMIT 20
        """
    )
    if not rows:
        return LeaderboardResponse(rows=[])
    out: list[LeaderboardRow] = []
    for row in rows:
        # net_pct is the net-of-fee return the maturity signal reads — same field surfaced on the row.
        net_pct = _metric(row["oos_return"]) * 100 - 0.18
        # ADVISORY ONLY (master/forward_maturity.py): surfaced, never a gate. The forward-test clock runs from the
        # track's first mark; live_ready recommends a matured + net-positive track. The operator decides.
        mat = forward_maturity(row["funded_at"], net_pct)
        out.append(
            LeaderboardRow(
                version_id=row["id"],
                name=row["name"],
                # Every numeric field is coerced via _metric so the API NEVER emits
                # null/NaN where the LeaderboardRow contract promises `number`.
                track_return_pct=_metric(row["oos_return"]) * 100,
                deflated_sharpe=_metric(row["deflated_sharpe"]),
                net_pct=net_pct,
                pbo=_metric(row["pbo"]),
                status=row["status"],
                lineage="seed:template -> wfo",
                forward_age_days=mat.forward_age_days,
                live_ready=mat.live_ready,
            )
        )
    return LeaderboardResponse(rows=out)


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
        notes_md="Deterministic WFO accepted this version for the standardized track. Live capital remains gated by the global toggle, sim survival, regime fit, and caps.",
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


def _autonomy_status_response() -> AutonomyStatusResponse:
    from cosmu.api.models import TickSummary as _TickSummary
    from cosmu.master.scheduler import autonomy_status

    st = autonomy_status(store)
    return AutonomyStatusResponse(
        running=st.running,
        paused=st.paused,
        live_enabled=st.live_enabled,
        cycles_run=st.cycles_run,
        last_tick_at=st.last_tick_at,
        last_action=st.last_action,
        next_action=st.next_action,
        last_summary=_TickSummary(
            authored=st.last_summary.authored,
            gated_passed=st.last_summary.gated_passed,
            funded=st.last_summary.funded,
            recommendations=st.last_summary.recommendations,
        ),
    )


@app.get("/autonomy/status", response_model=AutonomyStatusResponse)
def autonomy_status_route() -> AutonomyStatusResponse:
    """The human-overview snapshot of the autonomous master tick — running/paused, live on/off (reported, never
    armed here), cycles run, and the last tick's headline counts. Read entirely off the persisted ledger."""
    return _autonomy_status_response()


@app.post("/autonomy/pause", response_model=AutonomyPauseResponse)
def autonomy_pause() -> AutonomyPauseResponse:
    from cosmu.master.scheduler import pause

    pause(store)
    return AutonomyPauseResponse(paused=True)


@app.post("/autonomy/resume", response_model=AutonomyPauseResponse)
def autonomy_resume() -> AutonomyPauseResponse:
    from cosmu.master.scheduler import resume

    resume(store)
    return AutonomyPauseResponse(paused=False)


@app.post("/autonomy/tick", response_model=AutonomyTickResponse)
def autonomy_tick() -> AutonomyTickResponse:
    """Run ONE bounded, idempotent, audited autonomous cycle: ingest → author (LLM proposes if a key is set, else
    deterministic) → DETERMINISTIC gate + flywheel → open standalone forward-test tracks from survivors → emit recommendations.
    LIVE STAYS OFF — sim fills only; the tick never arms live. Cron-able (one tick per call, not a daemon)."""
    from cosmu.master.scheduler import run_tick

    # REAL data only: screen + fund on actual Binance spot bars. Synthetic fixtures are CI/offline only —
    # the app must never display or fund on fabricated edge.
    report = run_tick(store, n=6, seed=7, edge_market=False)
    # Persist a point-in-time reflection (the analyst-panel debate) so the agent accrues a memory of HOW IT
    # THOUGHT each cycle. Defensive: a reasoning record only — it never moves money, and never blocks the tick.
    try:
        from cosmu.mind import reflect

        reflect(store, reference_bars=_brain_reference_bars())
    except Exception:  # noqa: BLE001 — reflection is best-effort; the tick must not depend on it
        pass
    s = report.summary
    return AutonomyTickResponse(
        authored=s.authored,
        gated_passed=s.gated_passed,
        funded=s.funded,
        recommendations=s.recommendations,
    )


@app.post("/recommendations/{rec_id}/approve", response_model=RecommendationActionResponse)
def recommendation_approve(rec_id: str) -> RecommendationActionResponse:
    """Approve a recommendation: mark it approved and apply the validated action via policy + audit. Money-adjacent
    recommendations (live/funding/cap moves) are recorded as a policy that STAYS GATED — approval here never moves
    real money; that still requires the explicit 2-click live arming + a passed gate."""
    row = store.row("SELECT * FROM recommendations WHERE id = ?", (rec_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    if row["state"] != "open":
        return RecommendationActionResponse(ok=False, applied=False, reason=f"already {row['state']}")
    payload = _json(row["payload"]) or {}
    kind = row["kind"]
    money_adjacent = kind in {"live_promotion", "fund_capital", "cap_change"} or bool(payload.get("requires_money_move"))
    store.rows("UPDATE recommendations SET state = 'approved' WHERE id = ?", (rec_id,))
    # The approved action is applied as a research-routing policy (auditable); money-adjacent stays gated.
    store.insert(
        "policies",
        {
            "ts": utcnow(),
            "source": "recommendation",
            "raw_text": row["body"],
            "parsed": {"recommendation_id": rec_id, "kind": kind, "requires_money_move": money_adjacent},
            "scope": "policy",
            "applied": int(not money_adjacent),
            "applied_at": utcnow() if not money_adjacent else None,
        },
    )
    store.append_event(actor="human", kind="recommendation_approved", ref_type="recommendation", ref_id=rec_id, payload={"kind": kind, "applied": not money_adjacent})
    if money_adjacent:
        return RecommendationActionResponse(ok=True, applied=False, reason="money-adjacent — recorded but stays gated until live is armed")
    return RecommendationActionResponse(ok=True, applied=True)


@app.post("/recommendations/{rec_id}/dismiss", response_model=RecommendationActionResponse)
def recommendation_dismiss(rec_id: str) -> RecommendationActionResponse:
    row = store.row("SELECT state FROM recommendations WHERE id = ?", (rec_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    store.rows("UPDATE recommendations SET state = 'dismissed' WHERE id = ?", (rec_id,))
    store.append_event(actor="human", kind="recommendation_dismissed", ref_type="recommendation", ref_id=rec_id)
    return RecommendationActionResponse(ok=True)


@app.post("/toggle/live", response_model=ToggleResponse)
def toggle_live(request: ToggleRequest) -> ToggleResponse:
    if request.enabled and not request.confirm:
        # Hardened: enabling live requires explicit confirm. We do NOT mutate state — the UI must re-submit
        # with confirm=true. Returning requires_confirm keeps the contract honest instead of a 400 surprise.
        return ToggleResponse(
            enabled=False,
            promoted=[],
            caps={"per_strategy": float(settings.live.per_strategy_live_cap), "global": float(settings.live.global_live_cap)},
            requires_confirm=True,
            reason="enabling live requires confirm=true",
        )
    store.rows("UPDATE live_toggle SET enabled = ?, enabled_at = ?, enabled_by = ? WHERE id = 'global'", (int(request.enabled), utcnow(), "local"))
    store.append_event(actor="human", kind="live_toggle_changed", ref_type="live_toggle", ref_id="global", payload={"enabled": request.enabled})
    return ToggleResponse(
        enabled=request.enabled,
        promoted=[] if not request.enabled else ["simulation-only"],
        caps={"per_strategy": float(settings.live.per_strategy_live_cap), "global": float(settings.live.global_live_cap)},
        requires_confirm=False,
    )


def _eligible_strategies() -> list[EligibleStrategy]:
    """Strategies eligible to be armed: forward-test survivors that (a) passed the gates, (b) have >=
    FORWARD_TEST_MIN_DAYS of net-positive FORWARD evidence, AND (c) whose PROVEN regime set includes the CURRENT
    market regime. All three are HARD preconditions — a 0-day-old, underwater, or out-of-regime strategy is NOT
    eligible. Capability ≠ edge: eligibility only gates WHAT CAN be armed; a human still makes the final launch
    click, and even then an order is real only with the toggle ON + keys + caps + no kill-switch. Never promotes."""
    from cosmu.master.live_eligibility import live_eligibility_verdict

    rows = store.rows(
        """
        SELECT sv.id, s.name FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        JOIN backtests b ON b.strategy_version_id = sv.id
        WHERE b.passed_gates = 1
        ORDER BY sv.created_at DESC LIMIT 20
        """
    )
    reference = _brain_reference_bars()
    seen: set[str] = set()
    out: list[EligibleStrategy] = []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        if not live_eligibility_verdict(store, r["id"], reference).eligible:
            continue  # blocked: not forward-proven (>= FORWARD_TEST_MIN_DAYS net-positive) or out-of-regime
        out.append(EligibleStrategy(version_id=r["id"], name=r["name"]))
    return out


@app.post("/live/activate", response_model=ActivateResponse)
def live_activate(request: ActivateRequest) -> ActivateResponse:
    caps = LiveCaps(per_strategy_cap=request.per_strategy_cap, global_cap=request.global_cap, max_daily_loss=request.max_daily_loss)
    if not request.confirm:
        return ActivateResponse(armed=False, caps=caps, eligible=[], reason="activation requires confirm=true")
    store.rows(
        """
        INSERT INTO live_caps(id, scope, ref_id, max_notional, max_daily_loss) VALUES ('global', 'pool', 'global', ?, ?)
        ON CONFLICT (id) DO UPDATE SET max_notional = excluded.max_notional, max_daily_loss = excluded.max_daily_loss
        """,
        (str(request.global_cap), str(request.max_daily_loss)),
    )
    eligible = _eligible_strategies()
    store.append_event(
        actor="human",
        kind="live_armed",
        ref_type="live_caps",
        ref_id="global",
        payload={"per_strategy_cap": request.per_strategy_cap, "global_cap": request.global_cap, "max_daily_loss": request.max_daily_loss, "eligible": [e.version_id for e in eligible]},
    )
    return ActivateResponse(armed=True, caps=caps, eligible=eligible)


@app.post("/live/defund", response_model=DefundResponse)
def live_defund(request: DefundRequest) -> DefundResponse:
    pf = _portfolio()
    if request.scope == "strategy" and request.version_id:
        rows = store.rows("SELECT instrument_id FROM positions WHERE strategy_version_id = ?", (request.version_id,))
        store.rows("UPDATE positions SET qty = '0', updated_at = ? WHERE strategy_version_id = ?", (utcnow(), request.version_id))
        defunded = [request.version_id]
    else:
        rows = store.rows("SELECT DISTINCT strategy_version_id FROM positions WHERE CAST(qty AS REAL) != 0")
        store.rows("UPDATE positions SET qty = '0', updated_at = ?", (utcnow(),))
        defunded = [str(r["strategy_version_id"] or "pool") for r in rows]
    pf.mark_to_market({})
    store.append_event(actor="human", kind="live_defunded", ref_type="live_caps", ref_id="global", payload={"scope": request.scope, "defunded": defunded})
    return DefundResponse(ok=True, defunded=defunded)


@app.get("/live/positions", response_model=LivePositionsResponse)
def live_positions() -> LivePositionsResponse:
    pf = _portfolio()
    live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    armed = bool(live_row and live_row["enabled"]) and resolve_mode(settings) != "disabled"
    caps = LiveCaps(**_live_caps_row())
    daily = pf.daily_loss()
    positions = [
        LivePosition(
            instrument_id=p.instrument_id,
            symbol=p.symbol,
            qty=float(p.qty),
            avg_price=float(p.avg_price),
            unrealized_pnl=float(p.unrealized_pnl(p.avg_price)),  # mark==basis without a fresh tick; honest 0
            venue=p.venue,
        )
        for p in pf.positions()
    ]
    return LivePositionsResponse(armed=armed, mode=_live_mode(), daily_loss=float(daily.daily_loss), caps=caps, positions=positions)


# Which venues have LIVE execution credentials wired. Only Binance has an execution adapter + keys today;
# the others are legal-but-unwired ("not connected") until their adapter ships. Secrets stay server-side —
# the UI only ever sees the boolean.
def _venue_connected(venue_id: str) -> bool:
    if venue_id == "binance":
        return bool(settings.binance_api_key and settings.binance_api_secret)
    return False


def _current_jurisdiction() -> str:
    """The operator's chosen jurisdiction: the latest audited `jurisdiction_set` event, else the
    LIVE_JURISDICTION env default — validated against the curated list so it's always a known code."""
    row = store.row("SELECT payload FROM events WHERE kind = 'jurisdiction_set' ORDER BY ts DESC LIMIT 1")
    if row:
        try:
            code = json.loads(row["payload"]).get("code")
            if code in SUPPORTED_JURISDICTIONS:
                return code
        except (TypeError, ValueError, KeyError):
            pass
    env = (settings.live_jurisdiction or "FR").upper()
    return env if env in SUPPORTED_JURISDICTIONS else "FR"


@app.get("/live/jurisdictions", response_model=JurisdictionsResponse)
def live_jurisdictions() -> JurisdictionsResponse:
    """The curated pick-list of operating jurisdictions + the current one. Each option lists the venues that
    are live-legal from there, so the UI can show what picking it unlocks."""
    catalog = default_catalog()
    options = [
        JurisdictionOption(code=code, label=label, legal_venue_ids=[v.id for v in catalog.live_legal_venues(code)])
        for code, label in SUPPORTED_JURISDICTIONS.items()
    ]
    return JurisdictionsResponse(current=_current_jurisdiction(), options=options)


@app.post("/live/jurisdiction", response_model=JurisdictionsResponse)
def set_live_jurisdiction(request: SetJurisdictionRequest) -> JurisdictionsResponse:
    code = request.code.upper()
    if code not in SUPPORTED_JURISDICTIONS:
        raise HTTPException(status_code=400, detail=f"unsupported jurisdiction: {request.code}")
    store.append_event(actor="operator", kind="jurisdiction_set", ref_type="config", ref_id="jurisdiction", payload={"code": code})
    return live_jurisdictions()


@app.get("/live/venues", response_model=LiveVenuesResponse)
def live_venues() -> LiveVenuesResponse:
    """The honest LIVE venue picture: the venues legal to trade from our jurisdiction, whether each is wired
    (connected) or not, whether it's ticked into the universe, and the real capital deployed at each now."""
    catalog = default_catalog()
    country = _current_jurisdiction()
    enabled_ids = {r["id"] for r in venue_rows(store) if r["enabled"]}
    deployed: dict[str, float] = {}
    for p in _portfolio().positions():  # real capital at risk per venue: |qty| * avg_price
        deployed[p.venue] = deployed.get(p.venue, 0.0) + abs(_metric(p.qty)) * _metric(p.avg_price)
    venues = [
        LiveVenue(
            id=v.id,
            name=v.name,
            kind=v.kind,
            live_legal=True,  # this set is already filtered to legal-from-our-jurisdiction
            connected=_venue_connected(v.id),
            enabled=v.id in enabled_ids,
            deployed_usd=round(_metric(deployed.get(v.id, 0.0)), 2),
        )
        for v in catalog.live_legal_venues(country)
    ]
    caps = LiveCaps(**_live_caps_row())
    total = round(sum(v.deployed_usd for v in venues), 2)
    return LiveVenuesResponse(jurisdiction=country, global_cap=caps.global_cap, total_deployed_usd=total, venues=venues)


@app.get("/live/venue-catalog", response_model=VenueCatalogResponse)
def live_venue_catalog() -> VenueCatalogResponse:
    """Read-only catalog for the launch-live modal: every venue with its real fee schedule and a
    `configured` boolean (True = API keys are present in server env for that venue; False = greyed-out
    in the UI, cannot arm). Keys are NEVER returned — only the boolean. This includes ALL venues in the
    catalog (not just the jurisdiction-legal subset) so the modal can show grey non-configured ones."""
    catalog = default_catalog()
    fee_venues = [
        VenueFeeInfo(
            id=v.id,
            name=v.name,
            kind=v.kind,
            maker_fee_bps=float(v.maker_fee_bps),
            taker_fee_bps=float(v.taker_fee_bps),
            min_notional=float(v.min_notional),
            fee_tiers=[
                VenueFeeTierInfo(
                    min_volume_30d_usd=float(t.min_volume_30d_usd),
                    maker_fee_bps=float(t.maker_fee_bps),
                    taker_fee_bps=float(t.taker_fee_bps),
                )
                for t in v.fee_tiers
            ],
            configured=_venue_connected(v.id),
            live_enabled=v.live_enabled,
        )
        for v in catalog.venues
    ]
    instruments = [
        VenueInstrumentInfo(
            id=i.id,
            venue_id=i.venue_id,
            symbol=i.symbol,
            asset_class=i.asset_class,
            min_notional=float(i.min_notional),
        )
        for i in catalog.instruments
    ]
    return VenueCatalogResponse(venues=fee_venues, instruments=instruments)


@app.post("/live/launch", response_model=LaunchActivateResponse)
def live_launch(request: LaunchActivateRequest) -> LaunchActivateResponse:
    """Strategy launch-live flow: arm one gate-passed strategy on a chosen venue + asset with a given budget.
    This is the ONLY path that launches a single strategy live — and the ONLY path that writes status='live'
    (on a confirmed, eligible launch). Forward-test maturity is now a HARD precondition: the strategy must have
    >= FORWARD_TEST_MIN_DAYS of net-positive forward evidence AND be in a proven regime to arm. `override_forward_test`
    (default OFF) lets a human arm an UNPROVEN strategy anyway, recorded with a loud `live_override_launch` warning;
    it never waives the regime gate. The 5 execution interlocks still apply in full at execute time (toggle ON +
    keys present + gate passed + caps available + no kill-switch). `confirm` must be true (two-click safety)."""
    caps = LiveCaps(per_strategy_cap=request.per_strategy_cap, global_cap=request.global_cap, max_daily_loss=request.max_daily_loss)
    if not request.confirm:
        return LaunchActivateResponse(
            armed=False, version_id=request.version_id, venue_id=request.venue_id, symbol=request.symbol,
            budget=request.budget, caps=caps, eligible=[], reason="confirm must be true to arm",
        )
    # Validate venue is configured (keys present). A non-configured venue CANNOT arm regardless
    # of the toggle — this is the server-side key-gate that backs the UI grey-out.
    if not _venue_connected(request.venue_id):
        return LaunchActivateResponse(
            armed=False, version_id=request.version_id, venue_id=request.venue_id, symbol=request.symbol,
            budget=request.budget, caps=caps, eligible=[],
            reason=f"venue '{request.venue_id}' has no API keys configured — add them to the server env first",
        )

    # HARD live-eligibility gate: forward-test maturity (>= FORWARD_TEST_MIN_DAYS net-positive) AND regime.
    # `override_forward_test` waives ONLY the forward-test precondition (logged below), never the regime gate.
    from cosmu.master.live_eligibility import forward_clock_origin, live_eligibility_verdict

    reference = _brain_reference_bars()
    verdict = live_eligibility_verdict(store, request.version_id, reference, override=request.override_forward_test)
    ft_days = verdict.forward_age_days if forward_clock_origin(store, request.version_id) else None
    readiness = "proven" if verdict.forward_ready else "not yet proven"

    if not verdict.eligible:
        # Not forward-proven (and no override), underwater, or out-of-regime — refuse to arm. No status write.
        return LaunchActivateResponse(
            armed=False, version_id=request.version_id, venue_id=request.venue_id, symbol=request.symbol,
            budget=request.budget, caps=caps, eligible=[], forward_test_days=ft_days,
            readiness=readiness, overridden=False, reason=verdict.reason,  # type: ignore[arg-type]
        )

    # Eligible (or human-overridden): upsert caps, then mark the strategy live. This UPDATE is the ONLY place
    # status='live' is written — a strategy becomes live only on a confirmed, eligible launch click.
    store.rows(
        """
        INSERT INTO live_caps(id, scope, ref_id, max_notional, max_daily_loss) VALUES ('global', 'pool', 'global', ?, ?)
        ON CONFLICT (id) DO UPDATE SET max_notional = excluded.max_notional, max_daily_loss = excluded.max_daily_loss
        """,
        (str(request.global_cap), str(request.max_daily_loss)),
    )
    store.rows("UPDATE strategy_versions SET status = 'live' WHERE id = ?", (request.version_id,))
    if verdict.overridden:
        # The explicit, logged warning for arming an unproven strategy (owner-pending escape hatch, default OFF).
        store.append_event(
            actor="human", kind="live_override_launch", ref_type="strategy_version", ref_id=request.version_id,
            payload={
                "reason": verdict.reason, "forward_age_days": verdict.forward_age_days,
                "net_return_pct": verdict.net_return_pct, "min_days": verdict.min_days,
                "venue_id": request.venue_id, "symbol": request.symbol,
            },
        )
    eligible = _eligible_strategies()
    store.append_event(
        actor="human", kind="live_launched", ref_type="strategy_version", ref_id=request.version_id,
        payload={
            "venue_id": request.venue_id, "symbol": request.symbol, "budget": request.budget,
            "per_strategy_cap": request.per_strategy_cap, "global_cap": request.global_cap,
            "max_daily_loss": request.max_daily_loss, "forward_test_days": ft_days,
            "readiness": readiness, "overridden": verdict.overridden,
        },
    )
    return LaunchActivateResponse(
        armed=True, version_id=request.version_id, venue_id=request.venue_id, symbol=request.symbol,
        budget=request.budget, caps=caps, eligible=eligible, forward_test_days=ft_days,
        readiness=readiness, overridden=verdict.overridden,  # type: ignore[arg-type]
    )


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


def _brain_reference_bars():
    """A reference close series for the CURRENT-regime read — REAL Binance BTCUSDT only. If the cache/network is
    unavailable we return no bars (current_regime then reports a neutral 'chop' default) rather than reading a
    synthetic fixture: the displayed regime must never be derived from fabricated data."""
    from cosmu.data.market import BinanceSpotOHLCVProvider

    try:
        bars = BinanceSpotOHLCVProvider().fetch_bars("BTCUSDT", "1d", limit=240)
        if len(bars) >= 60:
            return bars
    except Exception:  # noqa: BLE001 — offline/no-network: report neutral, never fabricate a regime
        pass
    return []


@app.get("/research/brain", response_model=BrainResponse)
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


@app.get("/mind", response_model=MindResponse)
def mind() -> MindResponse:
    """The Mind — the agent's standardized self-knowledge in one read: what it KNOWS (point-in-time data sources
    + freshness), how it THINKS (the analyst panel + the debate's consensus), and what it has LEARNED (memory,
    the ML survival model, regime coverage, gate efficiency). The panel reads REAL ingested signals only — a
    perspective with no data abstains, never fabricates. RAILGUARD: this reasons; it never funds or fires an
    order — the deterministic gate alone disposes."""
    from cosmu.mind import build_mind, judge_from_settings

    # LLM-as-judge is OPT-IN (MIND_JUDGE_ENABLED): off → the committee is fully deterministic (default, $0,
    # fast). On + a key → pillars WITH data are rubric-scored by the model; the consensus stays deterministic
    # math and the gate alone disposes. The seam degrades gracefully, so enabling it can never stall the read.
    judge = judge_from_settings(settings) if settings.mind_judge_enabled else None
    return MindResponse(**build_mind(store, reference_bars=_brain_reference_bars(), judge=judge))


@app.get("/mind/source-trust", response_model=SourceTrustResponse)
def mind_source_trust() -> SourceTrustResponse:
    """Source-trust scoreboard — for every registered data source, a plain-language trust score.

    Trust = freshness × realized gate contribution (how many gate-passed backtests used this source).
    Honest: a source with no data ingested shows trust_score=0, status="no data" — never fabricates.
    Read-only; no LLM on this path; the Gate/money path is deterministic and separate."""
    from cosmu.mind.source_trust import build_source_trust
    from cosmu.knowledge.store import utcnow

    with store.reading():
        rows = build_source_trust(store)
    return SourceTrustResponse(
        as_of=utcnow(),
        rows=[
            SourceTrustRow(
                source=r.source,
                features=r.features,
                last_at=r.last_at,
                freshness_label=r.freshness_label,
                status=r.status,
                gate_pass_count=r.gate_pass_count,
                trust_score=r.trust_score,
                summary=r.summary,
                tier=r.tier,
                hours_since=r.hours_since,
            )
            for r in rows
        ],
    )


def _present_provider_keys() -> set[str]:
    """Which provider env keys are set on the engine (Railway). Drives the cockpit's grey/disabled state:
    a key-gated source with no key here renders disabled. Read straight off the typed settings."""
    present: set[str] = set()
    if settings.xai_api_key:
        present.add("XAI_API_KEY")
    if settings.lunarcrush_api_key:
        present.add("LUNARCRUSH_API_KEY")
    if settings.fred_api_key:
        present.add("FRED_API_KEY")
    if settings.polymarket_token:
        present.add("POLYMARKET_TOKEN")
    return present


@app.get("/scores", response_model=ScoresResponse)
def scores() -> ScoresResponse:
    """The SCORES COCKPIT — per-source + composite INDEX scores grouped by category (crypto · social ·
    macro · OSINT · metals/forex), each with freshness and a plain-language "what this means" review.

    Composite index = freshness × realized gate contribution, averaged over the sources that actually have
    data. HONEST: a category/source with no ingested data reports connected=False and index=null — never a
    fabricated score. A key-gated source whose key is not set on the engine shows disabled=True so the UI
    greys it out. Reviews are deterministic plain-language reads; no LLM on the gate/scoring/money path."""
    from cosmu.mind.scores import build_scores

    snap = build_scores(store, present_keys=_present_provider_keys())
    return ScoresResponse(
        as_of=snap.as_of,
        composite_index=snap.composite_index,
        composite_status=snap.composite_status,
        composite_review=snap.composite_review,
        categories=[
            ScoreCategory(
                key=c.key,
                label=c.label,
                index_score=c.index_score,
                status=c.status,
                freshness_label=c.freshness_label,
                connected=c.connected,
                live_sources=c.live_sources,
                total_sources=c.total_sources,
                review=c.review,
                sources=[
                    ScoreSourceRow(
                        source=s.source,
                        category=s.category,
                        features=s.features,
                        last_at=s.last_at,
                        freshness_label=s.freshness_label,
                        status=s.status,
                        trust_score=s.trust_score,
                        tier=s.tier,
                        hours_since=s.hours_since,
                        connected=s.connected,
                        key_required=s.key_required,
                        key_name=s.key_name,
                        key_present=s.key_present,
                        disabled=s.disabled,
                        review=s.review,
                    )
                    for s in c.sources
                ],
            )
            for c in snap.categories
        ],
    )


def _settings_key_rows() -> list[SettingsKeyRow]:
    """Build the read-only key inventory from typed settings. SECURITY: only the boolean `configured` is
    derived — no value is ever read into the response. The canonical table lives in docs/KEYS.md."""
    binance_live = bool(settings.binance_api_key and settings.binance_api_secret)
    binance_testnet = bool(settings.binance_testnet_api_key and settings.binance_testnet_api_secret)
    return [
        SettingsKeyRow(
            key="API secret",
            env_var="API_SECRET_KEY",
            configured=bool(settings.api_secret_key),
            unlocks="Locks the control-plane API — the web app sends it; nobody else can call the engine.",
            requirement="required",
            cost="free",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="xAI (Grok)",
            env_var="XAI_API_KEY",
            configured=bool(settings.xai_api_key),
            unlocks="LLM strategy authoring (preferred). Research still runs offline without it.",
            requirement="optional",
            cost="paid",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="OpenRouter",
            env_var="OPENROUTER_API_KEY",
            configured=bool(settings.openrouter_api_key),
            unlocks="LLM authoring fallback when xAI is not set. Optional.",
            requirement="optional",
            cost="paid",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="LunarCrush",
            env_var="LUNARCRUSH_API_KEY",
            configured=bool(settings.lunarcrush_api_key),
            unlocks="Social-sentiment scores + a REAL (non-synthetic) edge-gate verdict.",
            requirement="optional",
            cost="paid",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="FRED",
            env_var="FRED_API_KEY",
            configured=bool(settings.fred_api_key),
            unlocks="Macro-regime cross-asset source (free key).",
            requirement="optional",
            cost="free",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="Polymarket",
            env_var="POLYMARKET_TOKEN",
            configured=bool(settings.polymarket_token),
            unlocks="Prediction-market risk-on cross-asset source (a market token id, not a secret).",
            requirement="optional",
            cost="free",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="Binance (live)",
            env_var="BINANCE_API_KEY / BINANCE_API_SECRET",
            configured=binance_live,
            unlocks="Real-money execution on Binance spot. Only needed once you arm live trading.",
            requirement="live-only",
            cost="free",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="Binance (testnet)",
            env_var="BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET",
            configured=binance_testnet,
            unlocks="Paper execution against Binance testnet (testnet.binance.vision).",
            requirement="optional",
            cost="free",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="Slack alerts",
            env_var="SLACK_WEBHOOK_URL",
            configured=bool(os.environ.get("SLACK_WEBHOOK_URL")),
            unlocks="Ops alerts to a Slack channel.",
            requirement="optional",
            cost="free",
            where="Engine env (Railway)",
        ),
    ]


@app.get("/settings/keys", response_model=SettingsKeysResponse)
def settings_keys() -> SettingsKeysResponse:
    """Read-only key inventory for the Settings → Keys page: which provider keys are configured on the
    engine and what each unlocks. SECURITY: values are NEVER returned — only a boolean `configured` per
    key. Safe to render in the browser. The canonical key table lives in docs/KEYS.md."""
    return SettingsKeysResponse(rows=_settings_key_rows())


@app.get("/mind/news-intel", response_model=NewsIntelResponse)
def mind_news_intel(symbol: str = "BTCUSDT", limit: int = 20) -> NewsIntelResponse:
    """Recent scored news events for a symbol — the typed, dated, point-in-time news/intel panel.

    Each event has: ts, available_at, value (signed magnitude in [-1, 1]), event_type (bullish/bearish/neutral).
    Honest empty state when no news has been ingested yet. No LLM on this path — events were scored at ingest."""
    from cosmu.mind.news_intel import recent_news_events

    with store.reading():
        raw = recent_news_events(store, symbol=symbol, limit=min(limit, 100))
    return NewsIntelResponse(
        symbol=symbol,
        events=[
            NewsEventRow(
                ts=r.get("ts"),
                available_at=r.get("available_at"),
                value=float(r["value"]),
                event_type=r["event_type"],
                symbol=symbol,
            )
            for r in raw
        ],
    )


@app.get("/research/drift", response_model=DriftResponse)
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


@app.get("/skills", response_model=SkillsResponse)
def skills() -> SkillsResponse:
    """The Curator's distilled SKILL recipes — reusable, parameterized templates the brain reuses as priors.
    Best-graded first; pruned skills are excluded. `grade` is the downstream OOS pass-rate of derived Versions
    (the deterministic Gate's verdicts) — the Curator curates what the Gate judged, it never judges."""
    from cosmu.lab.curator import live_skills

    return SkillsResponse(
        skills=[
            Skill(
                name=s.name,
                grade=round(s.grade, 6),
                success_count=s.success_count,
                lineage=s.lineage,
                recipe_summary=s.recipe_summary,
                created_at=s.created_at,
            )
            for s in live_skills(store)
        ]
    )


@app.get("/memory/insights", response_model=MemoryInsightsResponse)
def memory_insights_route() -> MemoryInsightsResponse:
    """What the brain has LEARNED from long-term memory (graveyard/research RAG): dead-end structures to avoid +
    winning patterns to reuse. Read straight off the persisted notes — no recompute, no LLM."""
    from cosmu.knowledge.memory import memory_insights

    return MemoryInsightsResponse(
        insights=[MemoryInsight(kind=i["kind"], text=i["text"], ref=i["ref"]) for i in memory_insights(store)]
    )


@app.get("/costs", response_model=CostsResponse)
def costs() -> CostsResponse:
    """Cost transparency — opex vs alpha. Total spend, spend by category, the opex/equity ratio,
    per-strategy opex vs net edge, the static infra cost table (MASTER_PLAN §9), and a summary of
    recorded LLM calls. Seeds the static infra lines on first call (idempotent per calendar month).
    Reads only persisted rows — no external billing API calls."""
    # Seed static infra lines (idempotent: once per calendar month). Best-effort.
    try:
        from cosmu.costs.writer import seed_infra_costs
        seed_infra_costs(store)
    except Exception:  # noqa: BLE001 — seed is best-effort; never crash the endpoint
        pass

    cost_rows = store.rows("SELECT category, SUM(CAST(amount AS REAL)) AS amount FROM costs GROUP BY category")
    by_category = [CostByCategory(category=r["category"], amount=float(r["amount"] or 0)) for r in cost_rows]
    total = round(sum(c.amount for c in by_category), 6)
    try:
        equity = float(_portfolio().equity())
    except Exception:  # noqa: BLE001 — equity is best-effort; the cost page must render without it
        equity = 0.0
    per_rows = store.rows(
        """
        SELECT sv.id AS version_id, s.name AS name,
               SUM(CAST(c.amount AS REAL)) AS opex,
               COALESCE(CAST(tr.equity AS REAL) - CAST(tr.starting_capital AS REAL), 0) AS net
        FROM costs c
        JOIN strategy_versions sv ON sv.id = c.strategy_version_id
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN tracks tr ON tr.strategy_version_id = sv.id
        GROUP BY sv.id, s.name, tr.equity, tr.starting_capital
        """
    )
    per_strategy = [
        CostPerStrategy(version_id=r["version_id"], name=r["name"], opex=round(float(r["opex"] or 0), 6), net=round(float(r["net"] or 0), 6))
        for r in per_rows
    ]

    # Build the static infra table from the seeded costs rows (meta field identifies infra seeds).
    import json as _json_mod
    # NOTE: the LIKE pattern MUST be a bound parameter — an inline '%' collides with psycopg2's
    # %-paramstyle (store passes a params tuple), raising IndexError on Postgres (SQLite tolerates it).
    infra_rows = store.rows(
        "SELECT vendor, category, CAST(amount AS REAL) AS amount, meta FROM costs WHERE meta LIKE ?",
        ('%"seed": "infra"%',),
    )
    seen_vendors: set[str] = set()
    infra_lines: list[InfraLine] = []
    for r in infra_rows:
        vendor = r["vendor"]
        if vendor in seen_vendors:
            continue  # keep only the first (latest) seed row per vendor
        seen_vendors.add(vendor)
        try:
            meta = _json_mod.loads(r["meta"]) if isinstance(r["meta"], str) else (r["meta"] or {})
        except (ValueError, TypeError):
            meta = {}
        infra_lines.append(InfraLine(
            vendor=vendor,
            category=r["category"],
            amount=float(r["amount"] or 0),
            amount_min=float(meta.get("amount_min", r["amount"] or 0)),
            amount_max=float(meta.get("amount_max", r["amount"] or 0)),
            note=str(meta.get("note", "")),
        ))

    # LLM call summary from llm_calls table.
    llm_count_row = store.row("SELECT COUNT(*) AS n, COALESCE(SUM(CAST(cost AS REAL)), 0) AS total FROM llm_calls")
    llm_count = int(llm_count_row["n"] or 0) if llm_count_row else 0
    llm_total = float(llm_count_row["total"] or 0.0) if llm_count_row else 0.0
    task_rows = store.rows("SELECT task, COUNT(*) AS n FROM llm_calls GROUP BY task")
    by_task = {r["task"]: int(r["n"]) for r in task_rows}

    return CostsResponse(
        total_usd=total,
        by_category=by_category,
        opex_vs_alpha=round(total / equity, 6) if equity else 0.0,
        per_strategy=per_strategy,
        infra_lines=infra_lines,
        llm_calls=LlmCallSummary(call_count=llm_count, total_cost=llm_total, by_task=by_task),
    )


@app.get("/events", response_model=EventsResponse)
def events(limit: int = 50) -> EventsResponse:
    rows = store.rows("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
    return EventsResponse(events=[Event(id=row["id"], ts=row["ts"], actor=row["actor"], kind=row["kind"], ref_type=row["ref_type"], ref_id=row["ref_id"], payload=_json(row["payload"])) for row in rows])


@app.get("/intelligence", response_model=IntelligenceResponse)
def intelligence() -> IntelligenceResponse:
    from cosmu.api.intelligence import compute_intelligence

    return IntelligenceResponse(**compute_intelligence(store))


def ensure_recommendations() -> None:
    if store.row("SELECT id FROM recommendations LIMIT 1"):
        return
    store.insert(
        "recommendations",
        {
            "ts": utcnow(),
            "kind": "paper_promotion_watch",
            "body": "One seeded strategy cleared the deterministic WFO gates. Keep it in realistic sim until it survives 4+ weeks with positive net edge before live promotion.",
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
    import os

    # Bind for BOTH local dev and production (Railway/any PaaS injects $PORT). Default 0.0.0.0 so the container
    # is reachable; reload only in local/dev. Production (APP_ENV=production) → no reload, real $PORT.
    _port = int(os.environ.get("PORT", "8000"))
    _host = os.environ.get("HOST", "0.0.0.0")
    _reload = os.environ.get("APP_ENV", "dev").strip().lower() in ("dev", "local")
    import uvicorn

    uvicorn.run("cosmu.api.app:app", host=_host, port=_port, reload=_reload)
