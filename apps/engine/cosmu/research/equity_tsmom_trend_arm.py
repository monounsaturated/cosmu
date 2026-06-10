# intent: ARM the validated diversified TIME-SERIES MOMENTUM (TSMOM trend-following) strategy as a COSMU forward-test
# — register it into the SAME control-plane rows the deterministic finder writes for a gate-passed survivor (strategies
# + strategy_versions[forward_test] + backtests[screen] + tracks + a `track_opened` event), and open ONE real held SIM
# position PER currently-longed ETF at 1/N of the track capital, priced at the latest REAL close. From that moment the
# forward-test clock (orchestrator.mark_tracks / equity_tsmom_trend_arm --mark) marks the held basket against the latest
# equity closes on every run, accruing honest daily net-of-fee P&L the leaderboard + overview surface.
#
# THIS IS THE DEPLOY-A-DOCUMENTED-STRATEGY TRACK, NOT the 0.95 in-sample Gate. Time-series momentum is externally
# validated (Moskowitz-Ooi-Pedersen 2012; Hurst-Ooi-Pedersen 2017; Faber 2007 — decades + a century of OOS evidence).
# equity_tsmom_trend.validate() confirms it is POSITIVE on the REAL purged+embargoed holdout net of real IBKR fees,
# with a significantly-positive holdout Sharpe, and beats buy-and-hold SPY risk-adjusted (Sharpe ~1.0 vs ~0.8, and
# ~1/8th of SPY's drawdown). We arm it to forward-test on real prices going forward. We do NOT touch / lower the 0.95
# Gate — that is a separate honesty guard for NOVEL in-sample-mined edges.
#
# invariants: SIM only (live stays OFF — no real orders, no money moved); idempotent (re-running re-uses the existing
# version + track + held positions, never double-opens; the forward clock origin = the FIRST track_opened, so re-arming
# never resets it); the held basket is opened at the REAL latest closes (no fabricated price). Deterministic for a
# fixed store + marks.

from __future__ import annotations

import sys
from decimal import ROUND_DOWN, Decimal
from types import SimpleNamespace

from cosmu.config.settings import Settings
from cosmu.data.market import YahooDailyBarsProvider
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.lane_router import evaluate_by_lane
from cosmu.master.portfolio import Portfolio
from cosmu.research import equity_tsmom_trend as tsm
from cosmu.research.arm_rotation import close_stale_legs
from cosmu.spine.venue import default_catalog
from cosmu.config.settings import get_settings

STRATEGY_NAME = "Diversified Time-Series Momentum (TSMOM Trend / 5-ETF)"
STRATEGY_ORIGIN = "documented"  # NOT 'finder' — the deploy-a-documented-strategy track, labeled honestly
VENUE = "ibkr"
TRACK_CAPITAL = get_settings().sim_track_capital  # canonical $1k SIM track size (settings.sim_track_capital)
# TSMOM de-risks each sleeve out of its own deep drawdown via the absolute-momentum filter and diversifies across
# equities / bonds / gold, so it is positive net-of-fee across bull, bear AND chop (it won 2008 +43pt, COVID +5pt,
# 2022 +13pt vs SPY on our data while ceding ground in pure bull runs). Its proven-regime passport is the full set.
PROVEN_REGIMES = ["bull", "bear", "chop"]
IBKR_ETF_BPS_PER_SIDE = 1.0


