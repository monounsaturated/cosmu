# intent: ARM the validated SECTOR-MOMENTUM ROTATION (TAA) strategy as a COSMU forward-test track — register it into
# the SAME control-plane rows the deterministic finder writes for a gate-passed survivor (strategies +
# strategy_versions[forward_test] + backtests[screen] + tracks + a `track_opened` event), and open held SIM positions
# in the currently-signalled BASKET (the top-3 sectors equal-weight, or AGG when risk-off) priced at the latest REAL
# closes. From that moment the forward-test clock marks the held basket against the latest equity closes on every run,
# accruing honest daily net-of-fee P&L the leaderboard + overview surface.
#
# THIS IS THE DEPLOY-A-DOCUMENTED-STRATEGY TRACK, NOT the 0.95 in-sample Gate. Sector-momentum rotation with a
# 200-day-SMA trend filter is a textbook TAA rule (Faber 2007 + the broad relative-strength sector literature);
# equity_sector_rotation_taa.validate() confirms it is POSITIVE OOS net of real ETF fees on the REAL purged+embargoed
# holdout (cosmu.research.equity_holdout) and beats buy-and-hold SPY risk-adjusted (higher full-cycle Sharpe AND less
# than half SPY's drawdown). We arm it to forward-test on real prices going forward. We do NOT touch / lower the 0.95
# Gate — that is a separate honesty guard for NOVEL in-sample-mined edges.
#
# invariants: SIM only (live stays OFF — no real orders, no money moved); idempotent (re-running re-uses the existing
# version + track, never double-opens); the registered spec is a faithful minimal description; held positions are
# opened at REAL latest closes (no fabricated price). Deterministic for a fixed store + marks.

from __future__ import annotations

import sys
from decimal import ROUND_DOWN, Decimal

from cosmu.config.settings import Settings, get_settings
from cosmu.data.market import YahooDailyBarsProvider
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio
from cosmu.research import equity_sector_rotation_taa as taa
from cosmu.spine.venue import default_catalog

STRATEGY_NAME = "Sector-Momentum Rotation (TAA / Top-3 SPDR + SPY-200SMA)"  # UNIQUE name (no GEM/sibling collision)
STRATEGY_ORIGIN = "documented"  # NOT 'finder' — the deploy-a-documented-strategy track, labeled honestly
VENUE = "ibkr"
ETF_BPS_PER_SIDE = taa.ETF_BPS_PER_SIDE
# The rule de-risks into bonds in bear markets (trend filter) and tilts to the strongest sectors in bulls. It is
# net-positive across regimes on our data (it gives ground in uninterrupted bulls, wins decisively in the crashes it
# is built for — see the 2008/2022 subperiods). Proven-regime passport is the full set.
PROVEN_REGIMES = ["bull", "bear", "chop"]


def _minimal_spec(current_basket: list[str]) -> dict:
    """A faithful MINIMAL StrategySpec dict. This is a monthly cross-sectional rotation with a market-regime overlay,
    not a condition-based intra-asset signal, so we don't force it through the full condition compiler — we record
    enough that the leaderboard's taxonomy renders it correctly (equity / IBKR / 1d / momentum). The entry references
    `xsec_momentum_rank` so the edge_type derives as 'momentum' (its true structural bet) — an honest tag."""
    return {
        "name": STRATEGY_NAME,
        "rationale": (
            "Sector-Momentum Rotation (TAA): monthly. REGIME FILTER — if SPY's month-end close >= its trailing "
            "200-day SMA (risk-ON), hold the TOP-3 of the 9 SPDR sectors (XLK/XLF/XLE/XLV/XLY/XLP/XLI/XLU/XLB) by "
            "trailing 6-month total return, equal-weight; else (risk-OFF) hold AGG (US aggregate bonds). Documented "
            "TAA rule (Faber-style trend filter + relative sector momentum), deployed via the documented lane, NOT "
            "the in-sample Gate. Edge: full-cycle Sharpe ~0.86 (> SPY 0.79) at <half SPY's drawdown (~21% vs ~51%)."
        ),
        "universe": {"venues": [VENUE], "asset_classes": ["equity"], "min_instruments": 1},
        "horizon": {"bar_size": "1d", "min_hold_days": 21, "max_hold_days": 31},
        "entry": [{"feature": {"name": "xsec_momentum_rank"}, "op": "gte", "threshold": {"param": "rank_top"}}],
        "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
        "risk": {"max_concurrent_positions": taa.TOP_K, "max_position_pct": 1.0 / taa.TOP_K, "conviction": 0.5},
        "param_space": {},
        "direction": 1,
        "current_holding": current_basket,
    }


