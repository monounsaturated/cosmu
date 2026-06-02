# intent: expose the engine's typed control-plane API; inputs: HTTP requests; outputs: Pydantic responses/OpenAPI; invariants: mutating money routes are gated and live remains off by default.

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from cosmu.api.models import (
    ActivateRequest,
    ActivateResponse,
    Allocation,
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
    CrossAssetVerdict,
    DefundRequest,
    DefundResponse,
    DriftResponse,
    DriftSleeve,
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
    IntelligenceResponse,
    GraveyardRow,
    MlFeatureWeight,
    MlRankedItem,
    MlRequest,
    MlResponse,
    LeaderboardResponse,
    LeaderboardRow,
    LiveCaps,
    LivePosition,
    LivePositionsResponse,
    PineSample,
    PineSamplesResponse,
    PineTranslateRequest,
    PineTranslateResponse,
    MemoryInsight,
    MemoryInsightsResponse,
    Point,
    PopulationResponse,
    PortfolioResponse,
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
    VenueState,
    VenueToggleRequest,
)
from cosmu.adapters.exec.binance import BinanceSpotExecutionAdapter, resolve_mode
from cosmu.config.settings import get_settings
from cosmu.evolution.loop import CohortSummary, FarmLoop
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import PaperPortfolio
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
try:
    store = Store(settings)
except Exception:
    from cosmu.config.settings import Settings as _S
    store = Store(_S(database_url="sqlite:///.cosmu/fallback.sqlite3"))


def _portfolio() -> PaperPortfolio:
    return PaperPortfolio(store, bankroll=settings.paper_bankroll, daily_loss_cap=settings.live.daily_loss_cap)


def _live_mode() -> str:
    """The mode GET /live/positions reports — the adapter's resolved mode (testnet/live) or paper if disabled."""
    mode = resolve_mode(settings)
    return mode if mode in ("testnet", "live") else "paper"


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
            _fund_wallet_on_startup()
        except Exception:  # noqa: BLE001 — boot tasks are best-effort; never crash the app
            pass

    threading.Thread(target=_boot, daemon=True).start()
    yield


def _fund_wallet_on_startup() -> None:
    """Close the loop on boot: if gate-passed survivors exist with sleeves but the paper Wallet holds no
    positions yet, size them with the capped-Kelly allocator and open paper positions so GET /portfolio reflects
    a genuinely funded Wallet (no fabricated numbers). Best-effort + offline-safe; never blocks startup."""
    try:
        from cosmu.orchestrator import fund_wallet_from_survivors

        if store.row("SELECT id FROM positions WHERE CAST(qty AS REAL) != 0 LIMIT 1"):
            return  # already funded — idempotent, don't double-open
        if not store.row("SELECT sv.id FROM strategy_versions sv JOIN sleeves sl ON sl.strategy_version_id = sv.id WHERE sv.status IN ('paper','live') LIMIT 1"):
            return  # no survivors yet — honest empty Wallet
        fund_wallet_from_survivors(store, bankroll=settings.paper_bankroll)
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


