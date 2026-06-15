# intent: gate-ranked leaderboard; inputs: none; outputs: LeaderboardResponse; invariants: every numeric coerced finite; maturity is advisory, never a gate.

from __future__ import annotations

import math

from fastapi import APIRouter

from cosmu.api._shared import _json, _metric, oos_window_days as _oos_window_days, store
from cosmu.api.models import LeaderboardResponse, LeaderboardRow
from cosmu.master.divergence import divergence as forward_divergence
from cosmu.master.paper_maturity import maturity as paper_maturity
from cosmu.strategy.taxonomy import derive_facets

router = APIRouter()

# _oos_window_days now lives in cosmu.api._shared (shared with the strategy-detail router's Backtest column),
# imported above as the same name so this router's call sites are unchanged.


def _money_or_none(value: object) -> float | None:
    """A real dollar figure, or None when it's missing/non-finite — so the v18 money columns (value_usd /
    pnl_usd) carry an honest `null` for an un-marked track instead of a fabricated $0. Never coerces null→0
    (unlike _metric), because for money a missing mark is "—", not zero."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _paper_return_pct(tr_equity: object, starting_capital: object) -> float | None:
    """The real net-of-fee forward return % from the marked trajectory: (marked_equity / starting_capital - 1) * 100.
    Returns None when the track has no marked snapshot yet (day-0 / never marked) or its starting_capital is
    missing/degenerate — so the contract carries an honest `null` rather than the rosy backtest number. A marked
    flat/negative track returns its TRUE (0 / negative) number; never falls back to the backtest."""
    if tr_equity is None or starting_capital is None:
        return None
    try:
        start = float(starting_capital)
        equity = float(tr_equity)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(start) and math.isfinite(equity)) or start <= 0:
        return None
    return (equity / start - 1.0) * 100.0


@router.get("/leaderboard", response_model=LeaderboardResponse)
def leaderboard() -> LeaderboardResponse:
    # The track's paper clock origin = its FIRST `track_opened` event (per-version, written when the
    # deterministic gate opened the standalone track). MIN(ts) is the moment the paper run started ticking;
    # advisory maturity (paper_age_days / live_ready) is computed from it. LEFT JOIN so non-funded rows still
    # appear with a 0-day clock (not yet ready).
    # paper_return_pct is the REAL paper number: marked-to-market equity (the LATEST per-track
    # portfolio_snapshot the mark clock wrote) vs the track's starting_capital — net of fees, since funding.
    # We derive it from the marked SNAPSHOT (not tracks.return_pct, which is SEEDED with the backtest number at
    # funding time): a track with no marked snapshot yet has `tr_equity` NULL → paper_return_pct stays null
    # (day-0 truth), so a fresh track can NEVER surface its rosy backtest as forward performance.
    rows = store.rows(
        """
        SELECT sv.id, s.name, sv.status, sv.spec, sv.origin, b.deflated_sharpe, b.oos_return, b.pbo,
               b.oos_start, b.oos_end, b.num_trades AS bt_trades, ev.funded_at,
               tr.starting_capital, ps.equity AS tr_equity,
               EXISTS(SELECT 1 FROM executions e WHERE e.strategy_version_id = sv.id
                      AND CAST(e.is_paper AS INTEGER) = 1) AS has_paper_fills,
               (SELECT COUNT(*) FROM executions e2 WHERE e2.strategy_version_id = sv.id
                      AND CAST(e2.is_paper AS INTEGER) = 1) AS paper_trades
        FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN backtests b ON b.strategy_version_id = sv.id
        LEFT JOIN (
            SELECT ref_id, MIN(ts) AS funded_at FROM events WHERE kind = 'track_opened' GROUP BY ref_id
        ) ev ON ev.ref_id = sv.id
        LEFT JOIN tracks tr ON tr.strategy_version_id = sv.id
        LEFT JOIN (
            SELECT ref_id, equity FROM portfolio_snapshots p1
            WHERE scope = 'track' AND ts = (
                SELECT MAX(ts) FROM portfolio_snapshots p2 WHERE p2.scope = 'track' AND p2.ref_id = p1.ref_id
            )
        ) ps ON ps.ref_id = sv.id
        -- ACTIVE-FIRST then strength: a funded/active track must NEVER be ranked off the board by a stronger
        -- KILLED one. Killed versions hugely outnumber the live ones (graveyard grows unbounded), so a pure
        -- deflated_sharpe sort + a tight LIMIT silently truncated funded paper tracks below the cut — the
        -- Paper hero (status-filtered Σ allocated) then disagreed with "Invested" (Σ of the rows that survived
        -- the cut). Sorting killed last guarantees every non-killed Version is on the board; killed fill the
        -- rest by strength. LIMIT lifted to 200 so the active tier is never the thing that gets cut.
        ORDER BY (CASE WHEN sv.status = 'killed' THEN 1 ELSE 0 END),
                 CAST(COALESCE(b.deflated_sharpe, 0) AS REAL) DESC
        LIMIT 200
        """
    )
    if not rows:
        return LeaderboardResponse(rows=[])
    out: list[LeaderboardRow] = []
    seen_versions: set[str] = set()  # one row per Version: a Version with >1 backtest fans out the LEFT JOIN
    for row in rows:
      # Dedup to a single row per Version — keep the FIRST (rows are ordered by deflated_sharpe DESC, so the
      # strongest backtest wins). Without this a multi-backtest Version appears twice (and inflates the count).
      if row["id"] in seen_versions:
          continue
      seen_versions.add(row["id"])
      # Defense-in-depth: one malformed row must NEVER 500 the whole floor leaderboard. A row that can't be
      # built is skipped (logged), so the rest of the floor still renders. (derive_facets is also bulletproof.)
      try:
        # net_pct is the net-of-fee return the maturity signal reads — same field surfaced on the row.
        # oos_return is ALREADY net-of-fee at the screened venue (the backtest charged that venue's fee +
        # slippage); surface it straight — no fabricated 0.18 round-trip haircut on top of an already-net number.
        net_pct = _metric(row["oos_return"]) * 100
        # ADVISORY ONLY (master/paper_maturity.py): surfaced, never a gate. The paper clock runs from the
        # track's first mark; live_ready recommends a matured + net-positive track. The operator decides.
        mat = paper_maturity(row["funded_at"], net_pct)
        # HAS THIS TRACK ACTUALLY TRADED ON PAPER? The single source of truth = a real paper fill in the
        # executions ledger (is_paper=1), the SAME signal the detail sheet's blotter reads. A funded
        # documented arm only writes `positions` (apply_fill) and a seeded track snapshot — NO executions —
        # so it must read "—" for every forward money figure, exactly like its sheet says "no fills yet".
        # Gating the marked money on this is what makes the aggregate and the per-strategy sheet tell the
        # SAME honest story (and kills the fabricated value/P&L the screener showed for un-traded tracks).
        has_paper_fills = bool(row["has_paper_fills"])
        # The REAL paper return: marked equity (latest scope='track' snapshot) vs the track's
        # starting_capital, net of fees. None unless the track has genuinely traded on paper — a marked
        # snapshot without a backing fill is NOT a forward result.
        paper_return_pct = _paper_return_pct(row["tr_equity"], row["starting_capital"]) if has_paper_fills else None
        # ADVISORY (master/divergence.py): an early warning that the REAL marked forward return has stopped
        # tracking the backtest this track was funded on. We compare the marked forward return to the backtest OOS
        # return pro-rated to the SAME elapsed forward window (track_return_pct = oos_return*100 is the backtest %,
        # mat.paper_age_days is the marked clock, and the OOS window length comes from the b.oos_start/end bounds).
        # Fails safe to the "insufficient" empty state when the marked window is too short or any input is missing —
        # so a fresh / un-marked track NEVER raises a false alarm. MONITORING ONLY, never on the Gate/money path.
        # Hoisted once: the backtest OOS window length feeds BOTH the divergence pro-rating and the v18
        # `oos_window_days` display column (so the OOS % is shown with its window). None when bounds are bad.
        oos_window_days = _oos_window_days(row["oos_start"], row["oos_end"])
        div = forward_divergence(
            paper_return_pct,
            mat.paper_age_days,
            _metric(row["oos_return"]) * 100,
            oos_window_days,
        )
        # v18 money columns — REAL marked $ value + $ P&L, net of fees. None (not 0) unless the track has
        # genuinely traded on paper (has_paper_fills): a seeded/marked snapshot with no backing fill is not
        # deployed capital, so it reads "—", never a fabricated $value / $0 P&L. pnl_pct ALIASES
        # paper_return_pct so the $ and % can never disagree and the backtest is never surfaced as forward.
        value_usd = _money_or_none(row["tr_equity"]) if has_paper_fills else None
        start_usd = _money_or_none(row["starting_capital"])
        pnl_usd = (value_usd - start_usd) if (value_usd is not None and start_usd is not None) else None
        # Trades at the LATEST stage — paper fills when the track has genuinely traded (has_paper_fills), else
        # the strongest backtest's round-trips — so the count matches the stage the rest of the row reports
        # (paper money vs backtest OOS). None when neither exists (a queued Version with no backtest, no fills).
        _bt_trades = row["bt_trades"]
        trades = int(row["paper_trades"]) if has_paper_fills else (int(_bt_trades) if _bt_trades is not None else None)
        # Facets are DERIVED from the spec's named features (taxonomy.py) — no manual tagging — so the
        # Strategies filters always reflect the strategy's real inputs and structure.
        facets = derive_facets(_json(row["spec"]), row["origin"])
        out.append(
            LeaderboardRow(
                version_id=row["id"],
                name=row["name"],
                # Every numeric field is coerced via _metric so the API NEVER emits
                # null/NaN where the LeaderboardRow contract promises `number`.
                track_return_pct=_metric(row["oos_return"]) * 100,
                deflated_sharpe=_metric(row["deflated_sharpe"]),
                net_pct=net_pct,
                paper_return_pct=paper_return_pct,
                pbo=_metric(row["pbo"]),
                status=row["status"],
                lineage="seed:template -> wfo",
                paper_age_days=mat.paper_age_days,
                live_ready=mat.live_ready,
                # Honest divergence read-out: "insufficient" carries a null gap (the empty state), so the UI never
                # renders a fabricated number for a track without enough marked history.
                divergence_status=div.status,
                divergence_gap_pct=div.gap_pct if div.status != "insufficient" else None,
                has_paper_fills=has_paper_fills,
                trades=trades,
                value_usd=value_usd,
                pnl_usd=pnl_usd,
                pnl_pct=paper_return_pct,
                oos_window_days=oos_window_days,
                signal_family=facets.signal_family,
                signal_family_label=facets.signal_family_label,
                features=facets.features,
                asset_class=facets.asset_class,
                venue=facets.venue,
                timeframe=facets.timeframe,
                origin=facets.origin,
                edge_type=facets.edge_type,
            )
        )
      except Exception:  # noqa: BLE001 — skip a single broken row, never 500 the floor.
        import logging
        logging.getLogger(__name__).warning("leaderboard: skipped a malformed row", exc_info=True)
        continue
    return LeaderboardResponse(rows=out)
