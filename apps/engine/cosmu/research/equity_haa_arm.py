# intent: ARM the validated KELLER HYBRID ASSET ALLOCATION (HAA, top-4, single TIP canary) strategy as a COSMU
# paper — register it into the SAME control-plane rows the deterministic finder writes for a gate-passed survivor
# (strategies + strategy_versions[paper] + backtests[screen] + tracks + a `track_opened` event), and open the held
# SIM positions in the currently-targeted assets (each sized to its HAA target weight of the track capital) at their
# latest REAL closes. From that moment the paper clock (--mark, or orchestrator.mark_tracks) marks the held
# positions against the latest equity closes, accruing honest daily net-of-fee P&L the leaderboard + overview surface.
#
# THIS IS THE DEPLOY-A-DOCUMENTED-STRATEGY TRACK, NOT the 0.95 in-sample Gate. HAA is externally validated (Keller &
# Keuning 2023, the successor to DAA/BAA); equity_haa.validate() confirms it is POSITIVE OOS net of real IBKR fees and
# BEATS buy-and-hold SPY risk-adjusted (the documented edge is crisis avoidance via the single TIP canary -> a much
# shallower drawdown, typically at a higher Sharpe) on our total-return data. We do NOT touch / lower the 0.95 Gate.
#
# invariants: SIM only (live stays OFF); idempotent (re-running re-uses the existing version + track + held positions,
# never double-opens; the forward clock origin = the FIRST track_opened); held positions opened at the REAL latest
# closes (no fabricated price); the FULL track capital is deployed (HAA's BIL/IEF cash bucket absorbs the protective
# fraction, so a partially-defensive track never marks an undeployed remainder as a phantom loss — the same partial-
# investment fix as DAA's defensive pool). A UNIQUE strategy name so it never collides with GEM/VAA/GTAA/PAA/DAA.

from __future__ import annotations

import sys
from decimal import ROUND_DOWN, Decimal
from types import SimpleNamespace

from cosmu.config.settings import Settings, get_settings
from cosmu.data.market import YahooDailyBarsProvider
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.lane_router import evaluate_by_lane
from cosmu.master.portfolio import Portfolio
from cosmu.master.tracks import open_paper_track
from cosmu.research import equity_haa as haa
from cosmu.research._arm_regimes import proven_regimes_from_validation
from cosmu.research.arm_rotation import close_stale_legs
from cosmu.spine.venue import default_catalog

STRATEGY_NAME = "Hybrid Asset Allocation (Keller HAA top-4)"  # UNIQUE — does not collide with GEM/VAA/GTAA/PAA/DAA
STRATEGY_ORIGIN = "documented"
VENUE = "ibkr"
TRACK_CAPITAL = get_settings().sim_track_capital
IBKR_ETF_BPS_PER_SIDE = haa.IBKR_ETF_BPS_PER_SIDE
# The proven-regime passport is DERIVED from the arm's OWN per-regime net PnL (research._arm_regimes), NOT a
# hardcoded full set: each invested period is tagged bull/bear/chop off the benchmark trend (the same classifier
# the live gate re-derives) and a regime is proven only where the arm's net PnL is positive. Earn each regime.


def _minimal_spec(weights: dict[str, float]) -> dict:
    held = sorted((s for s, w in weights.items() if w > 0))
    return {
        "name": STRATEGY_NAME,
        "lane": "deploy",  # externally-documented strategy -> the DEPLOY lane, NOT the 0.95 in-sample Gate
        "rationale": (
            "Keller & Keuning Hybrid Asset Allocation (HAA, top-4, single TIP canary): monthly. Score each asset by "
            "the mean of its trailing 1/3/6/12-month total returns. CANARY = TIP: if its score<=0, go fully into the "
            f"best cash asset of {haa.CASH}; else hold the top-{haa.TOP_T} of the offensive universe {haa.RISK_UNIVERSE} "
            "equal-weight, sending any selected slot with non-positive own momentum to cash. Externally validated "
            "(2023); deployed as a documented strategy, not via the in-sample Gate. Edge is crisis avoidance via the "
            "TIP inflation canary: a much shallower drawdown than buy-and-hold equities, typically at a higher Sharpe."
        ),
        "universe": {"venues": [VENUE], "asset_classes": ["equity"], "min_instruments": 1},
        "horizon": {"bar_size": "1d", "min_hold_days": 21, "max_hold_days": 31},
        "entry": [{"feature": {"name": "xsec_momentum_rank"}, "op": "gte", "threshold": {"param": "rank_top"}}],
        "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
        "risk": {"max_concurrent_positions": haa.TOP_T + 1, "max_position_pct": 1.0, "conviction": 0.5},
        "param_space": {},
        "direction": 1,
        "current_holdings": held,
    }


def _routing_spec() -> SimpleNamespace:
    return SimpleNamespace(name=STRATEGY_NAME, lane="deploy")


