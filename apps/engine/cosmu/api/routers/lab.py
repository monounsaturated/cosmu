# intent: the Lab control-plane — author/queue/finder/ML; inputs: briefs + run requests; outputs: typed drafts + cohort/finder summaries; invariants: LLM proposes, the deterministic Gate disposes; never funds.

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from functools import lru_cache

from cosmu.api._shared import (
    _metric,
    _summary_to_response,
    annualized_return,
    annualized_return_lo,
    count_total_combos,
    count_total_strategies,
    oos_window_days,
    settings,
    store,
)
from cosmu.knowledge.store import backtest_symbols_has_oos_window, backtest_symbols_has_timeframe
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
    "{cell_window}{cell_timeframe}b.oos_return AS pooled_return, b.oos_start, b.oos_end, bs.created_at, "
    # Has this cell's VERSION genuinely traded on paper? A real is_paper=1 fill in the executions ledger — the SAME
    # signal the leaderboard/detail-sheet read, so the screener's "Paper" badge can never lie over a no-fill row.
    "EXISTS(SELECT 1 FROM executions e WHERE e.strategy_version_id = bs.strategy_version_id "
    "AND CAST(e.is_paper AS INTEGER) = 1) AS has_paper_fills "
    "FROM backtest_symbols bs "
    "JOIN strategy_versions sv ON sv.id = bs.strategy_version_id "
    "JOIN strategies s ON s.id = sv.strategy_id "
    "LEFT JOIN backtests b ON b.id = bs.backtest_id"
)


@lru_cache(maxsize=64)
def _venue_taker_bps(venue_id: str | None) -> float | None:
    """TODAY's taker fee (bps) for a venue, from the venue catalog — fees-always-today: the backtest charges THIS
    schedule on every bar, so this is the honest fee the cell pays. None for a NULL/unknown venue. Memoized per
    venue id (the catalog is a static singleton). Display-only; never a gate."""
    if not venue_id:
        return None
    try:
        from cosmu.spine.venue import default_catalog

        return float(default_catalog().venue(venue_id).taker_fee_bps)
    except Exception:  # noqa: BLE001 — unknown venue / catalog miss → honest None, never a fabricated fee
        return None


def _cell_select() -> str:
    """The per-cell SELECT, schema-adaptive: includes `bs.oos_window_days AS cell_window_days` (each cell's OWN
    validation window) AND `bs.timeframe AS cell_timeframe` (the LOT-C 4th axis) ONLY when the live
    `backtest_symbols` table carries each column. On a pre-migration prod table a missing column is OMITTED entirely
    (SELECTing it would raise UndefinedColumn) and `_cell_row` falls back (the window → the parent backtest's shared
    window; the timeframe → NULL, resolved client-side to the spec's single bar_size). Probes memoized per DSN."""
    cell_window = "bs.oos_window_days AS cell_window_days, " if backtest_symbols_has_oos_window(store) else ""
    cell_timeframe = "bs.timeframe AS cell_timeframe, " if backtest_symbols_has_timeframe(store) else ""
    return _CELL_SELECT_BASE.format(cell_window=cell_window, cell_timeframe=cell_timeframe)


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
    trades = int(_metric(r["trades"]))
    # The honest "≥ x%/yr" confidence floor — a Sharpe-SE shrinkage of THIS cell's own return over its own window
    # and trade count (None when too thin / window unknown). Turns the point CAGR into a lower-bound the screener
    # can show subtly so a noisy short-window outlier isn't read as fact. Display-only; never a gate.
    ann_lo = annualized_return_lo(r["return_pct"], window_days, r.get("sharpe"), trades)
    # Thin-sample flag: fewer trades on this cell's OWN data than the gate's real floor → too thin to judge honestly.
    # Compared against settings.gates.min_trades (the live constant, NOT a hardcoded 30) so the UI mute/flag tracks
    # the gate. Never a gate itself; the brut min-trades floor still runs in the scorer/promote path.
    thin = trades < settings.gates.min_trades
    return LabSymbolRow(
        strategy_version_id=r["strategy_version_id"],
        strategy_name=r["strategy_name"],
        strategy_id=r["strategy_id"],
        kind=r.get("kind") or "quant",
        status=r.get("status") or "",
        symbol=r["symbol"],
        venue_id=r.get("venue_id"),
        timeframe=r.get("cell_timeframe"),  # the LOT-C 4th axis; NULL for legacy/pre-migration cells (one bar_size)
        return_pct=_metric(r["return_pct"]),
        return_pct_annualized=ann,
        return_pct_annualized_lo=ann_lo,
        oos_window_days=window_days,
        thin=thin,
        sharpe=_metric(r["sharpe"]),
        max_drawdown=_metric(r["max_drawdown"]),
        trades=trades,
        has_paper_fills=bool(r.get("has_paper_fills")),
        fee_bps=_venue_taker_bps(r.get("venue_id")),
        verdict=r.get("verdict"),
        pooled_return_pct=_metric(pooled) if pooled is not None else None,
        created_at=r["created_at"],
    )


