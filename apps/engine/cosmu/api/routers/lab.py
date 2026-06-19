# intent: the Lab control-plane — author/queue/finder/ML; inputs: briefs + run requests; outputs: typed drafts + cohort/finder summaries; invariants: LLM proposes, the deterministic Gate disposes; never funds.

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cosmu.api._shared import _metric, _summary_to_response, annualized_return, oos_window_days, settings, store
from cosmu.knowledge.store import backtest_symbols_has_oos_window
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
    LabSymbolRow,
    LabSymbolsResponse,
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


# The per-cell SELECT — one row per backtest_symbols, carrying the algo id (sv.strategy_id) the comparison table
# groups on AND the parent backtest's pooled OOS return (b.oos_return) as the ADVISORY pooled number. Shared by
# /lab/symbols and the strategy-triplet routes (via _cell_select) so every granular cell is built the SAME way.
# `bs.oos_window_days` is the CELL's OWN validation window (the annualizer denominator) — selected only when the
# live schema carries the column (see _cell_select); pre-migration prod falls back to the parent backtest window.
_CELL_SELECT_BASE = (
    "SELECT bs.strategy_version_id, sv.strategy_id, s.name AS strategy_name, sv.kind, sv.status, "
    "bs.symbol, bs.venue_id, bs.return_pct, bs.sharpe, bs.max_drawdown, bs.trades, bs.verdict, "
    "{cell_window}b.oos_return AS pooled_return, b.oos_start, b.oos_end, bs.created_at "
    "FROM backtest_symbols bs "
    "JOIN strategy_versions sv ON sv.id = bs.strategy_version_id "
    "JOIN strategies s ON s.id = sv.strategy_id "
    "LEFT JOIN backtests b ON b.id = bs.backtest_id"
)


def _cell_select() -> str:
    """The per-cell SELECT, schema-adaptive: includes `bs.oos_window_days AS cell_window_days` (each cell's OWN
    validation window) ONLY when the live `backtest_symbols` table carries the column. On a pre-migration prod
    table the column is OMITTED entirely (SELECTing it would raise UndefinedColumn) and `_cell_row` falls back to
    the parent backtest's shared window. The probe is memoized per DSN (see knowledge/store.py)."""
    cell_window = "bs.oos_window_days AS cell_window_days, " if backtest_symbols_has_oos_window(store) else ""
    return _CELL_SELECT_BASE.format(cell_window=cell_window)


def _cell_row(r: dict) -> LabSymbolRow:
    """Build one granular triplet cell from a `_cell_select()` row. return_pct is the standalone truth on THIS
    (symbol, venue); pooled_return_pct rides along as advisory only (NULL when the parent backtest is missing)."""
    pooled = r.get("pooled_return")
    # Annualize this cell's standalone return over ITS OWN validation window (cell_window_days, persisted at screen
    # time) so a recently-listed coin's CAGR is computed over ITS short window — NOT the parent backtest's shared
    # (longest-cell) window. Fall back to the parent backtest's monthly bounds only for legacy/pre-migration cells
    # whose own window is NULL (residual cross-window non-comparability fix; the per-cell return_pct is unchanged).
    cell_window = r.get("cell_window_days")
    window_days = float(cell_window) if cell_window is not None else oos_window_days(r.get("oos_start"), r.get("oos_end"))
    ann = annualized_return(r["return_pct"], window_days)
    return LabSymbolRow(
        strategy_version_id=r["strategy_version_id"],
        strategy_name=r["strategy_name"],
        strategy_id=r["strategy_id"],
        kind=r.get("kind") or "quant",
        status=r.get("status") or "",
        symbol=r["symbol"],
        venue_id=r.get("venue_id"),
        return_pct=_metric(r["return_pct"]),
        return_pct_annualized=ann,
        oos_window_days=window_days,
        sharpe=_metric(r["sharpe"]),
        max_drawdown=_metric(r["max_drawdown"]),
        trades=int(_metric(r["trades"])),
        verdict=r.get("verdict"),
        pooled_return_pct=_metric(pooled) if pooled is not None else None,
        created_at=r["created_at"],
    )