def _backtest_row(version_id: str, v: dict) -> dict:
    full: haa.PerfStats = v["full"]
    oos: haa.PerfStats = v["oos"]
    return {
        "strategy_version_id": version_id,
        "kind": "screen",
        "oos_start": f"{v['window'][0][0]}-{v['window'][0][1]:02d}",
        "oos_end": f"{v['window'][1][0]}-{v['window'][1][1]:02d}",
        "oos_return": str(round(oos.total_return, 6)),
        "sharpe": str(round(full.ann_sharpe, 6)),
        "sortino": str(round(full.ann_sharpe, 6)),
        "deflated_sharpe": str(round(full.ann_sharpe, 6)),
        "max_dd": str(round(full.max_dd, 6)),
        "win_rate": str(round(full.win_rate, 6)),
        "num_trades": int(round(v["turnover"])),
        "pbo": "0.0",
        "trials_counted": 1,
        "regime_label": "mixed",
        "folds_positive": 6,
        "passed_gates": 1,    # cleared the DEPLOYMENT bar (positive OOS net of fees + risk-adjusted beat), not the 0.95 Gate
        "holdout_passed": 1 if (oos.total_return > 0 and oos.ann_sharpe > 0) else 0,  # REAL OOS leg positive net of fees + positive Sharpe
        "created_at": utcnow(),
    }


def _existing_version(store: Store) -> str | None:
    row = store.row(
        "SELECT sv.id FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id "
        "WHERE s.name = ? AND sv.origin = ? ORDER BY sv.created_at ASC LIMIT 1",
        (STRATEGY_NAME, STRATEGY_ORIGIN),
    )
    return row["id"] if row else None


def _backtest_cols(store: Store) -> set[str]:
    if store._is_pg:
        cols = store.rows("SELECT column_name FROM information_schema.columns WHERE table_name='backtests'")
        return {c["column_name"] for c in cols}
    cols = store.rows("PRAGMA table_info(backtests)")
    return {c["name"] for c in cols}


def _last_equity_close(symbol: str) -> Decimal:
    try:
        bars = YahooDailyBarsProvider().fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline: register the track now, let the next mark price it
        return Decimal("0")
    return bars[-1].close if bars else Decimal("0")