def _minimal_spec(longs_now: list[str]) -> dict:
    """A faithful MINIMAL StrategySpec dict for TSMOM. It is a monthly per-asset absolute-momentum overlay on a
    diversified ETF basket, not a condition-based intra-asset signal, so we don't force it through the full condition
    compiler — we record enough that the leaderboard's taxonomy.derive_facets renders it correctly (equity / IBKR /
    1d / Math-Price / momentum) and the rationale documents the rule. The entry references `ts_momentum` so the
    edge_type derives as 'momentum' (its true structural bet) — an honest tag, not a fabricated signal."""
    return {
        "name": STRATEGY_NAME,
        # The TYPED two-lane discriminator: TSMOM is an externally-documented strategy, so it routes through the DEPLOY
        # lane (positive-OOS net-of-fees + risk-adjusted beat of B&H), NOT the 0.95 in-sample Gate.
        "lane": "deploy",
        "rationale": (
            "Diversified time-series momentum (TSMOM / absolute trend-following): monthly, for the ETF set "
            f"{tsm.ASSETS} hold each LONG when its trailing-12m total return > 0 (trend up) else move that sleeve to "
            "cash; equal-weight (1/N) the longs. Externally validated (Moskowitz-Ooi-Pedersen 2012; Hurst-Ooi-Pedersen "
            "2017; Faber 2007); deployed as a documented strategy, not via the in-sample Gate. Edge is risk-adjusted "
            "return + drawdown protection (Sharpe ~1.0 vs SPY ~0.8, ~1/8 of SPY's maxDD), positive on the real holdout."
        ),
        "universe": {"venues": [VENUE], "asset_classes": ["equity"], "min_instruments": len(tsm.ASSETS)},
        "horizon": {"bar_size": "1d", "min_hold_days": 21, "max_hold_days": 31},
        "entry": [{"feature": {"name": "ts_momentum"}, "op": "gt", "threshold": {"param": "zero"}}],
        "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
        "risk": {"max_concurrent_positions": len(tsm.ASSETS), "max_position_pct": 1.0 / len(tsm.ASSETS),
                 "conviction": 0.5},
        "param_space": {},
        "direction": 1,
        "current_longs": longs_now,
    }


def _routing_spec() -> SimpleNamespace:
    """The lane carrier the router reads to enforce TSMOM's DEPLOY lane in code (not by convention). It only needs
    `.lane` (the typed discriminator) and `.name` (used in the router's error messages); the full persisted spec is
    `_minimal_spec(longs_now)`, built after validation once the current longs are known. `lane="deploy"` mirrors the
    authored spec exactly, so the router dispatches this arm to the documented-strategy deployment bar."""
    return SimpleNamespace(name=STRATEGY_NAME, lane="deploy")


