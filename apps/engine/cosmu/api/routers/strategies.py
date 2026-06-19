# intent: per-version strategy detail + plain-language summary plumbing; inputs: version_id (+ externally
# written summary text on PUT); outputs: StrategyDetailResponse / SummaryFactsResponse; invariants: the engine
# only STORES/SERVES summaries (the text is written externally by the operator's agent — no LLM in this path);
# live stays gated. AUTH: every route here (the PUT included) is behind the app-level shared-secret middleware
# in cosmu/api/app.py — when API_SECRET_KEY is set, a matching `x-api-key` header is required; no per-route check.

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from cosmu.api._shared import _json, _metric, annualized_return, oos_window_days, store
from cosmu.api.models import (
    Backtest,
    CellCurvePoint,
    CellCurveResponse,
    Execution,
    LabSymbolsResponse,
    Point,
    StrategyDetailResponse,
    StrategySummaryPutRequest,
    StrategySummaryPutResponse,
    SummaryFactsResponse,
    TripletCardResponse,
)
# The granular triplet cell is built ONE way, in the lab router — reuse its SELECT + row/dedup helpers so the
# strategy-triplet routes here can never drift from /lab/symbols (same columns, same pooled-advisory join).
from cosmu.api.routers.lab import _cell_row, _cell_select, _dedup_cells
from cosmu.api.routers.leaderboard import _money_or_none  # the shared finite-or-None money coercion (never null→0)
from cosmu.knowledge.store import backtest_symbols_has_equity_curve, utcnow
from cosmu.master.scorer import BacktestMetrics, TrialStats, deflated_sharpe_prob
from cosmu.research.summary_facts import facts_hash, summary_facts

router = APIRouter()


def _deflated_sharpe_prob(bt: dict) -> float | None:
    """The GATED deflated-Sharpe PROBABILITY in [0,1] for a backtest row — the number the 0.95 bar actually
    checks — recomputed from the row's persisted survival inputs via master/scorer.deflated_sharpe_prob (the
    SAME function the deterministic Gate runs). Distinct from `backtests.deflated_sharpe`, which is the deflated
    Sharpe RATIO (a ranking number that can exceed 1.0). Trials = this row's own `trials_counted` (no correlation
    haircut), matching score()'s default — verified prod-wide to reproduce the recorded verdict (prob ≥ 0.95 ⟺
    passed_gates). Returns None when the survival columns are absent (pre-migration / arm rows): the UI then falls
    back to the binary passed_gates verdict (≥/< 0.95) rather than fabricating a number. Read-only — never gates."""
    sharpe_per_obs = bt.get("sharpe_per_obs")
    skew = bt.get("skew")
    kurtosis = bt.get("kurtosis")
    n_obs = bt.get("n_obs")
    if sharpe_per_obs is None or skew is None or kurtosis is None or n_obs is None:
        return None
    trials = int(bt.get("trials_counted") or 1)
    metrics = BacktestMetrics(
        oos_return=_metric(bt["oos_return"]),
        sharpe=_metric(bt["sharpe"]) if bt.get("sharpe") is not None else _metric(0),
        sortino=_metric(bt["sortino"]) if bt.get("sortino") is not None else _metric(0),
        max_drawdown=_metric(bt["max_dd"]),
        win_rate=_metric(bt["win_rate"]),
        num_trades=int(bt["num_trades"]),
        sharpe_per_obs=_metric(sharpe_per_obs),
        skew=_metric(skew),
        kurtosis=_metric(kurtosis),
        n_obs=int(n_obs),
        pbo=_metric(bt["pbo"]),
        trials_counted=trials,
    )
    return round(deflated_sharpe_prob(metrics, TrialStats(count=trials)), 6)


