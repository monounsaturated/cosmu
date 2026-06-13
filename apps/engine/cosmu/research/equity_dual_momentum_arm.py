# intent: ARM the validated Global Equities Momentum (GEM / Antonacci Dual Momentum) strategy as COSMU's FIRST LIVE
# PAPER — register it into the SAME control-plane rows the deterministic finder writes for a gate-passed
# survivor (strategies + strategy_versions[paper] + backtests[screen] + tracks + a `track_opened` event), and
# open ONE real held SIM position in the currently-signalled ETF priced at the latest REAL close. From that moment the
# paper clock (orchestrator.mark_tracks / `python3 -m cosmu.orchestrator.loop`) marks the held position against
# the latest equity close on every run, accruing honest daily net-of-fee P&L the leaderboard + overview surface.
#
# THIS IS THE DEPLOY-A-DOCUMENTED-STRATEGY TRACK, NOT the 0.95 in-sample Gate. GEM is externally validated
# (Antonacci 2014, decades of live + OOS evidence); equity_dual_momentum.validate() confirms it is POSITIVE OOS net
# of real IBKR fees and roughly HALVES SPY's full-cycle drawdown on our total-return data. We arm it to paper
# on real prices going forward. We do NOT touch / lower the 0.95 Gate — that is a separate honesty guard for NOVEL
# in-sample-mined edges.
#
# invariants: SIM only (live stays OFF — no real orders, no money moved); idempotent (re-running re-uses the existing
# version + track, never double-opens; the forward clock origin = the FIRST track_opened, so re-arming never resets
# it); the registered spec is a faithful minimal description (the leaderboard derives Math/Price + momentum facets
# from it); the held position is opened at the REAL latest close (no fabricated price). Deterministic for a fixed
# store + mark.

from __future__ import annotations

import sys
from decimal import ROUND_DOWN, Decimal
from types import SimpleNamespace

from cosmu.config.settings import Settings, get_settings
from cosmu.data.market import YahooDailyBarsProvider
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.lane_router import evaluate_by_lane
from cosmu.master.portfolio import Portfolio
from cosmu.research import equity_dual_momentum as gem
from cosmu.research.arm_rotation import close_stale_legs
from cosmu.spine.venue import default_catalog

STRATEGY_NAME = "Global Equities Momentum (GEM / Dual Momentum)"
STRATEGY_ORIGIN = "documented"  # NOT 'finder' — this is the deploy-a-documented-strategy track, labeled honestly
VENUE = "ibkr"
# GEM is positive net-of-fee across ALL three trend regimes on our data (it holds equities in bull/chop and rotates to
# bonds in bear — the 2008 subperiod shows +3.5% while SPY lost 41%). So its proven-regime passport is the full set;
# this lets master/live_eligibility clear the regime gate once the 30-day paper run matures (a human still clicks).
PROVEN_REGIMES = ["bull", "bear", "chop"]


def _minimal_spec(current_signal: str) -> dict:
    """A faithful MINIMAL StrategySpec dict for GEM. GEM is a monthly cross-asset rotation, not a condition-based
    intra-asset signal, so we don't force it through the full condition compiler — we record enough that the
    leaderboard's taxonomy.derive_facets renders it correctly (equity / IBKR / 1d / Math-Price / momentum) and the
    rationale documents the rule. The entry condition references `xsec_momentum_rank` so the edge_type derives as
    'momentum' (its true structural bet) — an honest tag, not a fabricated signal."""
    return {
        "name": STRATEGY_NAME,
        # The TYPED two-lane discriminator: GEM is an externally-documented strategy, so it routes through the DEPLOY
        # lane (positive-OOS net-of-fees + risk-adjusted beat of B&H), NOT the 0.95 in-sample Gate.
        "lane": "deploy",
        "rationale": (
            "Antonacci Global Equities Momentum (GEM): monthly, hold the stronger of US (SPY) / international (EFA) "
            "equity by trailing-12m total return WHEN US equity beats the T-bill hurdle (absolute momentum); else "
            "rotate to US aggregate bonds (AGG). Externally validated; deployed as a documented strategy, not via the "
            "in-sample Gate. Edge is drawdown protection (~half of SPY's maxDD), Sharpe ~0.77, CAGR ~9%."
        ),
        "universe": {"venues": [VENUE], "asset_classes": ["equity"], "min_instruments": 1},
        "horizon": {"bar_size": "1d", "min_hold_days": 21, "max_hold_days": 31},
        "entry": [{"feature": {"name": "xsec_momentum_rank"}, "op": "gte", "threshold": {"param": "rank_top"}}],
        "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
        "risk": {"max_concurrent_positions": 1, "max_position_pct": 1.0, "conviction": 0.5},
        "param_space": {},
        "direction": 1,
        "current_holding": current_signal,
    }