def _dedup_cells(rows: list[dict]) -> list[dict]:
    """Keep ONE cell per (STRATEGY, symbol, venue) TRIPLET — the (algo × asset × venue) combo IS the unit the
    operator tracks, NOT the version. A strategy with many near-identical VERSIONS (e.g. DeFi-flow with 3 versions
    all on SOL/USDT at binance) used to show 3 separate rows for the SAME combo; keying on `strategy_id` collapses
    them to one. Rows arrive created_at DESC, so the FIRST seen wins → the LATEST version's cell. This is HONEST:
    latest, never the best-RETURN version (best-of-N selection bias). Crucially the key still carries venue_id: the
    SAME edge on the SAME symbol at two venues is two DISTINCT combos (the fee axis differs) and must NEVER be
    collapsed into one — that was the older bug that hid a venue's P&L behind its sibling's. The key ALSO carries the
    timeframe (the LOT-C 4th axis): the SAME edge on the SAME symbol+venue at two timeframes (1h vs 1d) is likewise two
    DISTINCT combos and must not collapse (a NULL/legacy timeframe normalises to "" so single-tf cells are unchanged)."""
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict] = []
    for r in rows:
        key = (r["strategy_id"], r["symbol"], r.get("venue_id") or "", r.get("cell_timeframe") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


# Track-only strategies: a Version that holds a paper/live TRACK but has NO backtest_symbols cell. These were armed
# via the documented-cohort / arm_fleet path (DAA, ADM, TSMOM, funding-carry, …) rather than the finder/loop screen,
# so they never wrote per-symbol cells — yet they trade on /paper and have a working detail page. The cell-backed
# screener INNER-JOINs backtest_symbols, so they were INVISIBLE here. One synthetic row per such version surfaces
# them: symbol/venue empty (no cell exists), metrics NULL (nothing was computed per-symbol — never a fabricated 0%),
# and the VERSION'S OWN status carried straight through so the lifecycle badge reads Paper/Live (not "New"). We scope
# to track-BEARING versions deliberately: surfacing every cell-less version would dump the whole killed graveyard
# (~420 rows) into the screener; a track is the honest signal that the strategy is actually being forward-tested.
_TRACK_ONLY_SELECT = (
    "SELECT sv.id AS strategy_version_id, sv.strategy_id, s.name AS strategy_name, sv.kind, sv.status, "
    # has_paper_fills for the track-only (TAA) versions too — same predicate as the cell select / leaderboard. A
    # funded paper track that has genuinely executed a rebalance fill carries True → the web badges it "Paper"
    # (matching the ribbon's "Trading" count); an armed-but-never-filled track carries False → badges "New". Without
    # this the funded TAA bots (DAA/VAA/ADM/…) were stamped has_paper_fills=False and mislabelled "New".
    "EXISTS(SELECT 1 FROM executions e WHERE e.strategy_version_id = sv.id "
    "AND CAST(e.is_paper AS INTEGER) = 1) AS has_paper_fills, "
    "sv.created_at "
    "FROM strategy_versions sv "
    "JOIN strategies s ON s.id = sv.strategy_id "
    "WHERE EXISTS (SELECT 1 FROM tracks tr WHERE tr.strategy_version_id = sv.id) "
    "AND NOT EXISTS (SELECT 1 FROM backtest_symbols bs WHERE bs.strategy_version_id = sv.id)"
)


def _track_only_row(r: dict) -> LabSymbolRow:
    """A track-only (armed, no per-symbol cell) Version as a synthetic screener row. No symbol/venue (no cell
    exists); the per-cell metrics are NULL/"—" placeholders (nothing was computed per symbol — NEVER a fabricated
    number) while the version's REAL status drives the lifecycle badge (Paper/Live, not "New"). verdict None so the
    front renders nothing in that slot. The web treats an empty symbol as the uncomputed signal and shows "—"."""
    return LabSymbolRow(
        strategy_version_id=r["strategy_version_id"],
        strategy_name=r["strategy_name"],
        strategy_id=r["strategy_id"],
        kind=r.get("kind") or "quant",
        # The version's real status — a track-only strategy is paper/live, NOT "New". Fall back to "lab" only when
        # the status is genuinely absent (never invent a more-advanced stage).
        status=r.get("status") or "lab",
        # Whether this funded track has actually executed a paper fill — drives the web's "Paper" badge so a funded
        # forward-test bot (TAA) reads "Paper", while an armed-but-never-filled track reads "New".
        has_paper_fills=bool(r.get("has_paper_fills")),
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
                timeframe: str | None = None,
                limit: int = 500) -> LabSymbolsResponse:
    """Per-symbol backtest cells — one row per (strategy × symbol × venue) TRIPLET, the granular truth the pooled
    leaderboard averages away. ONE row per combo (algo × asset × venue): a strategy's many versions on the SAME
    triplet collapse to the LATEST (see `_dedup_cells`), never the best-return one. Outlier-sorted (highest
    standalone return first) so the operator can SNIPE, with the honest verdict carried. Optional filters narrow by
    symbol / venue / verdict / version_id. Pure read; never a funding signal.

    TRACK-ONLY strategies (a paper/live track but NO backtest_symbols cell — armed via the documented-cohort /
    arm_fleet path, e.g. DAA / ADM / TSMOM / funding-carry) are ALSO surfaced — one synthetic row each, carrying the
    version's REAL status (so the badge reads Paper/Live, not "New") with metrics NULL/"—" (nothing was computed per
    symbol). They are appended AFTER the computed cells (no return to rank by), only when no symbol/venue/verdict
    filter is active (a cell-less row has no symbol/venue/verdict to match), and only for strategies NOT already
    represented by a cell-backed row (no double-counting a strategy that has both cells and a track)."""
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
    # The timeframe filter (LOT-C 4th axis) is applied ONLY when the column is live — a pre-migration prod table has no
    # `timeframe` column, so the predicate would raise UndefinedColumn. Absent → the filter is silently a no-op.
    if timeframe and backtest_symbols_has_timeframe(store):
        conds.append("bs.timeframe = ?")
        params.append(timeframe)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    # Track-only rows only make sense unfiltered (or filtered to a specific version_id) — a symbol/venue/verdict/
    # timeframe filter is asking for cells, which a track-only (uncomputed) version has none of.
    include_track_only = not (symbol or venue or verdict or timeframe)
    with store.reading():
        # Fetch latest-first so the per-triplet dedup below keeps the most recent version's cell, then we
        # re-sort by return for the outlier ranking. A generous cap pre-dedup; the response is trimmed to `limit`.
        rows = store.rows(f"{_cell_select()}{where} ORDER BY bs.created_at DESC LIMIT 5000", tuple(params))
        symbols = [r["symbol"] for r in store.rows("SELECT DISTINCT symbol FROM backtest_symbols ORDER BY symbol")]
        venues = [
            r["venue_id"]
            for r in store.rows("SELECT DISTINCT venue_id FROM backtest_symbols WHERE venue_id IS NOT NULL ORDER BY venue_id")
        ]
        # Distinct timeframes present (the LOT-C 4th-axis filter chip) — queried ONLY when the column is live (a
        # pre-migration prod table has no `timeframe` column → empty list, no crash, no chip). Today's single-tf world
        # surfaces at most one value, so the filter is invisible until multi-tf is deliberately enabled.
        timeframes = (
            [
                r["timeframe"]
                for r in store.rows("SELECT DISTINCT timeframe FROM backtest_symbols WHERE timeframe IS NOT NULL ORDER BY timeframe")
            ]
            if backtest_symbols_has_timeframe(store)
            else []
        )
        track_only: list[dict] = []
        if include_track_only:
            vsql = _TRACK_ONLY_SELECT
            vparams: tuple = ()
            if version_id:
                vsql += " AND sv.id = ?"
                vparams = (version_id,)
            track_only = store.rows(f"{vsql} ORDER BY sv.created_at DESC LIMIT 5000", vparams)
    deduped = _dedup_cells(rows)
    deduped.sort(key=lambda r: _metric(r["return_pct"]), reverse=True)
    cap = max(1, limit)
    # The track-only (armed, cell-less) strategies — the FUNDED forward-test bots (DAA / VAA / ADM / … and any
    # live track). These are the operationally critical rows (real capital at work), so they must NEVER be squeezed
    # out by a fat cell universe: RESERVE their space first and trim the ranked CELLS to fit, instead of appending
    # them only "if room is left" (which silently dropped every funded Paper bot whenever the killed/screened cell
    # count alone filled the cap — the grid then showed zero Paper rows while the ribbon still counted them as
    # 'Trading'). Skip any strategy ALREADY represented by a cell-backed row so a strategy with both cells and a
    # track isn't doubled with a redundant synthetic row.
    seen_strategies = {r["strategy_id"] for r in deduped}
    fresh_tracks = [r for r in track_only if r["strategy_id"] not in seen_strategies] if track_only else []
    track_rows = [_track_only_row(r) for r in fresh_tracks[:cap]]
    cell_budget = max(0, cap - len(track_rows))
    out = [_cell_row(r) for r in deduped[:cell_budget]] + track_rows
    # The TRUE denominators over the WHOLE set (not the `limit`-capped slice) so the ribbon shows the honest
    # "loaded of total" instead of passing off a page size as the universe. Counted outside the response trim.
    return LabSymbolsResponse(
        rows=out,
        symbols=symbols,
        venues=venues,
        timeframes=timeframes,
        min_trades=int(settings.gates.min_trades),
        total_combos=count_total_combos(store),
        total_strategies=count_total_strategies(store),
    )


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
