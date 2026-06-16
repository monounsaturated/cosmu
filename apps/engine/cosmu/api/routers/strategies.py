# intent: per-version strategy detail + plain-language summary plumbing; inputs: version_id (+ externally
# written summary text on PUT); outputs: StrategyDetailResponse / SummaryFactsResponse; invariants: the engine
# only STORES/SERVES summaries (the text is written externally by the operator's agent — no LLM in this path);
# live stays gated. AUTH: every route here (the PUT included) is behind the app-level shared-secret middleware
# in cosmu/api/app.py — when API_SECRET_KEY is set, a matching `x-api-key` header is required; no per-route check.

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cosmu.api._shared import _json, oos_window_days, store
from cosmu.api.models import (
    Backtest,
    Execution,
    Point,
    StrategyDetailResponse,
    StrategySummaryPutRequest,
    StrategySummaryPutResponse,
    SummaryFactsResponse,
)
from cosmu.api.routers.leaderboard import _money_or_none  # the shared finite-or-None money coercion (never null→0)
from cosmu.knowledge.store import utcnow
from cosmu.research.summary_facts import facts_hash, summary_facts

router = APIRouter()


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
            Backtest(id=bt["id"], kind=bt["kind"], oos_return=float(bt["oos_return"]), deflated_sharpe=float(bt["deflated_sharpe"]), max_dd=float(bt["max_dd"]), win_rate=float(bt["win_rate"]), num_trades=int(bt["num_trades"]), pbo=float(bt["pbo"]), passed_gates=bool(bt["passed_gates"]), oos_window_days=oos_window_days(bt["oos_start"], bt["oos_end"]))
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