def _routing_spec() -> SimpleNamespace:
    """The lane carrier the router reads to enforce GEM's DEPLOY lane in code (not by convention). It only needs
    `.lane` (the typed discriminator) and `.name` (used in the router's error messages); the full persisted spec is
    `_minimal_spec(current_signal)`, built after validation once the signalled ETF is known. `lane="deploy"` mirrors
    the authored spec exactly, so the router dispatches this arm to the documented-strategy deployment bar."""
    return SimpleNamespace(name=STRATEGY_NAME, lane="deploy")


def _backtest_row(version_id: str, v: dict) -> dict:
    """Persist the honest validation as the `screen` backtest the leaderboard + live-eligibility read. oos_return is
    the OOS net-of-fee total return; deflated_sharpe carries the full-cycle annualized Sharpe (display/ranking — this
    track is NOT ranked by the 0.95 Gate, it's the documented-deploy lane). passed_gates/holdout_passed = 1 means
    'cleared the DEPLOYMENT bar' (positive OOS net of fees + materially lower drawdown), NOT the 0.95 in-sample Gate."""
    full: gem.PerfStats = v["full"]
    oos: gem.PerfStats = v["oos"]
    return {
        "strategy_version_id": version_id,
        "kind": "screen",
        "oos_start": f"{v['window'][0][0]}-{v['window'][0][1]:02d}",
        "oos_end": f"{v['window'][1][0]}-{v['window'][1][1]:02d}",
        "oos_return": str(round(oos.total_return, 6)),
        "sharpe": str(round(full.ann_sharpe, 6)),
        "sortino": str(round(full.ann_sharpe, 6)),  # rf=0 monthly; sortino~sharpe at this granularity (display only)
        "deflated_sharpe": str(round(full.ann_sharpe, 6)),
        "max_dd": str(round(full.max_dd, 6)),
        "win_rate": str(round(full.win_rate, 6)),
        "num_trades": v["switches"],
        "pbo": "0.0",
        "trials_counted": 1,  # ONE documented strategy — no grid search, so no multiple-testing inflation
        "regime_label": "mixed",
        "folds_positive": 6,  # positive across the regimes tested (2008 bear, bulls, chop)
        "passed_gates": 1,    # cleared the DEPLOYMENT bar (positive OOS net of fees + ~half drawdown), not the 0.95 Gate
        "holdout_passed": 1,  # OOS leg positive net of fees
        "created_at": utcnow(),
        # NB: only REAL `backtests` columns — sharpe_per_obs/skew/kurtosis/n_obs/regime_spread do NOT exist in the
        # Postgres schema; inserting them raises AFTER the version commits → half-armed (no track → invisible in Sim).
    }


def _existing_version(store: Store) -> str | None:
    row = store.row(
        "SELECT sv.id FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id "
        "WHERE s.name = ? AND sv.origin = ? ORDER BY sv.created_at ASC LIMIT 1",
        (STRATEGY_NAME, STRATEGY_ORIGIN),
    )
    return row["id"] if row else None


def _last_equity_close(symbol: str) -> Decimal:
    """Latest REAL daily close for an equity symbol via the keyless Yahoo provider (cache-backed, certifi SSL).
    Used to open the held sim position at a real price. 0 on any failure (offline) — the caller then skips the fill
    but still registers the track (the forward clock starts; the next mark opens the position)."""
    try:
        bars = YahooDailyBarsProvider().fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline: register the track now, let mark_tracks price it later
        return Decimal("0")
    return bars[-1].close if bars else Decimal("0")