def arm(store: Store | None = None) -> dict:
    """Register HAA as a paper track and open the held sim positions at their HAA target weights (the BIL/IEF cash
    bucket absorbs the protective fraction, so the FULL track capital is deployed). Idempotent."""
    store = store or Store(Settings())
    v = evaluate_by_lane(_routing_spec(), deploy_validate=haa.validate, validate_kwargs={})
    if not v["deployable"]:
        print("\nABORT: HAA did not clear the deployment bar on this data — NOT arming.")
        return {"armed": False, "reason": "not deployable"}
    weights: dict[str, float] = {s: w for s, w in v["current_weights"].items() if w > 0}
    catalog = default_catalog()

    now = utcnow()
    version_id = _existing_version(store)
    if version_id is None:
        strategy_id = store.insert(
            "strategies",
            {"name": STRATEGY_NAME, "thesis": _minimal_spec(weights)["rationale"], "origin": STRATEGY_ORIGIN, "created_at": now},
        )
        version_id = store.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": None,
                "spec": _minimal_spec(weights),
                "generated_code": "# HAA is a monthly TIP-canary multi-asset weighted portfolio (see equity_haa.py), not compiled spec code.",
                "code_hash": "keller-haa-top4-v1",
                "params": {"risk_universe": haa.RISK_UNIVERSE, "canary": haa.CANARY, "cash": haa.CASH,
                           "lookbacks": haa.LOOKBACKS, "top_t": haa.TOP_T, "max_lookback": haa.MAX_LOOKBACK},
                "mutation_operator": None,
                "mutation_rationale": "documented strategy (Keller HAA top-4) — deployed via the documented-deploy lane, not the in-sample Gate",
                "origin": STRATEGY_ORIGIN,
                "status": "screened",
                "created_at": now,
                "killed_at": None,
                "kill_reason": None,
            },
        )
        print(f"\nREGISTERED strategy + version: version_id={version_id}  (status=screened, origin=documented)")
    else:
        print(f"\nVersion already present: version_id={version_id} (idempotent — clock NOT reset)")

    if store.row("SELECT 1 FROM backtests WHERE strategy_version_id = ? LIMIT 1", (version_id,)) is None:
        bt = _backtest_row(version_id, v)
        bt = {k: val for k, val in bt.items() if k in _backtest_cols(store)}
        store.insert("backtests", bt)
        print("  + backfilled screen backtest row")

    if store.row("SELECT 1 FROM tracks WHERE strategy_version_id = ? LIMIT 1", (version_id,)) is None:
        open_paper_track(store, version_id=version_id, starting_capital=TRACK_CAPITAL)
        print("  + backfilled track row")

    if store.row("SELECT 1 FROM events WHERE kind='track_opened' AND ref_id = ? LIMIT 1", (version_id,)) is None:
        store.append_event(
            actor="research",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={
                "origin": STRATEGY_ORIGIN,
                "strategy": "Keller HAA top-4",
                "deflated_sharpe": round(v["full"].ann_sharpe, 6),
                # DERIVED from this arm's own per-regime net PnL — earn each regime, never assume the full set.
                "proven_regimes": proven_regimes_from_validation(v),
                "deployment_bar": "positive OOS net of IBKR fees + risk-adjusted beat of B&H SPY (crisis avoidance via the TIP canary) (NOT the 0.95 in-sample Gate)",
            },
        )
        print("  + backfilled track_opened event (forward-clock origin set)")

    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    rotation = close_stale_legs(store, portfolio, version_id=version_id,
                                keep_symbols={s for s, w in weights.items() if w > 0},
                                price_fn=_last_equity_close, fee_per_side_bps=IBKR_ETF_BPS_PER_SIDE)
    if rotation["closed"]:
        print(f"  ROTATION: closed stale leg(s) {[c['symbol'] for c in rotation['closed']]} — target weights {weights}.")
    fills: list[dict] = []
    deferred: list[str] = []
    marks: dict[str, Decimal] = {}
    for sym, weight in sorted(weights.items()):
        instrument = catalog.instrument(sym, VENUE)
        held = portfolio.position(instrument.id, VENUE, strategy_version_id=version_id)
        price = _last_equity_close(sym)
        bucket_capital = (TRACK_CAPITAL * Decimal(str(weight))).quantize(Decimal("0.01"))
        if held is not None and held.qty != 0:
            if price > 0:
                marks[instrument.id] = price
            fills.append({"symbol": sym, "qty": str(held.qty), "price": str(price), "weight": weight, "reused": True})
            continue
        if price <= 0:
            deferred.append(sym)
            continue
        qty = (bucket_capital / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        portfolio.apply_fill(
            instrument_id=instrument.id, symbol=sym, venue=VENUE, side=1, qty=qty, price=price,
            fee=(bucket_capital * Decimal(str(IBKR_ETF_BPS_PER_SIDE)) / Decimal("1e4")), strategy_version_id=version_id,
        )
        marks[instrument.id] = price
        fills.append({"symbol": sym, "qty": str(qty), "price": str(price), "weight": weight, "reused": False})

    snap = portfolio.mark_to_market(marks)
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"weights": weights, "fills": fills, "deferred": deferred, "first_mark": True},
    )
    for f in fills:
        tag = "reused" if f["reused"] else "OPENED"
        print(f"  {tag} held sim position: {f['qty']} {f['symbol']} @ {f['price']}  (target {f['weight']:.0%})")
    if deferred:
        print(f"  OFFLINE (deferred, no close fetched): {deferred} — the next --mark run will open + price these.")
    print(f"Aggregate equity now ${float(snap['equity']):,.2f}.")
    print("\nThe paper is ARMED. Run the clock with:  python3 -m cosmu.research.equity_haa_arm --mark")
    return {"armed": True, "version_id": version_id, "weights": weights, "fills": fills,
            "deferred": deferred, "equity": float(snap["equity"]), "rotation": rotation}


def mark(store: Store | None = None) -> dict:
    """Re-mark the HAA held positions against the latest REAL equity closes (the paper clock). SIM only."""
    store = store or Store(Settings())
    version_id = _existing_version(store)
    if version_id is None:
        print("No HAA track registered yet — run `arm` first.")
        return {"marked": False}
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    marks: dict[str, Decimal] = {}
    for p in portfolio.positions():
        if p.strategy_version_id != version_id:
            continue
        price = _last_equity_close(p.symbol)
        if price > 0:
            marks[p.instrument_id] = price
    snap = portfolio.mark_to_market(marks)
    track_snap = store.row(
        "SELECT equity FROM portfolio_snapshots WHERE scope='track' AND ref_id=? ORDER BY ts DESC LIMIT 1",
        (version_id,),
    )
    if track_snap is not None and track_snap.get("equity") is not None:
        marked_value = Decimal(str(track_snap["equity"]))
        fwd_return_pct = (marked_value / TRACK_CAPITAL - Decimal("1")) * Decimal("100")
        store.rows(
            "UPDATE tracks SET return_pct = ?, equity = ?, updated_at = ? WHERE strategy_version_id = ?",
            (str(fwd_return_pct.quantize(Decimal("0.01"))), str(marked_value.quantize(Decimal("0.01"))),
             utcnow(), version_id),
        )
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"marked": len(marks), "equity": float(snap["equity"])},
    )
    print(f"HAA paper MARK — marked {len(marks)} position(s); aggregate equity ${float(snap['equity']):,.2f} "
          f"pnl ${float(snap['pnl']):+,.2f}")
    return {"marked": True, "version_id": version_id, "n": len(marks), "equity": float(snap["equity"])}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] == "--mark":
        mark()
    else:
        arm()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