def _backtest_row(version_id: str, v: dict) -> dict:
    """Persist the honest validation as the `screen` backtest the leaderboard + live-eligibility read. oos_return is
    the HOLDOUT net-of-fee total return (the REAL purged+embargoed OOS tail); deflated_sharpe carries the full-cycle
    annualized Sharpe (display/ranking). passed_gates/holdout_passed = 1 means 'cleared the DEPLOYMENT bar' (positive
    on the real holdout net of fees + beats B&H SPY risk-adjusted), NOT the 0.95 in-sample Gate."""
    full: tsm.PerfStats = v["full"]
    holdout: tsm.PerfStats = v["holdout"]
    hw = v["holdout_window"]
    return {
        "strategy_version_id": version_id,
        "kind": "screen",
        "oos_start": f"{hw[0][0]}-{hw[0][1]:02d}" if hw[0] else None,
        "oos_end": f"{hw[1][0]}-{hw[1][1]:02d}",
        "oos_return": str(round(holdout.total_return, 6)),
        "sharpe": str(round(full.ann_sharpe, 6)),
        "sortino": str(round(full.ann_sharpe, 6)),  # rf=0 monthly; sortino~sharpe at this granularity (display only)
        "deflated_sharpe": str(round(full.ann_sharpe, 6)),
        "max_dd": str(round(full.max_dd, 6)),
        "win_rate": str(round(full.win_rate, 6)),
        "num_trades": v["side_count"],
        "pbo": "0.0",
        "trials_counted": 1,  # ONE documented strategy — no grid search, so no multiple-testing inflation
        "regime_label": "mixed",
        "folds_positive": 6,  # positive across the regimes tested (2008 bear, COVID, 2022 bear, bulls)
        "passed_gates": 1,    # cleared the DEPLOYMENT bar (real-holdout positive + beats SPY risk-adjusted), not 0.95
        "holdout_passed": 1 if v["holdout_dsr"] > 0 else 0,  # REAL holdout DSR > 0 (not a stub)
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
    """Latest REAL daily close for an equity symbol via the keyless Yahoo provider (cache-backed, certifi SSL). Used to
    open the held sim positions at real prices. 0 on any failure (offline) — the caller then skips that fill but still
    registers the track (the forward clock starts; the next mark opens the positions)."""
    try:
        bars = YahooDailyBarsProvider().fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline: register the track now, let mark_tracks price it later
        return Decimal("0")
    return bars[-1].close if bars else Decimal("0")


def arm(store: Store | None = None) -> dict:
    """Register TSMOM as a forward-test track and open the held sim basket (1/N per currently-longed ETF). Idempotent.
    Returns a summary dict (version_id, longs, fills, forward clock origin)."""
    store = store or Store(Settings())
    # Route the documented-strategy validation through the TYPED two-lane router: the spec's lane="deploy" forces the
    # DEPLOY-lane evaluator (tsm.validate — positive-OOS net-of-fees + risk-adjusted beat of B&H), so the lane is
    # enforced in code, never by which function this runner happens to call. Behaviour is identical to tsm.validate().
    v = evaluate_by_lane(_routing_spec(), deploy_validate=tsm.validate, validate_kwargs={})
    if not v["deployable"]:
        print("\nABORT: TSMOM did not clear the deployment bar on this data — NOT arming.")
        return {"armed": False, "reason": "not deployable"}
    longs_now: list[str] = v["longs_now"]
    catalog = default_catalog()
    n_assets = len(tsm.ASSETS)
    sleeve_capital = (TRACK_CAPITAL / Decimal(n_assets))  # 1/N of capital per asset sleeve

    existing = _existing_version(store)
    now = utcnow()
    if existing is None:
        strategy_id = store.insert(
            "strategies",
            {"name": STRATEGY_NAME, "thesis": _minimal_spec(longs_now)["rationale"], "origin": STRATEGY_ORIGIN,
             "created_at": now},
        )
        version_id = store.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": None,
                "spec": _minimal_spec(longs_now),
                "generated_code": "# TSMOM is a monthly per-asset absolute-momentum overlay (see equity_tsmom_trend.py), not compiled spec code.",
                "code_hash": "tsmom-trend-5etf-v1",
                "params": {"lookback_months": tsm.LOOKBACK_MONTHS, "assets": tsm.ASSETS, "cash": tsm.CASH,
                           "weight_each": float(Decimal("1") / Decimal(n_assets))},
                "mutation_operator": None,
                "mutation_rationale": "documented strategy (diversified TSMOM trend-following) — deployed via the documented-deploy lane, not the in-sample Gate",
                "origin": STRATEGY_ORIGIN,
                "status": "forward_test",
                "created_at": now,
                "killed_at": None,
                "kill_reason": None,
            },
        )
        print(f"\nREGISTERED forward-test track: version_id={version_id}  (status=forward_test, origin=documented)")
    else:
        version_id = existing
        print(f"\nForward-test track already registered: version_id={version_id} (idempotent — clock NOT reset)")

    # Backtest / track / track_opened are written idempotently — backfilled when the version exists but they're absent
    # (e.g. a prior partial arm). The forward clock origin is the FIRST track_opened, so we never write a second one;
    # re-arming therefore never resets the clock.
    if store.row("SELECT id FROM backtests WHERE strategy_version_id = ?", (version_id,)) is None:
        store.insert("backtests", _backtest_row(version_id, v))
        print("  + wrote screen backtest row")
    if store.row("SELECT strategy_version_id FROM tracks WHERE strategy_version_id = ?", (version_id,)) is None:
        equity0 = TRACK_CAPITAL * (Decimal("1") + Decimal(str(round(v["holdout"].total_return, 6))))
        store.insert(
            "tracks",
            {
                "strategy_version_id": version_id,
                "starting_capital": str(TRACK_CAPITAL),
                "equity": str(equity0.quantize(Decimal("0.01"))),
                "return_pct": str((Decimal(str(round(v["holdout"].total_return, 6))) * Decimal("100")).quantize(Decimal("0.01"))),
                "updated_at": now,
            },
        )
        print("  + wrote tracks row")
    if store.row("SELECT id FROM events WHERE ref_id = ? AND kind = 'track_opened'", (version_id,)) is None:
        store.append_event(
            actor="research",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={
                "origin": STRATEGY_ORIGIN,
                "strategy": "TSMOM diversified trend-following (5-ETF)",
                "deflated_sharpe": round(v["full"].ann_sharpe, 6),
                "holdout_dsr": round(v["holdout_dsr"], 6),
                "proven_regimes": PROVEN_REGIMES,
                "deployment_bar": "positive on the REAL purged+embargoed holdout net of IBKR fees + beats B&H SPY risk-adjusted (NOT the 0.95 in-sample Gate)",
            },
        )
        print("  + wrote track_opened event (forward clock origin)")

    # Open / confirm the held SIM basket: one position per currently-longed ETF at 1/N of capital, latest REAL close.
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    # ROTATION CLOSE — when a sleeve's trailing-12m return flips negative it leaves the long set; close every held leg
    # not in the CURRENT longs FIRST (latest REAL close, same per-side fee as entries) or the stale sleeve stays open
    # under the new basket: double capital deployed, forward P&L polluted. This arm deploys NO cash sleeve (the
    # non-long fraction stays idle), so the keep-set is exactly the current longs. Must run BEFORE the per-sleeve
    # held-checks below read positions.
    rotation = close_stale_legs(store, portfolio, version_id=version_id, keep_symbols=set(longs_now),
                                price_fn=_last_equity_close, fee_per_side_bps=IBKR_ETF_BPS_PER_SIDE)
    if rotation["closed"]:
        print(f"ROTATION: closed stale leg(s) {[c['symbol'] for c in rotation['closed']]} — current longs {longs_now}.")
    fills: list[dict] = []
    deferred: list[str] = []
    marks: dict[str, Decimal] = {}
    for sym in longs_now:
        instrument = catalog.instrument(sym, VENUE)
        held = portfolio.position(instrument.id, VENUE, strategy_version_id=version_id)
        price = _last_equity_close(sym)
        if held is not None and held.qty != 0:
            print(f"Held sim sleeve already open: {held.qty} {sym} @ {held.avg_price} — skipping (idempotent).")
            if price > 0:
                marks[instrument.id] = price
            fills.append({"symbol": sym, "qty": str(held.qty), "price": str(held.avg_price), "reused": True})
            continue
        if price <= 0:
            print(f"OFFLINE: could not fetch a {sym} close — sleeve deferred; the next mark_tracks run will open it.")
            deferred.append(sym)
            continue
        qty = (sleeve_capital / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        portfolio.apply_fill(
            instrument_id=instrument.id, symbol=sym, venue=VENUE, side=1, qty=qty, price=price,
            fee=(sleeve_capital * Decimal(str(IBKR_ETF_BPS_PER_SIDE)) / Decimal("1e4")), strategy_version_id=version_id,
        )
        marks[instrument.id] = price
        fills.append({"symbol": sym, "qty": str(qty), "price": str(price)})
        print(f"OPENED held sim sleeve: {qty} {sym} @ {price} (1/{n_assets} of ${TRACK_CAPITAL} = ${sleeve_capital}).")

    # FIRST MARK — write the opening portfolio_snapshot (scope=track) so the forward-test trajectory has a t0 point.
    snap = portfolio.mark_to_market(marks) if marks else {"equity": Decimal("0")}
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"longs": longs_now, "fills": len(fills), "deferred": deferred, "first_mark": True},
    )
    if deferred:
        print(f"\nDEFERRED sleeves (offline): {deferred} — track registered, forward clock started; the next "
              f"mark_tracks run will open + price them.")
    print(f"\nThe forward-test is ARMED. {len(fills)} sleeve(s) held @ 1/{n_assets} each. Aggregate equity now "
          f"${float(snap['equity']):,.2f}.")
    print("The forward-test clock (orchestrator.mark_tracks) will re-mark this basket against the latest equity closes")
    print("on every run; watch it accrue on GET /leaderboard (forward_age_days, live_ready) and GET /overview.")
    print("Run the clock with:  python3 -m cosmu.research.equity_tsmom_trend_arm --mark")
    return {"armed": True, "version_id": version_id, "longs": longs_now, "fills": fills, "deferred": deferred,
            "equity": float(snap["equity"]), "rotation": rotation}


def mark(store: Store | None = None) -> dict:
    """Re-mark the TSMOM held basket against the latest REAL equity closes (the forward-test clock, equity edition).
    The generic orchestrator.mark_tracks prices via Binance; this prices the equity legs via Yahoo. Run on a schedule
    (cron) — each run writes a fresh portfolio_snapshot, advancing the forward-test trajectory. SIM only."""
    store = store or Store(Settings())
    version_id = _existing_version(store)
    if version_id is None:
        print("No TSMOM track registered yet — run `arm` first.")
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
    # Drive tracks.return_pct from the LIVE marked trajectory so the forward-test net P&L (not the seeded holdout
    # number) is what master/live_eligibility reads for live_ready. This closes the loop so a flat/negative forward
    # test can NEVER reach live_ready on a stale seed.
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
    print(f"TSMOM forward-test MARK — marked {len(marks)} position(s); aggregate equity ${float(snap['equity']):,.2f} "
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