@router.get("/strategies/{version_id}", response_model=StrategyDetailResponse)
def strategy_detail(version_id: str) -> StrategyDetailResponse:
    # All reads for this sheet share ONE warm pooled connection (the detail sheet fans out to ~7 reads —
    # version + executions + backtests + summary + summary_facts' 3 reads; without one connection each was a
    # separate round-trip and, cold, the per-call handshake pushed it past the web timeout). Nested store reads
    # (incl. _latest_summary → summary_facts) reuse this connection automatically.
    with store.reading():
        row = store.row(
            "SELECT sv.*, s.name FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id WHERE sv.id = ?",
            (version_id,),
        )
        if row is None:
            row = store.row(
                "SELECT sv.*, s.name FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id ORDER BY sv.created_at DESC LIMIT 1"
            )
        if row is not None:
            version_id = row["id"]
            executions = store.rows("SELECT * FROM executions WHERE strategy_version_id = ? ORDER BY ts DESC LIMIT 50", (version_id,))
            backtests = store.rows("SELECT * FROM backtests WHERE strategy_version_id = ? ORDER BY created_at DESC", (version_id,))
            summary_md, summary_stale, summary_updated_at = _latest_summary(version_id)
            # HONEST forward money for the sheet's money band + equity chart — the SAME pattern the leaderboard
            # serves (marked scope='track' snapshot − starting_capital, gated on a real paper fill), NEVER the
            # execution cash flow and NEVER tracks.equity (the rosy backtest seed). All-or-nothing: every money
            # figure is real only when the track has BOTH a paper fill AND a marked snapshot, else all None.
            has_paper_fills = bool(store.row(
                "SELECT 1 FROM executions WHERE strategy_version_id = ? AND CAST(is_paper AS INTEGER) = 1 LIMIT 1",
                (version_id,),
            ))
            tr = store.row("SELECT starting_capital FROM tracks WHERE strategy_version_id = ?", (version_id,))
            snap_rows = store.rows(
                "SELECT ts, equity FROM portfolio_snapshots WHERE scope = 'track' AND ref_id = ? ORDER BY ts ASC",
                (version_id,),
            )
            pos_rows = store.rows("SELECT qty, avg_price, realized_pnl FROM positions WHERE strategy_version_id = ?", (version_id,))
            marked = bool(snap_rows) and has_paper_fills
            start_usd = _money_or_none(tr["starting_capital"]) if tr else None
            value_usd = _money_or_none(snap_rows[-1]["equity"]) if marked else None
            # realized = Σ positions.realized_pnl over ALL rows (incl. closed qty=0 legs, mirroring portfolio.py);
            # invested = deployed cost basis = Σ avg_price*qty over OPEN rows. Both 0 for a freshly-opened buy-and-hold.
            realized_pnl = float(sum(float(r["realized_pnl"]) for r in pos_rows)) if marked else None
            invested_usd = float(sum(float(r["avg_price"]) * float(r["qty"]) for r in pos_rows)) if marked else None
            pnl_usd = (value_usd - start_usd) if (value_usd is not None and start_usd is not None) else None
            unrealized_pnl = (pnl_usd - realized_pnl) if (pnl_usd is not None and realized_pnl is not None) else None
            forward_equity = [Point(ts=s["ts"], value=float(s["equity"])) for s in snap_rows] if marked else []
    if row is None:
        raise HTTPException(status_code=404, detail="strategy version not found")
    # HONEST holdout: the headline backtest's REAL recorded one-shot-holdout verdict (holdout_passed) + its
    # deflated Sharpe — NEVER a hardcoded constant. {} when the version carries no backtest evidence. (Was
    # holdout={"passed": True, "deflated_sharpe": 0.35, "seen_once": True} for EVERY version — fabricated.)
    _hb = next((b for b in backtests if b.get("passed_gates")), None) or (
        max(backtests, key=lambda b: float(b["deflated_sharpe"])) if backtests else None
    )
    holdout = (
        {"passed": bool(_hb["holdout_passed"]), "deflated_sharpe": float(_hb["deflated_sharpe"]), "seen_once": True}
        if _hb is not None
        else {}
    )
    # Strategy MODEL kind off strategy_versions.kind ("quant" | "llm"; SELECT sv.* carries it). Default "quant"
    # for a pre-migration / malformed value so the sheet never crashes and never invents an "llm" tag.
    _kind = row["kind"] if "kind" in row.keys() else "quant"
    return StrategyDetailResponse(
        version_id=version_id,
        name=row["name"],
        kind=_kind if _kind in ("quant", "llm") else "quant",
        spec=_json(row["spec"]),
        generated_code=row["generated_code"],
        params=_json(row["params"]),
        trades=[
            Execution(id=trade["id"], side=trade["side"], qty=float(trade["qty"]), price=float(trade["price"]), fee=float(trade["fee"]), venue=trade["venue_id"], ts=trade["ts"])
            for trade in executions
        ],
        backtests=[
            Backtest(id=bt["id"], kind=bt["kind"], oos_return=float(bt["oos_return"]), deflated_sharpe=float(bt["deflated_sharpe"]), deflated_sharpe_prob=_deflated_sharpe_prob(bt), max_dd=float(bt["max_dd"]), win_rate=float(bt["win_rate"]), num_trades=int(bt["num_trades"]), pbo=float(bt["pbo"]), passed_gates=bool(bt["passed_gates"]), oos_window_days=oos_window_days(bt["oos_start"], bt["oos_end"]), oos_return_annualized=annualized_return(bt["oos_return"], oos_window_days(bt["oos_start"], bt["oos_end"])))
            for bt in backtests
        ],
        notes_md="Deterministic WFO accepted this version for the standardized track. Live capital remains gated by the global toggle, sim survival, regime fit, and caps.",
        holdout=holdout,
        summary_md=summary_md,
        summary_stale=summary_stale,
        summary_updated_at=summary_updated_at,
        has_paper_fills=has_paper_fills,
        value_usd=value_usd,
        invested_usd=invested_usd,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        pnl_usd=pnl_usd,
        starting_capital=start_usd,
        forward_equity=forward_equity,
    )


