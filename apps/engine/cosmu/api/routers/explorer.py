# intent: Strategy Explorer read-only API — serves stored backtest snapshots for the
# operator's pick-and-compare UI; inputs: DB rows; outputs: ExplorerListResponse /
# ExplorerDetailResponse; invariants: never triggers new backtests, never fabricates numbers,
# honest None for missing fields.

from __future__ import annotations

import math

from fastapi import APIRouter

from cosmu.api._shared import _json, _metric, settings, store
from cosmu.api.models import (
    CostBasisCell,
    CostBasisResponse,
    ExplorerDetailResponse,
    ExplorerListResponse,
    ExplorerPoint,
    ExplorerStats,
    ExplorerTrade,
    ExplorerVersion,
)
from cosmu.research.cost_basis import compute_version_cost_basis
from cosmu.strategy.taxonomy import derive_facets

router = APIRouter()


def _finite(v: object, default: float | None = None) -> float | None:
    """Coerce a nullable DB numeric into a finite float or None (not 0.0)."""
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


@router.get("/explorer", response_model=ExplorerListResponse)
def explorer_list() -> ExplorerListResponse:
    """All strategy versions (lean) for the selector dropdowns."""
    rows = store.rows(
        """
        SELECT sv.id, s.name, sv.status, sv.spec, sv.origin,
               b.deflated_sharpe, b.oos_return
        FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN backtests b ON b.strategy_version_id = sv.id
        ORDER BY CAST(COALESCE(b.deflated_sharpe, 0) AS REAL) DESC
        LIMIT 100
        """
    )
    versions: list[ExplorerVersion] = []
    venues_set: set[str] = set()
    assets_set: set[str] = set()

    for row in rows:
        facets = derive_facets(_json(row["spec"]), row["origin"])
        if facets.venue:
            venues_set.add(facets.venue)
        if facets.asset_class:
            assets_set.add(facets.asset_class)

        # oos_return is ALREADY net-of-fee at the venue it was screened on (run_strategy_backtest charges that
        # venue's taker fee + slippage). Surface it straight — no extra fabricated haircut. The friction-free
        # gross and the net under OTHER venues come from the on-demand cost-basis recompute, never a constant.
        net_pct = _metric(row["oos_return"]) * 100

        versions.append(
            ExplorerVersion(
                version_id=row["id"],
                name=row["name"],
                status=row["status"] or "lab",
                venue=facets.venue,
                asset_class=facets.asset_class,
                timeframe=facets.timeframe,
                signal_family_label=facets.signal_family_label,
                deflated_sharpe=_metric(row["deflated_sharpe"]),
                net_pct=net_pct,
            )
        )

    return ExplorerListResponse(
        versions=versions,
        venues=sorted(venues_set),
        assets=sorted(assets_set),
    )


