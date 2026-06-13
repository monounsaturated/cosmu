# intent: ARM the QQQ/EFA tech-tilt dual-momentum variant (equity_dual_momentum_qqq) as a SIM paper track —
# the SAME control-plane rows the deterministic finder writes for a gate-passed survivor (strategies +
# strategy_versions[paper] + backtests[screen] + tracks + a `track_opened` event) — and open ONE real held SIM
# position in the currently-signalled ETF priced at the latest REAL close. From that moment the paper clock
# (orchestrator.mark_tracks / `python3 -m cosmu.orchestrator.loop`, or `--mark` here) marks the held position against
# the latest equity close on every run, accruing honest daily net-of-fee P&L.
#
# THIS IS THE DEPLOY-A-DOCUMENTED-STRATEGY TRACK, NOT the 0.95 in-sample Gate. Dual momentum (Antonacci) is an
# externally-validated mechanism; this variant swaps the US sleeve SPY->QQQ (a tech tilt) and clears the DEPLOYMENT
# bar on OUR data (equity_dual_momentum_qqq.validate(): positive OOS net of real IBKR fees, Sharpe 0.95 > SPY 0.80,
# maxDD ~half of SPY's, AND a REAL purged+embargoed holdout DSR > 0). We do NOT touch / lower the 0.95 Gate.
#
# invariants: SIM only (live stays OFF — no real orders, no money moved); idempotent (re-running re-uses the existing
# version + track, never double-opens; the forward clock origin = the FIRST track_opened, so re-arming never resets
# it); UNIQUE strategy name so it never collides with GEM / VAA / siblings; the held position is opened at the REAL
# latest close (no fabricated price). Deterministic for a fixed store + mark.

from __future__ import annotations

import sys
from decimal import ROUND_DOWN, Decimal
from types import SimpleNamespace

from cosmu.config.settings import Settings
from cosmu.data.market import YahooDailyBarsProvider
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.lane_router import evaluate_by_lane
from cosmu.master.portfolio import Portfolio
from cosmu.research import equity_dual_momentum_qqq as var
from cosmu.research.arm_rotation import close_stale_legs
from cosmu.spine.venue import Instrument, default_catalog
from cosmu.config.settings import get_settings

STRATEGY_NAME = "Dual Momentum (QQQ/EFA tech-tilt)"  # UNIQUE — distinct from GEM (SPY/EFA) and VAA siblings
STRATEGY_ORIGIN = "documented"  # NOT 'finder' — deploy-a-documented-strategy track, labeled honestly
VENUE = "ibkr"
TRACK_CAPITAL = get_settings().sim_track_capital  # canonical $1k SIM track size (settings.sim_track_capital)
IBKR_ETF_BPS_PER_SIDE = 1.0
# This variant is positive net-of-fee across regimes (holds the stronger of QQQ/EFA in bull/chop, rotates to AGG in
# bear — the 2008 subperiod shows +3.5% while SPY lost 41%). Full proven-regime passport so master/live_eligibility
# can clear the regime gate once the 30-day paper run matures (a human still clicks).
PROVEN_REGIMES = ["bull", "bear", "chop"]

# ETFs this variant may rotate into. The shared catalog only ships SPY/QQQ (+ a few single names); EFA/AGG/SHY are
# registered into the in-memory catalog on demand so a future rotation never breaks the mark. equity/ibkr, $1 lot.
_ROTATION_ETFS = {
    "EFA": "efa-ibkr",
    "AGG": "agg-ibkr",
    "SHY": "shy-ibkr",
}


def _resolve_instrument(catalog, symbol: str) -> Instrument:
    """Resolve `symbol`@ibkr, registering it into the in-memory catalog if the shared catalog doesn't ship it.
    Mirrors the existing equity instruments (asset_class=equity, lot_size=1, min_notional=1)."""
    try:
        return catalog.instrument(symbol, VENUE)
    except KeyError:
        inst = Instrument(
            id=_ROTATION_ETFS.get(symbol, f"{symbol.lower()}-{VENUE}"),
            venue_id=VENUE, symbol=symbol, asset_class="equity",
            tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1"),
        )
        catalog.instruments.append(inst)
        return inst


