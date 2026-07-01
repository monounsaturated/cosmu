# intent: per-version strategy detail + plain-language summary plumbing; inputs: version_id (+ externally
# written summary text on PUT); outputs: StrategyDetailResponse / SummaryFactsResponse; invariants: the engine
# only STORES/SERVES summaries (the text is written externally by the operator's agent — no LLM in this path);
# live stays gated. AUTH: every route here (the PUT included) is behind the app-level shared-secret middleware
# in cosmu/api/app.py — when API_SECRET_KEY is set, a matching `x-api-key` header is required; no per-route check.

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from cosmu.api._shared import _json, _metric, annualized_return, honest_track_equity_series, oos_window_days, settings, store
from cosmu.api.models import (
    Backtest,
    CellCurvePoint,
    CellCurveResponse,
    CellProvenanceResponse,
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
from cosmu.master.live_eligibility import cell_id
from cosmu.master.scorer import BacktestMetrics, TrialStats, deflated_sharpe_prob
from cosmu.research.summary_facts import facts_hash, summary_facts

router = APIRouter()

_log = logging.getLogger("cosmu.api.strategies")


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
            # Carry-forward the marked series over the funder's mark-less "collapse-to-seed" snapshots (see
            # honest_track_equity_series) so BOTH the equity chart and the headline value read the real marked book
            # value, never the $1,000 seed a mark-less funder tick wrote. Display-only; the stored rows are untouched.
            honest_series = honest_track_equity_series(snap_rows, tr["starting_capital"] if tr else None)
            value_usd = _money_or_none(honest_series[-1][1]) if (marked and honest_series) else None
            # realized = Σ positions.realized_pnl over ALL rows (incl. closed qty=0 legs, mirroring portfolio.py);
            # invested = deployed cost basis = Σ avg_price*qty over OPEN rows. Both 0 for a freshly-opened buy-and-hold.
            realized_pnl = float(sum(float(r["realized_pnl"]) for r in pos_rows)) if marked else None
            invested_usd = float(sum(float(r["avg_price"]) * float(r["qty"]) for r in pos_rows)) if marked else None
            pnl_usd = (value_usd - start_usd) if (value_usd is not None and start_usd is not None) else None
            unrealized_pnl = (pnl_usd - realized_pnl) if (pnl_usd is not None and realized_pnl is not None) else None
            forward_equity = [Point(ts=ts, value=eq) for ts, eq in honest_series] if marked else []
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
        # The version's raw lifecycle status — so the sheet can show the TRUE stage (Live/Killed), which the
        # trades+backtests shape can't recover. "" when absent (never invents a stage).
        status=(row["status"] if "status" in row.keys() and row["status"] else ""),
        kind=_kind if _kind in ("quant", "llm") else "quant",
        spec=_json(row["spec"]),
        generated_code=row["generated_code"],
        params=_json(row["params"]),
        trades=[
            Execution(id=trade["id"], side=trade["side"], qty=float(trade["qty"]), price=float(trade["price"]), fee=float(trade["fee"]), venue=trade["venue_id"], ts=trade["ts"], is_paper=bool(trade["is_paper"]))
            for trade in executions
        ],
        backtests=[
            Backtest(id=bt["id"], kind=bt["kind"], oos_return=float(bt["oos_return"]), deflated_sharpe=float(bt["deflated_sharpe"]), deflated_sharpe_prob=_deflated_sharpe_prob(bt), max_dd=float(bt["max_dd"]), win_rate=float(bt["win_rate"]), num_trades=int(bt["num_trades"]), pbo=float(bt["pbo"]), passed_gates=bool(bt["passed_gates"]), oos_window_days=oos_window_days(bt["oos_start"], bt["oos_end"]), oos_return_annualized=annualized_return(bt["oos_return"], oos_window_days(bt["oos_start"], bt["oos_end"])))
            for bt in backtests
        ],
        # No hardcoded agent-notes boilerplate — the standalone page falls back to its own EmptyState when empty
        # (real per-version notes are not yet recorded). An honest empty string, never a fabricated narrative.
        notes_md="",
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
    """The PER-CELL net-of-fee backtest equity curve for ONE focused (symbol, venue) cell — the cumulated per-bar
    net equity the cell's metrics score on (never the pooled basket). The strat sheet's Backtest tab requests this
    for the focused cell, which has no fills to draw a curve from.

    Served from the curve persisted at screen time (backtest_symbols.equity_curve_json). When that is NULL/empty —
    the vast majority of EXISTING cells, screened before the column shipped (only NEW screens persist it) — the
    curve is RECOMPUTED ON THE FLY from the version's spec/params over the cell's real bars (one symbol ≈ 1-2s,
    fine on-open) and written back to the row so the next request is cached. Honest empty (available=False,
    points=[]) only when the cell truly has no curve: bars unavailable (offline), an unparseable spec, or a
    degenerate cell that never traded — never a fabricated curve.

    `venue` mirrors the /triplet selector: None → the latest cell for the symbol (don't constrain venue);
    "" → the NULL-venue cell explicitly; a real id → that venue."""
    # Pre-migration prod has no equity_curve_json column — SELECTing it would raise UndefinedColumn, so probe
    # first. We CANNOT cache a recompute back there (no column), so just serve the on-the-fly recompute over the
    # cell's bars (still honest — never a stored constant). The probe is memoized per DSN (see store.py).
    has_curve_col = backtest_symbols_has_equity_curve(store)
    conds = ["bs.strategy_version_id = ?", "bs.symbol = ?"]
    params: list[object] = [version_id, symbol]
    if venue is not None:
        if venue == "":
            conds.append("bs.venue_id IS NULL")
        else:
            conds.append("bs.venue_id = ?")
            params.append(venue)
    where = " WHERE " + " AND ".join(conds)
    _curve_select = "bs.equity_curve_json, " if has_curve_col else ""
    with store.reading():
        row = store.row(
            f"SELECT bs.id, {_curve_select}bs.backtest_id FROM backtest_symbols bs{where} "
            "ORDER BY bs.created_at DESC LIMIT 1",
            tuple(params),
        )
    raw = (row.get("equity_curve_json") if (row and has_curve_col) else None)
    points = _parse_curve_points(raw)
    if len(points) < 2 and row is not None:
        # NULL/empty stored curve (an existing cell, or a never-cached one) → recompute from the spec over the
        # cell's bars, then cache it back to the row when the column exists so subsequent opens are instant.
        recomputed = _recompute_cell_curve(version_id, symbol, venue, row.get("backtest_id"))
        if len(recomputed) >= 2:
            points = recomputed
            if has_curve_col and row.get("id"):
                _persist_cell_curve(str(row["id"]), points)
    # A chart needs ≥ 2 points to draw a line; below that it's honestly "not available" (the UI renders its
    # per-cell empty state rather than a degenerate single dot).
    return CellCurveResponse(
        version_id=version_id, symbol=symbol, venue=venue, available=len(points) >= 2, points=points,
    )


@router.get("/strategies/{version_id}/cell-provenance", response_model=CellProvenanceResponse)
def strategy_cell_provenance(version_id: str, symbol: str, venue: str | None = None) -> CellProvenanceResponse:
    """PER-CELL DATA PROVENANCE for ONE (symbol, venue) cell — EXACTLY what the backtest ran on, so a result is
    never a black box. Surfaces the bar SOURCE, interval, date range, bar count, holdout split, the TODAY's-schedule
    fee/slippage/impact overlay (fees-always-today), and the headline source-vs-venue divergence: whether the price
    SOURCE differed from the live VENUE (a FALLBACK reference was used), the corr/spread divergence metric, and a
    `divergence_flagged` warning. Display/audit only — never a gate input.

    Served from the provenance recorded on the cell's `track_opened` event payload at screen time (the same record
    written for every funded cell). `available` is False when no provenance was recorded (e.g. a cell whose track
    opened before this shipped) — an honest empty state, never a fabricated record. `venue` mirrors the other cell
    routes: None → the latest track-open for the symbol; a real id → that venue's cell."""
    cid = cell_id(version_id, symbol, venue) if venue else None
    with store.reading():
        if cid is not None:
            row = store.row(
                "SELECT payload FROM events WHERE kind = 'track_opened' AND ref_id = ? ORDER BY ts DESC LIMIT 1",
                (cid,),
            )
        else:
            # No venue constraint → the latest track_opened whose payload names this (version, symbol). The ref_id
            # is 'version:symbol:venue', so a LIKE on the version:symbol prefix matches any venue for the symbol.
            row = store.row(
                "SELECT payload FROM events WHERE kind = 'track_opened' AND ref_id LIKE ? ORDER BY ts DESC LIMIT 1",
                (f"{version_id}:{symbol}:%",),
            )
    prov = None
    if row and row.get("payload"):
        try:
            payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            prov = (payload or {}).get("provenance")
        except (ValueError, TypeError):
            prov = None
    if not prov:
        return CellProvenanceResponse(version_id=version_id, symbol=symbol, venue=venue, available=False)
    return CellProvenanceResponse(
        version_id=version_id,
        symbol=symbol,
        venue=venue or prov.get("venue"),
        available=True,
        bar_source=prov.get("bar_source"),
        bar_interval=prov.get("bar_interval"),
        n_bars=prov.get("n_bars"),
        first_bar_ts=prov.get("first_bar_ts"),
        last_bar_ts=prov.get("last_bar_ts"),
        holdout_split_index=prov.get("holdout_split_index"),
        fee_bps=prov.get("fee_bps"),
        slippage_bps=prov.get("slippage_bps"),
        impact_bps=prov.get("impact_bps"),
        reuses_reference=prov.get("reuses_reference"),
        source_is_fallback=prov.get("source_is_fallback"),
        align_corr=prov.get("align_corr"),
        align_spread_bps=prov.get("align_spread_bps"),
        align_overlap=prov.get("align_overlap"),
        divergence_flagged=prov.get("divergence_flagged"),
        log_line=_provenance_log_line(prov),
    )


def _provenance_log_line(prov: dict) -> str | None:
    """Rebuild the one-line provenance summary from a persisted provenance dict (the same shape CellProvenance.
    to_dict() writes), so the API can serve the SAME human-readable line the backtest log emitted. Best-effort —
    None on a malformed dict (the structured fields still carry the truth)."""
    try:
        from cosmu.data.reference import CellProvenance

        return CellProvenance(
            symbol=prov["symbol"], venue=prov["venue"], bar_source=prov["bar_source"],
            bar_interval=prov["bar_interval"], n_bars=prov["n_bars"],
            fee_bps=prov["fee_bps"], slippage_bps=prov["slippage_bps"], impact_bps=prov["impact_bps"],
            reuses_reference=prov["reuses_reference"], source_is_fallback=prov["source_is_fallback"],
            first_bar_ts=prov.get("first_bar_ts"), last_bar_ts=prov.get("last_bar_ts"),
            holdout_split_index=prov.get("holdout_split_index"),
            align_corr=prov.get("align_corr"), align_spread_bps=prov.get("align_spread_bps"),
            align_overlap=prov.get("align_overlap"),
        ).log_line()
    except (KeyError, TypeError):
        return None


def _parse_curve_points(raw: object) -> list[CellCurvePoint]:
    """Deserialize a stored/recomputed [{ts, net}] curve into typed points, dropping any malformed entry. Honest
    empty ([]) on any parse failure — never a fabricated point."""
    points: list[CellCurvePoint] = []
    if not raw:
        return points
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        for p in data or []:
            ts, net = p.get("ts"), p.get("net")
            if ts is None or net is None:
                continue
            points.append(CellCurvePoint(ts=str(ts), net=float(net)))
    except (ValueError, TypeError, AttributeError):
        return []
    return points


def _persist_cell_curve(cell_id: str, points: list[CellCurvePoint]) -> None:
    """Opportunistically cache a recomputed curve back onto the backtest_symbols row so the next request reads it
    instead of re-running the backtest. Best-effort: a write hiccup (read-replica, race) must never fail the read
    path — the curve is already in the response. Display-only; no gate column is touched."""
    try:
        payload = json.dumps([{"ts": p.ts, "net": p.net} for p in points])
        with store.batch() as writer:
            writer.execute("UPDATE backtest_symbols SET equity_curve_json = ? WHERE id = ?", (payload, cell_id))
    except Exception:  # noqa: BLE001 — caching is best-effort; the curve is already served
        _log.info("cell-curve cache-back failed for backtest_symbols.id=%s (served live)", cell_id)


def _recompute_cell_curve(
    version_id: str, symbol: str, venue: str | None, backtest_id: object
) -> list[CellCurvePoint]:
    """Recompute ONE cell's net-of-fee backtest equity curve on the fly — for a cell screened before the curve
    column shipped (its equity_curve_json is NULL). Mirrors the finder's screen path EXACTLY so the curve is the
    SAME net-of-fee stream the cell's metrics scored on, never a re-fitted or differently-costed one:

      1. Load the version's typed spec + fitted params (strategy_versions.spec/params).
      2. Fetch the cell's bars the SAME way the screen does — build_crypto_cells over the venue-tagged universe
         (UniversalOHLCVProvider; Binance reference, Kraken FALLBACK), bounded to JUST this symbol, then pick the
         cell whose venue matches the requested venue. Binance is reachable from this EU host directly.
      3. Charge the SAME costs the cell was scored under (the backtests row's fee_bps/slippage_bps/impact_bps),
         falling back to the venue catalog default when a column is unset (pre-migration / arm rows).
      4. Run a single-symbol run_strategy_backtest_detailed and cumulate per_symbol_runs[key].bar_returns via
         equity_curve_points — the locked gate math (scorer/fdr/trials/cohort) is byte-unchanged (display helper).

    Honest empty ([]) when bars are unavailable, the spec is unparseable, or the cell never traded. Crypto only:
    a non-crypto cell (equity/HL/prediction) has no keyless on-host bar route here, so it returns empty (its curve
    populates as the cron re-screens and persists it) rather than a fabricated series."""
    # Deferred imports: these pull the data/backtest stack (numpy-ish heavy modules) and must not load at API
    # import time — the cell-curve endpoint is the only consumer and it's an on-open, not hot, path.
    from decimal import Decimal

    from cosmu.data.backtest import (
        DEFAULT_IMPACT_BPS,
        DEFAULT_SLIPPAGE_BPS,
        equity_curve_points,
        run_strategy_backtest_detailed,
    )
    from cosmu.data.price_cells import build_crypto_cells
    from cosmu.data.reference import pair_for
    from cosmu.evolution.loop import fit_params
    from cosmu.spine.universe import enabled_universe
    from cosmu.spine.venue import default_catalog
    from cosmu.strategy.spec import StrategySpec

    with store.reading():
        ver = store.row("SELECT spec, params FROM strategy_versions WHERE id = ?", (version_id,))
        bt = (
            store.row(
                "SELECT venue_id, fee_bps, slippage_bps, impact_bps FROM backtests WHERE id = ?",
                (str(backtest_id),),
            )
            if backtest_id is not None
            else None
        )
    if ver is None:
        return []
    try:
        spec = StrategySpec.model_validate(_json(ver["spec"]))
    except Exception:  # noqa: BLE001 — a malformed/legacy spec can't be re-run → honest empty, never fabricated
        _log.info("cell-curve recompute: unparseable spec for version=%s", version_id)
        return []
    params = _json(ver["params"]) or {}
    if not isinstance(params, dict) or not params:
        params = fit_params(spec)  # the finder's deterministic midpoint params (matches a screen with no stored fit)

    # The venue this cell trades — the requested venue, else the cell's recorded backtest venue, else binance.
    venue_id = (venue or (bt["venue_id"] if bt and bt.get("venue_id") else None) or "binance")

    bar_size = spec.horizon.bar_size
    limit = 1500 if bar_size == "1h" else 1000
    canonical = pair_for(symbol, venue_id).id  # both 'BTC/USDT' and bare 'BTCUSDT' normalize to the same pair id
    try:
        enabled_venues, _classes = enabled_universe(store)
    except Exception:  # noqa: BLE001 — offline / no universe table → let build_crypto_cells take its legacy path
        enabled_venues = None
    try:
        cells = build_crypto_cells(
            store, timeframe=bar_size, limit=limit,
            enabled_venues=enabled_venues, fallback_symbols=(canonical,),
        )
    except Exception:  # noqa: BLE001 — provider refused / offline: the cell can't be priced → honest empty
        _log.info("cell-curve recompute: bar fetch failed for %s@%s (version=%s)", symbol, venue_id, version_id)
        return []
    # Pick the cell whose venue matches the request. venue ""/None → the reference (binance) cell. A namespaced
    # 'PAIR@venue' cell carries venue_id; the reference cell carries 'binance'.
    target = next((c for c in cells if c.venue_id == venue_id), None)
    if target is None and venue_id == "binance":
        target = next((c for c in cells if c.reuses_reference), None)  # the reference cell, however keyed
    if target is None or not target.bars:
        return []

    # The costs the cell was SCORED under (the backtests row), else the venue catalog default — never a re-typed
    # literal that could drift from what the screen charged.
    catalog_venue = None
    try:
        catalog_venue = default_catalog().venue(venue_id)
    except KeyError:
        pass
    fee_bps = _bps(bt.get("fee_bps") if bt else None) or (catalog_venue.taker_fee_bps if catalog_venue else Decimal("10"))
    slip_bps = _bps(bt.get("slippage_bps") if bt else None) or (
        catalog_venue.slippage_bps if catalog_venue else DEFAULT_SLIPPAGE_BPS
    )
    impact_bps = _bps(bt.get("impact_bps") if bt else None) or (
        catalog_venue.impact_bps if catalog_venue else DEFAULT_IMPACT_BPS
    )

    market = {target.key: target.bars}
    try:
        # include_holdout=False — the curve is the VALIDATION-window stream the screen scored on (the screen path
        # itself runs the grid with include_holdout=False), so the recompute matches what was persisted.
        detailed = run_strategy_backtest_detailed(
            spec, params, market, fee_bps=fee_bps, slippage_bps=slip_bps, impact_bps=impact_bps,
            include_holdout=False,
        )
    except Exception:  # noqa: BLE001 — a degenerate spec/param combo can't be scored → honest empty
        _log.info("cell-curve recompute: backtest failed for %s@%s (version=%s)", symbol, venue_id, version_id)
        return []
    run = detailed.per_symbol_runs.get(target.key)
    if run is None:
        return []
    return _parse_curve_points(equity_curve_points(run))


def _bps(value: object):  # noqa: ANN201 — Decimal | None
    """Coerce a persisted bps NUMERIC into a positive Decimal, or None when unset/zero/malformed (the caller then
    falls back to the venue catalog default). 0/negative is treated as 'unset' — a real fill always pays a fee."""
    from decimal import Decimal, InvalidOperation

    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d > 0 else None


@router.get("/strategies/{version_id}/comparison", response_model=LabSymbolsResponse)
def strategy_comparison(version_id: str, limit: int = 500) -> LabSymbolsResponse:
    """The 'table de comparaison' — EVERY backtest_symbols cell of the SAME algo (strategy_id) across its assets
    and venues, one row per (symbol × venue) TRIPLET (a strategy's many versions on the same triplet collapse to the
    LATEST via `_dedup_cells`), outlier-sorted. This is how the fiche shows the clicked cell's siblings side by side
    WITHOUT averaging — each cell keeps its own P&L/verdict. The distinct symbols + venues drive the asset/venue
    selector. Resolves the algo from any one of its versions. Pure read."""
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
    # Distinct timeframes (LOT-C 4th axis) for THIS algo's cells — drives the comparison grid's Timeframe filter.
    # Empty until cells carry a timeframe (pre-migration / single-tf), so the chip stays hidden in today's world.
    timeframes = sorted({r["cell_timeframe"] for r in deduped if r.get("cell_timeframe")})
    return LabSymbolsResponse(rows=out, symbols=symbols, venues=venues, timeframes=timeframes, min_trades=int(settings.gates.min_trades))