def _latest_summary(version_id: str) -> tuple[str | None, bool | None, str | None]:
    """The LATEST stored plain-language summary for a version (research_notes kind='summary'; newest wins) +
    its staleness vs the CURRENT facts. Honest (None, None, None) when no summary row exists — the UI renders
    'No summary yet', never a fabricated narrative."""
    note = store.row(
        "SELECT body_md, structured, created_at FROM research_notes WHERE strategy_version_id = ? AND kind = 'summary' ORDER BY created_at DESC LIMIT 1",
        (version_id,),
    )
    if note is None:
        return None, None, None
    structured = _json(note["structured"])
    pinned = structured.get("facts_hash") if isinstance(structured, dict) else None
    facts = summary_facts(store, version_id)
    stale = bool(facts is not None and pinned != facts_hash(facts))
    return note["body_md"], stale, note["created_at"]


@router.get("/strategies/{version_id}/summary-facts", response_model=SummaryFactsResponse)
def strategy_summary_facts(version_id: str) -> SummaryFactsResponse:
    """The DETERMINISTIC facts a plain-language summary is written from + the sha256 staleness pin. The
    external writer (Claude Code) GETs this, writes prose from these facts ONLY, then PUTs the summary back
    pinned to this exact facts_hash. Read-only; no LLM on this path."""
    facts = summary_facts(store, version_id)
    if facts is None:
        raise HTTPException(status_code=404, detail="strategy version not found")
    return SummaryFactsResponse(facts=facts, facts_hash=facts_hash(facts))


@router.put("/strategies/{version_id}/summary", response_model=StrategySummaryPutResponse)
def put_strategy_summary(version_id: str, request: StrategySummaryPutRequest) -> StrategySummaryPutResponse:
    """Store an EXTERNALLY-WRITTEN plain-language summary as a research_notes row (kind='summary'; the new
    latest wins — no schema change). The deployed engine NEVER generates this text — Claude Code writes it on
    the flat sub; this route only persists it with its facts_hash pin + writer provenance. Auth is the global
    x-api-key middleware (cosmu/api/app.py), the SAME gate every control-plane route sits behind. The embedding
    is the same deterministic keyless embed GraveyardMemory uses, so summaries are recallable like other notes."""
    from cosmu.knowledge.memory import _encode_embedding, embed  # the canonical research_notes serialization

    if summary_facts(store, version_id) is None:
        raise HTTPException(status_code=404, detail="strategy version not found")
    structured = {"facts_hash": request.facts_hash, "model": request.model, "prompt_version": request.prompt_version}
    store.insert(
        "research_notes",
        {
            "strategy_version_id": version_id,
            "kind": "summary",
            "body_md": request.body_md,
            "structured": structured,
            "created_at": utcnow(),
            "embedding": _encode_embedding(embed(request.body_md), store),
        },
    )
    store.append_event(actor="operator", kind="summary_written", ref_type="strategy_version", ref_id=version_id, payload=structured)
    return StrategySummaryPutResponse(ok=True)


@router.get("/strategies/{version_id}/triplet", response_model=TripletCardResponse)
def strategy_triplet(version_id: str, symbol: str | None = None, venue: str | None = None) -> TripletCardResponse:
    """The 'fiche triplet' — ONE focused (algo × asset × venue) backtest cell. The web links here from a clicked
    cell with ?symbol=&venue=; `cell` is the granular standalone result for THAT exact triplet (latest backtest),
    or None when no such cell exists (honest empty — never a fabricated row, never a pooled mean). `strategy_id`
    is the algo the comparison grid groups on, so the asset/venue selector can navigate to a sibling triplet.
    Pure read — the pooled number rides on the cell as advisory only; the deterministic Gate alone funds."""
    with store.reading():
        sv = store.row(
            "SELECT sv.strategy_id, s.name AS strategy_name FROM strategy_versions sv "
            "JOIN strategies s ON s.id = sv.strategy_id WHERE sv.id = ?",
            (version_id,),
        )
        if sv is None:
            raise HTTPException(status_code=404, detail="strategy version not found")
        conds = ["bs.strategy_version_id = ?"]
        params: list[object] = [version_id]
        if symbol:
            conds.append("bs.symbol = ?")
            params.append(symbol)
        # venue None → don't constrain (pick the latest cell for the symbol); "" → the NULL-venue cell explicitly;
        # a real id → that venue. So a sibling whose venue_id is NULL is still addressable, never silently skipped.
        if venue is not None:
            if venue == "":
                conds.append("bs.venue_id IS NULL")
            else:
                conds.append("bs.venue_id = ?")
                params.append(venue)
        where = " WHERE " + " AND ".join(conds)
        rows = store.rows(f"{_cell_select()}{where} ORDER BY bs.created_at DESC LIMIT 1", tuple(params))
    cell = _cell_row(rows[0]) if rows else None
    return TripletCardResponse(
        strategy_id=sv["strategy_id"],
        strategy_version_id=version_id,
        strategy_name=sv["strategy_name"],
        cell=cell,
    )