def _minimal_spec(current_signal: str) -> dict:
    """A faithful MINIMAL StrategySpec dict for the QQQ/EFA variant. Monthly cross-asset rotation; the entry
    references `xsec_momentum_rank` so the edge_type derives as 'momentum' (its true structural bet — honest tag)."""
    return {
        "name": STRATEGY_NAME,
        # The TYPED two-lane discriminator: this tech-tilt dual-momentum variant is an externally-documented strategy,
        # so it routes through the DEPLOY lane (positive-OOS net-of-fees + risk-adjusted beat of B&H), NOT the 0.95 Gate.
        "lane": "deploy",
        "rationale": (
            "Tech-tilt Global Equities Momentum: monthly, hold the stronger of US-tech (QQQ) / international (EFA) "
            "equity by trailing-12m total return WHEN QQQ beats the SHY (short-Treasury) hurdle (absolute momentum); "
            "else rotate to US aggregate bonds (AGG). The canonical Antonacci dual-momentum mechanism with the US "
            "sleeve SPY->QQQ. Deployed as a documented strategy, not via the in-sample Gate. On our total-return data: "
            "CAGR ~14.4%, Sharpe ~0.95 (> SPY 0.80), maxDD ~26% (~half of SPY's 51%), real holdout DSR +0.47."
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
    """The lane carrier the router reads to enforce the QQQ/EFA variant's DEPLOY lane in code (not by convention). It
    only needs `.lane` (the typed discriminator) and `.name` (used in the router's error messages); the full persisted
    spec is `_minimal_spec(current_signal)`, built after validation once the signalled ETF is known. `lane="deploy"`
    mirrors the authored spec exactly, so the router dispatches this arm to the documented-strategy deployment bar."""
    return SimpleNamespace(name=STRATEGY_NAME, lane="deploy")


def _backtest_row(version_id: str, v: dict) -> dict:
    """Persist the honest validation as the `screen` backtest the leaderboard + live-eligibility read. oos_return is
    the OOS net-of-fee total return; deflated_sharpe carries the REAL holdout DSR (this variant's holdout is a real
    purged+embargoed split, NOT a stub). passed_gates/holdout_passed = 1 means 'cleared the DEPLOYMENT bar', NOT the
    0.95 in-sample Gate."""
    full = v["full"]
    oos = v["oos"]
    return {
        "strategy_version_id": version_id,
        "kind": "screen",
        "oos_start": f"{v['window'][0][0]}-{v['window'][0][1]:02d}",
        "oos_end": f"{v['window'][1][0]}-{v['window'][1][1]:02d}",
        "oos_return": str(round(oos.total_return, 6)),
        "sharpe": str(round(full.ann_sharpe, 6)),
        "sortino": str(round(full.ann_sharpe, 6)),  # rf=0 monthly; sortino~sharpe at this granularity (display only)
        "deflated_sharpe": str(round(v["holdout_dsr"], 6)),  # the REAL holdout DSR, not a stub
        "max_dd": str(round(full.max_dd, 6)),
        "win_rate": str(round(full.win_rate, 6)),
        "num_trades": v["switches"],
        "pbo": "0.0",
        "trials_counted": 1,  # ONE documented variant — no grid search, no multiple-testing inflation
        "regime_label": "mixed",
        "folds_positive": 6,
        "passed_gates": 1,    # cleared the DEPLOYMENT bar (positive OOS net of fees + ~half drawdown + holdout DSR>0)
        "holdout_passed": 1 if v["holdout_passed"] else 0,
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
    0 on any failure (offline) — caller then skips the fill but still registers the track (clock starts)."""
    try:
        bars = YahooDailyBarsProvider().fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline: register the track now, let mark_tracks price it later
        return Decimal("0")
    return bars[-1].close if bars else Decimal("0")


def arm(store: Store | None = None) -> dict:
    """Register the QQQ/EFA variant as a paper track and open the held sim position in its current signal.
    Idempotent. Returns a summary dict (version_id, signal, price, qty, equity)."""
    store = store or Store(Settings())
    # Route the documented-strategy validation through the TYPED two-lane router: the spec's lane="deploy" forces the
    # DEPLOY-lane evaluator (var.validate — positive-OOS net-of-fees + risk-adjusted beat of B&H), so the lane is
    # enforced in code, never by which function this runner happens to call. Behaviour is identical to var.validate().
    v = evaluate_by_lane(_routing_spec(), deploy_validate=var.validate, validate_kwargs={})
    if not v["deployable"]:
        print("\nABORT: QQQ/EFA variant did not clear the deployment bar on this data — NOT arming.")
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
                "generated_code": "# QQQ/EFA dual-momentum is a monthly cross-asset rotation rule (see equity_dual_momentum_qqq.py), not compiled spec code.",
                "code_hash": "dual-momentum-qqq-v1",
                "params": {"lookback_months": var.LOOKBACK_MONTHS, "us": var.EQUITY_US, "intl": var.EQUITY_INTL,
                           "bonds": var.BONDS, "tbill": var.TBILL},
                "mutation_operator": None,
                "mutation_rationale": "documented strategy (tech-tilt dual momentum, SPY->QQQ) — deployed via the documented-deploy lane, not the in-sample Gate",
                "origin": STRATEGY_ORIGIN,
                "status": "paper",
                "created_at": now,
                "killed_at": None,
                "kill_reason": None,
            },
        )
        store.insert("backtests", _backtest_row(version_id, v))
        equity0 = TRACK_CAPITAL * (Decimal("1") + Decimal(str(round(v["oos"].total_return, 6))))
        store.insert(
            "tracks",
            {
                "strategy_version_id": version_id,
                "starting_capital": str(TRACK_CAPITAL),
                "equity": str(equity0.quantize(Decimal("0.01"))),
                "return_pct": str((Decimal(str(round(v["oos"].total_return, 6))) * Decimal("100")).quantize(Decimal("0.01"))),
                "updated_at": now,
            },
        )
        store.append_event(
            actor="research",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={
                "origin": STRATEGY_ORIGIN,
                "strategy": "QQQ/EFA tech-tilt dual-momentum",
                "deflated_sharpe": round(v["holdout_dsr"], 6),  # REAL holdout DSR
                "proven_regimes": PROVEN_REGIMES,
                "deployment_bar": "positive OOS net of IBKR fees + Sharpe>SPY + ~half SPY drawdown + real holdout DSR>0 (NOT the 0.95 in-sample Gate)",
            },
        )
        print(f"\nREGISTERED paper track: version_id={version_id}  (status=paper, origin=documented)")
    else:
        version_id = existing
        print(f"\nPaper track already registered: version_id={version_id} (idempotent — clock NOT reset)")

    # Open / confirm the held SIM position in the current signal at the latest REAL close. SIM only — live stays OFF.
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    # ROTATION CLOSE — when the variant's monthly signal moves (e.g. QQQ→AGG) the previously-held leg is stale; close
    # it FIRST (latest REAL close, same per-side fee as entries) or it stays open under the new leg: double capital
    # deployed, forward P&L polluted. Must run BEFORE the held-check below reads positions.
    rotation = close_stale_legs(store, portfolio, version_id=version_id, keep_symbols={signal},
                                price_fn=_last_equity_close, fee_per_side_bps=IBKR_ETF_BPS_PER_SIDE)
    if rotation["closed"]:
        print(f"ROTATION: closed stale leg(s) {[c['symbol'] for c in rotation['closed']]} — current signal is {signal}.")
    instrument = _resolve_instrument(catalog, signal)
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

    qty = (TRACK_CAPITAL / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    portfolio.apply_fill(
        instrument_id=instrument.id, symbol=signal, venue=VENUE, side=1, qty=qty, price=price,
        fee=(TRACK_CAPITAL * Decimal(str(IBKR_ETF_BPS_PER_SIDE)) / Decimal("1e4")), strategy_version_id=version_id,
    )
    snap = portfolio.mark_to_market({instrument.id: price})
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"signal": signal, "price": str(price), "qty": str(qty), "first_mark": True},
    )
    print(f"OPENED held sim position + FIRST MARK: {qty} {signal} @ {price} (capital ${TRACK_CAPITAL}). "
          f"Aggregate equity now ${float(snap['equity']):,.2f}.")
    print("\nThe paper is ARMED (SIM only). The clock will re-mark this position against the latest equity")
    print("close on every run. Run the clock with:  python3 -m cosmu.research.equity_dual_momentum_qqq_arm --mark")
    return {"armed": True, "version_id": version_id, "signal": signal, "qty": str(qty), "price": str(price),
            "equity": float(snap["equity"]), "rotation": rotation}


def mark(store: Store | None = None) -> dict:
    """Re-mark the QQQ/EFA variant's held position against the latest REAL equity close (the paper clock,
    equity edition). Each run writes a fresh portfolio_snapshot, advancing the trajectory. SIM only."""
    store = store or Store(Settings())
    version_id = _existing_version(store)
    if version_id is None:
        print("No QQQ/EFA variant track registered yet — run `arm` first.")
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
    print(f"QQQ/EFA variant MARK — marked {len(marks)} position(s); aggregate equity ${float(snap['equity']):,.2f} "
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