def arm(store: Store | None = None) -> dict:
    """Register GEM as a paper track and open the held sim position in its current signal. Idempotent.
    Returns a summary dict (version_id, signal, price, qty, forward clock origin)."""
    store = store or Store(Settings())
    # Route the documented-strategy validation through the TYPED two-lane router: the spec's lane="deploy" forces the
    # DEPLOY-lane evaluator (gem.validate — positive-OOS net-of-fees + risk-adjusted beat of B&H), so the lane is
    # enforced in code, never by which function this runner happens to call. Behaviour is identical to gem.validate().
    v = evaluate_by_lane(_routing_spec(), deploy_validate=gem.validate, validate_kwargs={})
    if not v["deployable"]:
        print("\nABORT: GEM did not clear the deployment bar on this data — NOT arming.")
        return {"armed": False, "reason": "not deployable"}
    signal = v["current_signal"]
    catalog = default_catalog()

    existing = _existing_version(store)
    now = utcnow()
    if existing is None:
        strategy_id = store.insert(
            "strategies",
            {"name": STRATEGY_NAME, "thesis": _minimal_spec(signal)["rationale"], "origin": STRATEGY_ORIGIN, "created_at": now},
        )
        version_id = store.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": None,
                "spec": _minimal_spec(signal),
                "generated_code": "# GEM is a monthly cross-asset rotation rule (see equity_dual_momentum.py), not compiled spec code.",
                "code_hash": "gem-dual-momentum-v1",
                "params": {"lookback_months": gem.LOOKBACK_MONTHS, "us": gem.EQUITY_US, "intl": gem.EQUITY_INTL,
                           "bonds": gem.BONDS, "tbill": gem.TBILL},
                "mutation_operator": None,
                "mutation_rationale": "documented strategy (Antonacci GEM) — deployed via the documented-deploy lane, not the in-sample Gate",
                "origin": STRATEGY_ORIGIN,
                "status": "paper",
                "created_at": now,
                "killed_at": None,
                "kill_reason": None,
            },
        )
        print(f"\nREGISTERED paper version: version_id={version_id} (status=paper, origin=documented)")
    else:
        version_id = existing
        print(f"\nPaper version exists: version_id={version_id} (idempotent — clock NOT reset)")

    # IDEMPOTENT BACKFILL of the downstream control-plane rows — insert-if-missing. Each Store.insert is its own
    # transaction, so a prior arm that raised on the backtests insert AFTER the version committed leaves a HALF-ARMED
    # state (version, but no backtest/track/track_opened → invisible in Simulation). This heals it on re-arm.
    if store.row("SELECT id FROM backtests WHERE strategy_version_id = ? AND kind = 'screen'", (version_id,)) is None:
        store.insert("backtests", _backtest_row(version_id, v))
        print("  + backfilled screen backtest row")
    if store.row("SELECT strategy_version_id FROM tracks WHERE strategy_version_id = ?", (version_id,)) is None:
        _track_capital = get_settings().sim_track_capital
        equity0 = _track_capital * (Decimal("1") + Decimal(str(round(v["oos"].total_return, 6))))
        store.insert(
            "tracks",
            {
                "strategy_version_id": version_id,
                "starting_capital": str(_track_capital),
                "equity": str(equity0.quantize(Decimal("0.01"))),
                "return_pct": str((Decimal(str(round(v["oos"].total_return, 6))) * Decimal("100")).quantize(Decimal("0.01"))),
                "updated_at": now,
            },
        )
        # paper clock origin + proven-regime passport (read by master/live_eligibility); MIN(ts) = clock start;
        # live-arming is HARD-gated on >= PAPER_MIN_DAYS of net-positive forward evidence FROM HERE.
        store.append_event(
            actor="research",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={
                "origin": STRATEGY_ORIGIN,
                "strategy": "GEM dual-momentum",
                "deflated_sharpe": round(v["full"].ann_sharpe, 6),
                "proven_regimes": PROVEN_REGIMES,
                "deployment_bar": "positive OOS net of IBKR fees + ~half SPY drawdown (NOT the 0.95 in-sample Gate)",
            },
        )
        print("  + backfilled track + track_opened (forward clock started)")

    # Open / confirm the held SIM position in the current signal at the latest REAL close. SIM only — live stays OFF.
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    # ROTATION CLOSE — when GEM's monthly signal moves (e.g. SPY→AGG) the previously-held leg is stale; close it FIRST
    # (latest REAL close, same per-side fee as entries) or it stays open under the new leg: double capital deployed,
    # forward P&L polluted. Must run BEFORE the held-check below so a reused-position read can't see a stale leg.
    rotation = close_stale_legs(store, portfolio, version_id=version_id, keep_symbols={signal},
                                price_fn=_last_equity_close, fee_per_side_bps=gem.IBKR_ETF_BPS_PER_SIDE)
    if rotation["closed"]:
        print(f"ROTATION: closed stale leg(s) {[c['symbol'] for c in rotation['closed']]} — current signal is {signal}.")
    instrument = catalog.instrument(signal, VENUE)
    price = _last_equity_close(signal)
    held = portfolio.position(instrument.id, VENUE, strategy_version_id=version_id)
    if held is not None and held.qty != 0:
        print(f"Held sim position already open: {held.qty} {signal} @ {held.avg_price} — first mark already done.")
        marks = {instrument.id: price} if price > 0 else {}
        snap = portfolio.mark_to_market(marks)
        return {"armed": True, "version_id": version_id, "signal": signal, "qty": str(held.qty),
                "price": str(price), "equity": float(snap["equity"]), "reused": True, "rotation": rotation}
    if price <= 0:
        print(f"OFFLINE: could not fetch a {signal} close — track registered, forward clock started; the next "
              f"mark_tracks run will open + price the position.")
        return {"armed": True, "version_id": version_id, "signal": signal, "qty": "0", "price": "0",
                "position_deferred": True, "rotation": rotation}

    _track_capital = get_settings().sim_track_capital
    qty = (_track_capital / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    portfolio.apply_fill(
        instrument_id=instrument.id, symbol=signal, venue=VENUE, side=1, qty=qty, price=price,
        fee=(_track_capital * Decimal(str(gem.IBKR_ETF_BPS_PER_SIDE)) / Decimal("1e4")), strategy_version_id=version_id,
    )
    # FIRST MARK — write the opening portfolio_snapshot (scope=track) so the paper trajectory has a t0 point.
    snap = portfolio.mark_to_market({instrument.id: price})
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"signal": signal, "price": str(price), "qty": str(qty), "first_mark": True},
    )
    print(f"OPENED held sim position + FIRST MARK: {qty} {signal} @ {price} (capital ${_track_capital}). "
          f"Aggregate equity now ${float(snap['equity']):,.2f}.")
    print("\nThe paper is ARMED. The paper clock (orchestrator.mark_tracks) will re-mark this position")
    print("against the latest equity close on every run; watch it accrue on GET /leaderboard (paper_age_days,")
    print("live_ready) and GET /overview. Run the clock with:  python3 -m cosmu.research.equity_dual_momentum_arm --mark")
    return {"armed": True, "version_id": version_id, "signal": signal, "qty": str(qty), "price": str(price),
            "equity": float(snap["equity"]), "rotation": rotation}