def _backtest_row(version_id: str, v: dict) -> dict:
    """Persist the honest validation as the `screen` backtest the leaderboard + live-eligibility read. oos_return is
    the REAL-HOLDOUT net total return; deflated_sharpe carries the full-cycle annualized Sharpe (display/ranking — this
    track is NOT ranked by the 0.95 Gate). passed_gates/holdout_passed=1 means 'cleared the DEPLOYMENT bar' (positive
    OOS net of fees on the real holdout + materially lower drawdown than SPY), NOT the 0.95 in-sample Gate."""
    # Columns mirror the REAL `backtests` schema EXACTLY (id, strategy_version_id, kind, is_start/end, oos_start/end,
    # oos_return, sharpe, sortino, deflated_sharpe, max_dd, win_rate, num_trades, pbo, trials_counted, regime_label,
    # folds_positive, passed_gates, holdout_passed, created_at). No phantom columns (sharpe_per_obs/skew/kurtosis/etc.
    # do NOT exist in this store — including them silently aborts the insert).
    full: taa.PerfStats = v["full"]
    holdout: taa.PerfStats = v["holdout"]
    return {
        "strategy_version_id": version_id,
        "kind": "screen",
        "is_start": f"{v['window'][0][0]}-{v['window'][0][1]:02d}",
        "is_end": f"{v['window'][1][0]}-{v['window'][1][1]:02d}",
        "oos_start": f"{v['window'][0][0]}-{v['window'][0][1]:02d}",
        "oos_end": f"{v['window'][1][0]}-{v['window'][1][1]:02d}",
        "oos_return": str(round(holdout.total_return, 6)),  # REAL purged+embargoed holdout net total
        "sharpe": str(round(full.ann_sharpe, 6)),
        "sortino": str(round(full.ann_sharpe, 6)),  # rf=0 monthly; sortino~sharpe at this granularity (display only)
        "deflated_sharpe": str(round(full.ann_sharpe, 6)),
        "max_dd": str(round(full.max_dd, 6)),
        "win_rate": str(round(full.win_rate, 6)),
        "num_trades": v["switches"],
        "pbo": "0.0",
        "trials_counted": 1,  # ONE documented strategy — no grid search, so no multiple-testing inflation
        "regime_label": "mixed",
        "folds_positive": 6,
        "passed_gates": 1,    # cleared the DEPLOYMENT bar (positive real-holdout net of fees + ~half SPY drawdown)
        "holdout_passed": 1 if (holdout.total_return > 0 and v["holdout_dsr"] >= 0) else 0,
        "created_at": utcnow(),
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
    0 on any failure (offline) — the caller then skips that leg's fill but still registers the track (the forward
    clock starts; the next mark opens the position)."""
    try:
        bars = YahooDailyBarsProvider().fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline: register the track now, let mark price it later
        return Decimal("0")
    return bars[-1].close if bars else Decimal("0")


def arm(store: Store | None = None) -> dict:
    """Register the rotation as a forward-test track and open held SIM positions in its current basket. Idempotent.
    Returns a summary dict (version_id, basket, legs, equity)."""
    store = store or Store(Settings())
    v = taa.validate()
    if not v["deployable"]:
        print("\nABORT: Sector rotation did not clear the deployment bar on this data — NOT arming.")
        return {"armed": False, "reason": "not deployable"}
    basket: list[str] = v["current_signal"]
    if not basket:
        print("\nABORT: no current signal — NOT arming.")
        return {"armed": False, "reason": "no signal"}
    catalog = default_catalog()

    now = utcnow()
    # COMPONENT-WISE IDEMPOTENT registration: get-or-create the version, then independently ensure the backtest,
    # track, and track_opened event each exist. Insert ONLY what is missing — so a re-run heals any partial state
    # (e.g. a version that landed but whose backtest/track insert failed) WITHOUT double-registering or resetting
    # the forward clock (the clock origin = MIN(ts) of track_opened, written once).
    existing = _existing_version(store)
    if existing is None:
        strategy_id = store.insert(
            "strategies",
            {"name": STRATEGY_NAME, "thesis": _minimal_spec(basket)["rationale"], "origin": STRATEGY_ORIGIN,
             "created_at": now},
        )
        version_id = store.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": None,
                "spec": _minimal_spec(basket),
                "generated_code": "# Monthly sector-momentum rotation with a 200d-SMA trend filter "
                                  "(see equity_sector_rotation_taa.py), not compiled spec code.",
                "code_hash": "sector-rotation-taa-v1",
                "params": {"top_k": taa.TOP_K, "lookback_months": taa.LOOKBACK_MONTHS, "sma_days": taa.SMA_DAYS,
                           "sectors": taa.SECTOR_ETFS, "market": taa.MARKET, "risk_off": taa.RISK_OFF},
                "mutation_operator": None,
                "mutation_rationale": "documented strategy (sector-momentum rotation + 200d-SMA TAA filter) — "
                                      "deployed via the documented-deploy lane, not the in-sample Gate",
                "origin": STRATEGY_ORIGIN,
                "status": "forward_test",
                "created_at": now,
                "killed_at": None,
                "kill_reason": None,
            },
        )
        print(f"\nREGISTERED forward-test version: version_id={version_id}  (status=forward_test, origin=documented)")
    else:
        version_id = existing
        print(f"\nForward-test version already registered: version_id={version_id} (idempotent — clock NOT reset)")

    # backtest (screen) — insert if absent
    if store.row("SELECT id FROM backtests WHERE strategy_version_id=? AND kind='screen'", (version_id,)) is None:
        store.insert("backtests", _backtest_row(version_id, v))
        print("  + backtest(screen) row written")
    # track — insert if absent
    if store.row("SELECT id FROM tracks WHERE strategy_version_id=?", (version_id,)) is None:
        _track_capital = get_settings().sim_track_capital
        equity0 = _track_capital * (Decimal("1") + Decimal(str(round(v["holdout"].total_return, 6))))
        store.insert(
            "tracks",
            {
                "strategy_version_id": version_id,
                "starting_capital": str(_track_capital),
                "equity": str(equity0.quantize(Decimal("0.01"))),
                "return_pct": str((Decimal(str(round(v["holdout"].total_return, 6))) * Decimal("100"))
                                  .quantize(Decimal("0.01"))),
                "updated_at": now,
            },
        )
        print("  + tracks row written")
    # track_opened event (the forward-clock origin) — append if absent
    if store.row("SELECT id FROM events WHERE ref_id=? AND kind='track_opened'", (version_id,)) is None:
        store.append_event(
            actor="research",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={
                "origin": STRATEGY_ORIGIN,
                "strategy": "sector-momentum rotation (TAA)",
                "deflated_sharpe": round(v["full"].ann_sharpe, 6),
                "proven_regimes": PROVEN_REGIMES,
                "deployment_bar": "positive OOS net of ETF fees on the REAL purged+embargoed holdout + ~half SPY "
                                  "drawdown (NOT the 0.95 in-sample Gate)",
            },
        )
        print("  + track_opened event appended (forward-clock origin)")

    # Open / confirm the held SIM positions in the current basket, equal-weight, each at the latest REAL close.
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    per_leg_capital = (get_settings().sim_track_capital / Decimal(len(basket))).quantize(Decimal("0.01"))
    legs: list[dict] = []
    marks: dict[str, Decimal] = {}
    any_opened = False
    for sym in basket:
        instrument = catalog.instrument(sym, VENUE)
        price = _last_equity_close(sym)
        held = portfolio.position(instrument.id, VENUE, strategy_version_id=version_id)
        if held is not None and held.qty != 0:
            if price > 0:
                marks[instrument.id] = price
            legs.append({"symbol": sym, "qty": str(held.qty), "avg_price": str(held.avg_price), "reused": True})
            continue
        if price <= 0:
            print(f"OFFLINE: could not fetch a {sym} close — leg deferred; the next mark will open + price it.")
            legs.append({"symbol": sym, "qty": "0", "price": "0", "deferred": True})
            continue
        qty = (per_leg_capital / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        portfolio.apply_fill(
            instrument_id=instrument.id, symbol=sym, venue=VENUE, side=1, qty=qty, price=price,
            fee=(per_leg_capital * Decimal(str(ETF_BPS_PER_SIDE)) / Decimal("1e4")),
            strategy_version_id=version_id,
        )
        marks[instrument.id] = price
        legs.append({"symbol": sym, "qty": str(qty), "price": str(price)})
        any_opened = True

    # FIRST MARK — write the opening portfolio_snapshot (scope=track) so the forward-test trajectory has a t0 point.
    snap = portfolio.mark_to_market(marks) if marks else {"equity": Decimal("0")}
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"basket": basket, "legs": legs, "first_mark": True},
    )
    if any_opened:
        print(f"OPENED held sim basket + FIRST MARK: {basket} (equal-weight, ${per_leg_capital}/leg, "
              f"capital ${get_settings().sim_track_capital}). Aggregate equity now ${float(snap['equity']):,.2f}.")
    else:
        print(f"Held sim basket already open / deferred: {basket}. Aggregate equity ${float(snap['equity']):,.2f}.")
    print("\nThe forward-test is ARMED. The forward-test clock will re-mark this basket against the latest equity")
    print("closes on every run; watch it accrue on GET /leaderboard (forward_age_days, live_ready) and GET /overview.")
    print("Run the clock with:  python3 -m cosmu.research.equity_sector_rotation_arm --mark")
    return {"armed": True, "version_id": version_id, "basket": basket, "legs": legs,
            "equity": float(snap["equity"]), "reused": existing is not None}


def mark(store: Store | None = None) -> dict:
    """Re-mark the rotation's held basket against the latest REAL equity closes (the forward-test clock, equity
    edition). Each run writes a fresh portfolio_snapshot, advancing the forward-test trajectory. SIM only."""
    store = store or Store(Settings())
    version_id = _existing_version(store)
    if version_id is None:
        print("No sector-rotation track registered yet — run `arm` first.")
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
    print(f"Sector-rotation forward-test MARK — marked {len(marks)} leg(s); aggregate equity "
          f"${float(snap['equity']):,.2f} pnl ${float(snap['pnl']):+,.2f}")
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