@router.get("/explorer/{version_id}", response_model=ExplorerDetailResponse)
def explorer_detail(version_id: str) -> ExplorerDetailResponse:
    """Full explorer snapshot for one version — from stored records only, never re-run."""
    row = store.row(
        "SELECT sv.*, s.name FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id WHERE sv.id = ?",
        (version_id,),
    )
    if row is None:
        return ExplorerDetailResponse(
            version_id=version_id,
            name="Unknown",
            spec={},
            available=False,
            equity_curve=[],
            trades=[],
            stats=ExplorerStats(
                thesis=None, asset=None, venue=None, fee_assumed_bps=None,
                data_span_days=None, num_bars=None, gross_return_pct=None,
                net_return_pct=None, cost_ratio=None, num_trades=None,
                deflated_sharpe=None, max_dd=None, oos_holdout_pct=None,
                gate_decision=None, gate_reason=None,
            ),
        )

    spec = _json(row["spec"]) or {}
    facets = derive_facets(spec, row["origin"])

    # Latest stored backtest for this version
    bt_row = store.row(
        "SELECT * FROM backtests WHERE strategy_version_id = ? ORDER BY created_at DESC LIMIT 1",
        (version_id,),
    )

    # All stored fills for this version (simulation trades)
    exec_rows = store.rows(
        "SELECT * FROM executions WHERE strategy_version_id = ? ORDER BY ts ASC",
        (version_id,),
    )

    # ── Build equity curve from fills ──────────────────────────────────────
    # Gross = sum(side × qty × price) without fees; Net = same minus fees.
    equity_curve: list[ExplorerPoint] = []
    if exec_rows:
        gross_acc = 0.0
        net_acc = 0.0
        for fill in exec_rows:
            try:
                price = float(fill["price"])
                qty = float(fill["qty"])
                fee = float(fill["fee"])
            except (TypeError, ValueError):
                continue
            cash = price * qty if fill["side"] == "sell" else -(price * qty)
            gross_acc += cash
            net_acc += cash - fee
            equity_curve.append(
                ExplorerPoint(ts=fill["ts"], gross=round(gross_acc, 4), net=round(net_acc, 4))
            )

    # ── Trades (for entry/exit markers) ────────────────────────────────────
    trades = [
        ExplorerTrade(
            ts=fill["ts"],
            side=fill["side"],
            price=float(fill["price"]),
            qty=float(fill["qty"]),
            fee=float(fill["fee"]),
        )
        for fill in exec_rows
        if _finite(fill.get("price")) is not None
    ]

    # ── Stats ───────────────────────────────────────────────────────────────
    gross_return_pct: float | None = None
    net_return_pct: float | None = None
    cost_ratio: float | None = None
    deflated_sharpe: float | None = None
    max_dd: float | None = None
    num_trades: int | None = None
    gate_decision: str | None = None
    gate_reason: str | None = None

    if bt_row is not None:
        dsr = _finite(bt_row.get("deflated_sharpe"))
        deflated_sharpe = dsr
        oos = _finite(bt_row.get("oos_return"))
        if oos is not None:
            # oos_return is the NET-of-fee return at the screened venue (the backtest already charged that
            # venue's fee + slippage), so surface it AS net — not "gross". A true friction-free gross requires
            # re-running the backtest at zero cost; that (and the net under other venues) is served on demand by
            # GET /strategies/{id}/cost-basis, never faked here with a magic constant.
            net_return_pct = round(oos * 100, 2)
            gross_return_pct = None
        mdd = _finite(bt_row.get("max_dd"))
        max_dd = round(mdd * 100, 2) if mdd is not None else None
        nt = bt_row.get("num_trades")
        try:
            num_trades = int(nt) if nt is not None else None
        except (TypeError, ValueError):
            num_trades = None
        passed = bool(bt_row.get("passed_gates"))
        gate_decision = "PASS" if passed else "FAIL"
        # Best-effort kill reason from events
        ev = store.row(
            "SELECT payload FROM events WHERE kind = 'strategy_killed' AND ref_id = ? ORDER BY id DESC LIMIT 1",
            (version_id,),
        )
        if ev:
            try:
                import json
                payload = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else (ev["payload"] or {})
                gate_reason = str(payload.get("reason") or "")[:200] or None
            except Exception:
                gate_reason = None

    # cost_ratio: fees paid / |gross cash out| — computed directly from the real fills (independent of the
    # stored return), so it survives gross_return_pct being honestly None.
    if equity_curve:
        total_fees = sum(float(fill["fee"]) for fill in exec_rows)
        gross_cash = sum(
            float(fill["price"]) * float(fill["qty"])
            for fill in exec_rows
            if fill["side"] == "sell"
        )
        if gross_cash > 0:
            cost_ratio = round(total_fees / gross_cash, 6)

    # fee assumed: try to get from spec → param_space or venue catalog
    fee_assumed_bps: float | None = None
    try:
        ps = spec.get("param_space") or {}
        # convention in specs: fee_bps or taker_fee_bps key
        for k in ("fee_bps", "taker_fee_bps", "maker_fee_bps"):
            v = ps.get(k)
            if v is not None:
                if isinstance(v, (int, float)):
                    fee_assumed_bps = float(v)
                elif isinstance(v, list) and v:
                    fee_assumed_bps = float(v[0])
                if fee_assumed_bps is not None:
                    break
        if fee_assumed_bps is None:
            # Look up from the venue catalog
            venue_row = store.row(
                "SELECT taker_fee_bps FROM venues WHERE id = ? OR name = ?",
                (facets.venue, facets.venue),
            )
            if venue_row:
                fee_assumed_bps = _finite(venue_row.get("taker_fee_bps"))
    except Exception:
        pass

    # data span: earliest / latest ts in fills or spec horizon
    data_span_days: int | None = None
    num_bars: int | None = None
    if exec_rows:
        try:
            from datetime import datetime
            ts_list = [datetime.fromisoformat(fill["ts"].replace("Z", "+00:00")) for fill in exec_rows]
            ts_list = [t for t in ts_list if t]
            if len(ts_list) >= 2:
                span = (max(ts_list) - min(ts_list)).days
                data_span_days = max(1, span)
        except Exception:
            pass

    # thesis from spec
    thesis: str | None = spec.get("name") or spec.get("description") or row.get("name")
    if thesis and len(thesis) > 80:
        thesis = thesis[:77] + "…"

    # OOS holdout pct from holdout event (best effort)
    oos_holdout_pct: float | None = None
    oos_holdout_pct = _finite(bt_row.get("oos_return")) * 100 if bt_row else None

    stats = ExplorerStats(
        thesis=thesis,
        asset=facets.asset_class or None,
        venue=facets.venue or None,
        fee_assumed_bps=fee_assumed_bps,
        data_span_days=data_span_days,
        num_bars=num_bars,
        gross_return_pct=gross_return_pct,
        net_return_pct=net_return_pct,
        cost_ratio=cost_ratio,
        num_trades=num_trades,
        deflated_sharpe=deflated_sharpe,
        max_dd=max_dd,
        oos_holdout_pct=oos_holdout_pct,
        gate_decision=gate_decision,
        gate_reason=gate_reason,
    )

    return ExplorerDetailResponse(
        version_id=version_id,
        name=row["name"],
        spec=spec,
        available=bt_row is not None or bool(exec_rows),
        equity_curve=equity_curve,
        trades=trades,
        stats=stats,
    )


@router.get("/explorer/{version_id}/cost-basis", response_model=CostBasisResponse)
def explorer_cost_basis(version_id: str) -> CostBasisResponse:
    """Per-basis performance for the fee-basis selector — No fees / venue-1 / venue-2 / … — RECOMPUTED on demand
    from the spec + fitted params on real cached bars (reusing the pure backtest, never a new sim path). The
    relative ordering across bases is the point ("which venue keeps more of the edge"); offline or for an asset
    class not yet wired it returns available=False + reason, an honest "—" rather than a fabricated number."""
    report = compute_version_cost_basis(store, version_id, settings=settings)
    return CostBasisResponse(
        version_id=report.version_id,
        name=report.name,
        available=report.available,
        reason=report.reason,
        gross_return_pct=report.gross_return_pct,
        cells=[
            CostBasisCell(
                basis=item.basis,
                label=item.label,
                venue_id=item.venue_id,
                fee_bps=item.fee_bps,
                slippage_bps=item.slippage_bps,
                impact_bps=item.impact_bps,
                net_return_pct=item.net_return_pct,
                cost_ratio=item.cost_ratio,
                num_trades=item.num_trades,
                holds=item.holds,
            )
            for item in report.items
        ],
    )