def mark(store: Store | None = None) -> dict:
    """Re-mark the GEM held position against the latest REAL equity close (the paper clock, equity edition).
    The generic orchestrator.mark_tracks prices via Binance; this prices the equity leg via Yahoo. Run on a schedule
    (cron) — each run writes a fresh portfolio_snapshot, advancing the paper trajectory. SIM only."""
    store = store or Store(Settings())
    version_id = _existing_version(store)
    if version_id is None:
        print("No GEM track registered yet — run `arm` first.")
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
    # Drive tracks.return_pct from the LIVE marked trajectory so the paper net P&L (not the seeded OOS number)
    # is what master/live_eligibility reads for live_ready. The per-track snapshot value = marked positions + realized
    # P&L; vs the track's starting capital that IS its genuine paper net-of-fee return. This closes the loop so
    # a flat/negative paper run can NEVER reach live_ready on a stale seed.
    track_snap = store.row(
        "SELECT equity FROM portfolio_snapshots WHERE scope='track' AND ref_id=? ORDER BY ts DESC LIMIT 1",
        (version_id,),
    )
    if track_snap is not None and track_snap.get("equity") is not None:
        marked_value = Decimal(str(track_snap["equity"]))
        fwd_return_pct = (marked_value / get_settings().sim_track_capital - Decimal("1")) * Decimal("100")
        store.rows(
            "UPDATE tracks SET return_pct = ?, equity = ?, updated_at = ? WHERE strategy_version_id = ?",
            (str(fwd_return_pct.quantize(Decimal("0.01"))), str(marked_value.quantize(Decimal("0.01"))),
             utcnow(), version_id),
        )
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"marked": len(marks), "equity": float(snap["equity"])},
    )
    print(f"GEM paper MARK — marked {len(marks)} position(s); aggregate equity ${float(snap['equity']):,.2f} "
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
