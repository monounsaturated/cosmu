# intent: the Lab control-plane — author/queue/finder/ML; inputs: briefs + run requests; outputs: typed drafts + cohort/finder summaries; invariants: LLM proposes, the deterministic Gate disposes; never funds.

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cosmu.api._shared import _summary_to_response, settings, store
from cosmu.api.models import (
    AuthorRequest,
    AuthorResponse,
    AuthorRunRequest,
    CohortSummaryResponse,
    FinderResponse,
    FinderRunRequest,
    FinderVariant,
    InboxIdeaRequest,
    InboxIdeaResponse,
    InboxQueueItem,
    InboxQueueResponse,
    MlFeatureWeight,
    MlRankedItem,
    MlRequest,
    MlResponse,
)
from cosmu.evolution.loop import FarmLoop
from cosmu.lab.author import AuthorDraft, draft_from_brief
from cosmu.spine.universe import has_live_data

router = APIRouter()


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


@router.post("/lab/author", response_model=AuthorResponse)
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


@router.post("/lab/author/run", response_model=CohortSummaryResponse)
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


@router.post("/lab/inbox", response_model=InboxIdeaResponse)
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


@router.get("/lab/inbox", response_model=InboxQueueResponse)
def lab_inbox_list() -> InboxQueueResponse:
    """The operator's queued strategy ideas, newest first — each `queued` until a scan imports it, then `imported`.
    Read off the audited event ledger; honest empty when nothing has been dropped yet."""
    from cosmu.lab.inbox import _INBOX_DIR, list_queued

    items = list_queued(store)
    return InboxQueueResponse(
        items=[InboxQueueItem(filename=i.filename, name=i.name, ts=i.ts, status=i.status) for i in items],
        inbox_dir=str(_INBOX_DIR),
    )


@router.post("/lab/finder", response_model=FinderResponse)
def lab_finder(request: FinderRunRequest) -> FinderResponse:
    """Run the Strategy Finder: grid-search the ORB+FVG seed's param space → screen each variant on REAL Binance
    spot bars (cached, offline-safe) → register every variant as a trial → rank by profit_factor (displayed) while
    the deterministic Gate + FDR + one-shot holdout decide promotion → persist winners to the config library."""
    if not has_live_data(store):
        raise HTTPException(status_code=400, detail="No venue with a live data path is enabled. Enable Binance (Crypto) in Settings to run the Finder.")
    from cosmu.evolution.seeder import seed_orb_fvg_spec
    from cosmu.lab.finder import StrategyFinder, seed_real

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


@router.post("/lab/ml", response_model=MlResponse)
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