def _dedup_cells(rows: list[dict]) -> list[dict]:
    """Keep ONE cell per (version, symbol, venue) — the triplet IS the unit. A re-run fans out a fresh backtest
    for the same triplet; rows arrive created_at DESC so the FIRST seen is the latest. Crucially the key carries
    venue_id: the SAME edge on the SAME symbol at two venues is two DISTINCT cells (the fee axis differs) and must
    NEVER be collapsed into one — that was the bug that hid a venue's P&L behind its sibling's."""
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict] = []
    for r in rows:
        key = (r["strategy_version_id"], r["symbol"], r.get("venue_id") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


# Authored-but-uncomputed versions: a Version that has NO backtest_symbols cell yet (today the screener INNER-JOINs
# backtest_symbols, so 418/426 versions are invisible). One synthetic "New" row per such version so the operator
# sees the whole authored population — symbol/venue empty (there is no cell), metrics zeroed (nothing computed), the
# version's own status (which normalizes to the "New" lane via the web LifeBadge). NULL spec-only, never fabricated.
_CELL_LESS_SELECT = (
    "SELECT sv.id AS strategy_version_id, sv.strategy_id, s.name AS strategy_name, sv.kind, sv.status, "
    "sv.created_at "
    "FROM strategy_versions sv "
    "JOIN strategies s ON s.id = sv.strategy_id "
    "WHERE NOT EXISTS (SELECT 1 FROM backtest_symbols bs WHERE bs.strategy_version_id = sv.id)"
)


def _new_version_row(r: dict) -> LabSymbolRow:
    """A cell-less (authored, not-yet-computed) Version as a synthetic 'New' screener row. No symbol/venue (no cell
    exists), metrics zeroed (nothing computed — never a fabricated number), the version's real status drives the
    lifecycle badge. verdict None so the front renders nothing in that slot."""
    return LabSymbolRow(
        strategy_version_id=r["strategy_version_id"],
        strategy_name=r["strategy_name"],
        strategy_id=r["strategy_id"],
        kind=r.get("kind") or "quant",
        status=r.get("status") or "lab",
        symbol="",
        venue_id=None,
        return_pct=0.0,
        sharpe=0.0,
        max_drawdown=0.0,
        trades=0,
        verdict=None,
        pooled_return_pct=None,
        created_at=r["created_at"],
    )


@router.get("/lab/symbols", response_model=LabSymbolsResponse)
def lab_symbols(symbol: str | None = None, venue: str | None = None,
                verdict: str | None = None, version_id: str | None = None,
                limit: int = 500) -> LabSymbolsResponse:
    """Per-symbol backtest cells — one row per (strategy × symbol × venue), the granular truth the pooled
    leaderboard averages away. Outlier-sorted (highest standalone return first) so the operator can SNIPE, with
    the honest verdict (robust/fragile/thin/negative) carried so a lone best-of-N winner is flagged, not
    celebrated. Optional filters narrow by symbol / venue / verdict / version_id. Pure read; never a funding signal.

    Authored-but-UNCOMPUTED versions (no backtest_symbols cell yet) are ALSO surfaced — one synthetic 'New' row each
    — so the whole authored population is visible, not just the ~8 versions that have cells. They are appended AFTER
    the computed cells (which keep the outlier ranking) and only when no symbol/venue/verdict filter is active (a
    cell-less version has no symbol/venue/verdict to match)."""
    conds: list[str] = []
    params: list[object] = []
    if symbol:
        conds.append("bs.symbol = ?")
        params.append(symbol)
    if venue:
        conds.append("bs.venue_id = ?")
        params.append(venue)
    if verdict:
        conds.append("bs.verdict = ?")
        params.append(verdict)
    if version_id:
        conds.append("bs.strategy_version_id = ?")
        params.append(version_id)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    # Cell-less 'New' rows only make sense unfiltered (or filtered to a specific version_id) — a symbol/venue/verdict
    # filter is asking for cells, which a not-yet-computed version has none of.
    include_new = not (symbol or venue or verdict)
    with store.reading():
        # Fetch latest-first so the per-triplet dedup below keeps the most recent backtest, then we
        # re-sort by return for the outlier ranking. A generous cap pre-dedup; the response is trimmed to `limit`.
        rows = store.rows(f"{_cell_select()}{where} ORDER BY bs.created_at DESC LIMIT 5000", tuple(params))
        symbols = [r["symbol"] for r in store.rows("SELECT DISTINCT symbol FROM backtest_symbols ORDER BY symbol")]
        venues = [
            r["venue_id"]
            for r in store.rows("SELECT DISTINCT venue_id FROM backtest_symbols WHERE venue_id IS NOT NULL ORDER BY venue_id")
        ]
        new_rows: list[dict] = []
        if include_new:
            vsql = _CELL_LESS_SELECT
            vparams: tuple = ()
            if version_id:
                vsql += " AND sv.id = ?"
                vparams = (version_id,)
            new_rows = store.rows(f"{vsql} ORDER BY sv.created_at DESC LIMIT 5000", vparams)
    deduped = _dedup_cells(rows)
    deduped.sort(key=lambda r: _metric(r["return_pct"]), reverse=True)
    out = [_cell_row(r) for r in deduped[: max(1, limit)]]
    # Append the authored-but-uncomputed 'New' versions after the ranked cells (they carry no return to rank by),
    # trimmed so the whole response still respects `limit`.
    if new_rows and len(out) < max(1, limit):
        out += [_new_version_row(r) for r in new_rows[: max(1, limit) - len(out)]]
    return LabSymbolsResponse(rows=out, symbols=symbols, venues=venues)


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