@router.get("/strategies/{version_id}/cell-curve", response_model=CellCurveResponse)
def strategy_cell_curve(version_id: str, symbol: str, venue: str | None = None) -> CellCurveResponse:
    """The persisted PER-CELL net-of-fee backtest equity curve for ONE focused (symbol, venue) cell — the
    cumulated per-bar net equity the cell's metrics score on, stored at screen time on
    backtest_symbols.equity_curve_json (never re-run, never the pooled basket). The strat sheet's Backtest tab
    requests this for the focused cell, which has no fills to draw a curve from. Honest empty
    (available=False, points=[]) when the cell has no stored curve yet — a cell that never traded, or a
    pre-migration prod row whose column doesn't exist. Pure read.

    `venue` mirrors the /triplet selector: None → the latest cell for the symbol (don't constrain venue);
    "" → the NULL-venue cell explicitly; a real id → that venue."""
    # Pre-migration prod has no equity_curve_json column — SELECTing it would raise UndefinedColumn, so probe
    # first and return the honest empty curve. The probe is memoized per DSN (see store.py).
    if not backtest_symbols_has_equity_curve(store):
        return CellCurveResponse(version_id=version_id, symbol=symbol, venue=venue, available=False, points=[])
    conds = ["bs.strategy_version_id = ?", "bs.symbol = ?"]
    params: list[object] = [version_id, symbol]
    if venue is not None:
        if venue == "":
            conds.append("bs.venue_id IS NULL")
        else:
            conds.append("bs.venue_id = ?")
            params.append(venue)
    where = " WHERE " + " AND ".join(conds)
    with store.reading():
        row = store.row(
            f"SELECT bs.equity_curve_json FROM backtest_symbols bs{where} ORDER BY bs.created_at DESC LIMIT 1",
            tuple(params),
        )
    raw = row.get("equity_curve_json") if row else None
    points: list[CellCurvePoint] = []
    if raw:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            for p in data or []:
                ts, net = p.get("ts"), p.get("net")
                if ts is None or net is None:
                    continue
                points.append(CellCurvePoint(ts=str(ts), net=float(net)))
        except (ValueError, TypeError, AttributeError):
            points = []
    # A chart needs ≥ 2 points to draw a line; below that it's honestly "not available" (the UI renders its
    # per-cell empty state rather than a degenerate single dot).
    return CellCurveResponse(
        version_id=version_id, symbol=symbol, venue=venue, available=len(points) >= 2, points=points,
    )


@router.get("/strategies/{version_id}/comparison", response_model=LabSymbolsResponse)
def strategy_comparison(version_id: str, limit: int = 500) -> LabSymbolsResponse:
    """The 'table de comparaison' — EVERY backtest_symbols cell of the SAME algo (strategy_id) across its assets
    and venues, one row per (version × symbol × venue), outlier-sorted. This is how the fiche shows the clicked
    cell's siblings side by side WITHOUT averaging — each cell keeps its own P&L/verdict. The distinct symbols +
    venues drive the asset/venue selector. Resolves the algo from any one of its versions. Pure read."""
    with store.reading():
        sv = store.row("SELECT strategy_id FROM strategy_versions WHERE id = ?", (version_id,))
        if sv is None:
            raise HTTPException(status_code=404, detail="strategy version not found")
        strategy_id = sv["strategy_id"]
        rows = store.rows(
            f"{_cell_select()} WHERE sv.strategy_id = ? ORDER BY bs.created_at DESC LIMIT 5000",
            (strategy_id,),
        )
    deduped = _dedup_cells(rows)
    deduped.sort(key=lambda r: _metric(r["return_pct"]), reverse=True)
    out = [_cell_row(r) for r in deduped[: max(1, limit)]]
    # Distinct symbols/venues are derived from THIS algo's cells (not the whole DB) so the selector only ever
    # offers triplets that actually exist for this strategy.
    symbols = sorted({r["symbol"] for r in deduped})
    venues = sorted({r["venue_id"] for r in deduped if r.get("venue_id")})
    return LabSymbolsResponse(rows=out, symbols=symbols, venues=venues)