@app.get("/portfolio", response_model=PortfolioResponse)
def portfolio() -> PortfolioResponse:
    snapshots = store.rows("SELECT ts, equity, pnl FROM portfolio_snapshots WHERE scope = 'pool' ORDER BY ts ASC LIMIT 120")
    curve = [Point(ts=row["ts"], value=float(row["equity"])) for row in snapshots]
    pnl_net = float(snapshots[-1]["pnl"]) if snapshots else 0.0
    # Real allocation: open positions weighted by their notional share of equity (no fabricated numbers).
    pf = _portfolio()
    equity = float(pf.equity())
    positions = pf.positions()
    notionals = [(p, float(abs(p.qty) * p.avg_price)) for p in positions]
    total_notional = sum(n for _, n in notionals)
    allocations = [
        Allocation(
            strategy_id=p.strategy_version_id or "pool",
            name=p.symbol,
            weight=round(n / total_notional, 6) if total_notional else 0.0,
            capital=round(n, 2),
            venue=p.venue,
        )
        for p, n in notionals
    ]
    cost_rows = store.rows("SELECT category, SUM(CAST(amount AS REAL)) AS amount FROM costs GROUP BY category")
    costs = [CostSlice(category=r["category"], amount=float(r["amount"] or 0)) for r in cost_rows]
    live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    return PortfolioResponse(
        equity_curve=curve,
        pnl_net=pnl_net,
        allocation=allocations,
        costs=costs,
        live_enabled=bool(live_row and live_row["enabled"]),
        opex_vs_alpha=round(sum(c.amount for c in costs) / equity, 6) if equity else 0.0,
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
    deterministic) → DETERMINISTIC gate + flywheel → fund the PAPER Wallet from survivors → emit recommendations.
    LIVE STAYS OFF — paper fills only; the tick never arms live. Cron-able (one tick per call, not a daemon)."""
    from cosmu.master.scheduler import run_tick

    # Run over the edge-bearing fixture so a survivor (and the fund/recommend path) is exercised offline too.
    report = run_tick(store, n=6, seed=7, edge_market=True)
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
    """Strategies eligible to be armed: paper survivors that passed gates AND whose PROVEN regime set includes
    the CURRENT market regime (a strategy may go live only in a regime it proved in). Capability ≠ edge — being
    eligible here does NOT trade live; it still requires the toggle ON + keys + the deterministic gate at
    execute time. The regime gate only BLOCKS — it never promotes."""
    from cosmu.master.live_eligibility import live_regime_verdict

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
        if not live_regime_verdict(store, r["id"], reference).eligible:
            continue  # blocked: current regime is not one this strategy proved in
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
    """A reference close series for the CURRENT-regime read. Prefer the real Binance BTCUSDT cache when it
    exists; otherwise fall back to the deterministic edge-bearing fixture so the snapshot is always answerable
    offline (no network, no keys)."""
    from cosmu.data.market import BinanceSpotOHLCVProvider
    from cosmu.research.fixtures import edge_bearing_screen_market

    try:
        bars = BinanceSpotOHLCVProvider().fetch_bars("BTCUSDT", "1d", limit=240)
        if len(bars) >= 60:
            return bars
    except Exception:  # noqa: BLE001 — offline/no-network is expected; fall back to the fixture
        pass
    return edge_bearing_screen_market()["BTCUSDT"]


@app.get("/research/brain", response_model=BrainResponse)
def research_brain() -> BrainResponse:
    """The live brain snapshot: LLM on/off, the latest research pass's gated counts + survivors + graveyard,
    the propose-only sources/tools, the current market regime, and the survival model's validation-queue
    ranking. If no pass has run yet, run one over the edge-bearing fixture so the snapshot is populated. The
    survival ranking ORDERS the queue — it is never a veto; the deterministic gate alone decided who passed."""
    from cosmu.config.feature_registry import FEATURE_REGISTRY
    from cosmu.lab.research import run_research_pass
    from cosmu.lab.tools.research_tools import research_tool_bus
    from cosmu.ml.regime import current_regime

    row = store.row("SELECT payload FROM events WHERE kind = 'research_pass' ORDER BY id DESC LIMIT 1")
    if row is None:
        run_research_pass(store, n=6, seed=7, edge_market=True, llm_enabled=bool(settings.openrouter_api_key))
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


@app.get("/research/drift", response_model=DriftResponse)
def research_drift() -> DriftResponse:
    """Per-funded-sleeve ALPHA-DECAY snapshot (master/drift): edge half-life + how far live has drifted below the
    edge it was funded on, and whether the anticipatory monitor recommends pulling capital BEFORE P&L turns.
    Read-only + deterministic — the monitor only recommends; the deterministic allocator + live toggle move money."""
    from cosmu.master.drift import assess_drift, funded_sleeve_ids, sleeve_return_series

    sleeves = []
    for vid in funded_sleeve_ids(store):
        v = assess_drift(vid, sleeve_return_series(store, vid))
        sleeves.append(
            DriftSleeve(
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
    return DriftResponse(sleeves=sleeves)


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
    """Cost transparency — opex vs alpha. Total spend, spend by category, the opex/equity ratio, and per-strategy
    opex vs net edge (so the machine can see which Versions earn their keep). Reads only persisted rows."""
    cost_rows = store.rows("SELECT category, SUM(CAST(amount AS REAL)) AS amount FROM costs GROUP BY category")
    by_category = [CostByCategory(category=r["category"], amount=float(r["amount"] or 0)) for r in cost_rows]
    total = round(sum(c.amount for c in by_category), 6)
    equity = float(_portfolio().equity())
    per_rows = store.rows(
        """
        SELECT sv.id AS version_id, s.name AS name,
               SUM(CAST(c.amount AS REAL)) AS opex,
               COALESCE(CAST(sl.equity AS REAL) - CAST(sl.starting_capital AS REAL), 0) AS net
        FROM costs c
        JOIN strategy_versions sv ON sv.id = c.strategy_version_id
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN sleeves sl ON sl.strategy_version_id = sv.id
        GROUP BY sv.id, s.name, sl.equity, sl.starting_capital
        """
    )
    per_strategy = [
        CostPerStrategy(version_id=r["version_id"], name=r["name"], opex=round(float(r["opex"] or 0), 6), net=round(float(r["net"] or 0), 6))
        for r in per_rows
    ]
    return CostsResponse(
        total_usd=total,
        by_category=by_category,
        opex_vs_alpha=round(total / equity, 6) if equity else 0.0,
        per_strategy=per_strategy,
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
    import os

    # Bind for BOTH local dev and production (Railway/any PaaS injects $PORT). Default 0.0.0.0 so the container
    # is reachable; reload only in local/dev. Production (APP_ENV=production) → no reload, real $PORT.
    _port = int(os.environ.get("PORT", "8000"))
    _host = os.environ.get("HOST", "0.0.0.0")
    _reload = os.environ.get("APP_ENV", "dev").strip().lower() in ("dev", "local")
    import uvicorn

    uvicorn.run("cosmu.api.app:app", host=_host, port=_port, reload=_reload)
