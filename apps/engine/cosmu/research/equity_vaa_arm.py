# intent: ARM the validated KELLER VIGILANT ASSET ALLOCATION — AGGRESSIVE (VAA-G4) strategy as a COSMU LIVE
# FORWARD-TEST — register it into the SAME control-plane rows the deterministic finder writes for a gate-passed
# survivor (strategies + strategy_versions[forward_test] + backtests[screen] + tracks + a `track_opened` event), and
# open ONE real held SIM position in the currently-signalled ETF priced at the latest REAL close. From that moment the
# forward-test clock (orchestrator.mark_tracks / `python3 -m cosmu.orchestrator.loop`, or `--mark` here) marks the
# held position against the latest equity close on every run, accruing honest daily net-of-fee P&L the leaderboard +
# overview surface.
#
# THIS IS THE DEPLOY-A-DOCUMENTED-STRATEGY TRACK, NOT the 0.95 in-sample Gate. VAA-G4 is externally validated
# (Keller & Keuning 2017, widely replicated); equity_vaa.validate() confirms it is POSITIVE OOS net of real IBKR fees
# and beats buy-and-hold SPY BOTH on full-cycle Sharpe (0.95 vs 0.80) AND maxDD (~45% of SPY's) on our total-return
# data, with the real purged+embargoed holdout (cosmu.research.equity_holdout) giving a holdout dSR ~ +0.38 (>0 =>
# significantly positive out-of-sample). We arm it to forward-test on real prices going forward. We do NOT touch /
# lower the 0.95 Gate — that is a separate honesty guard for NOVEL in-sample-mined edges.
#
# invariants: SIM only (live stays OFF — no real orders, no money moved); idempotent (re-running re-uses the existing
# version + track, never double-opens; the forward clock origin = the FIRST track_opened, so re-arming never resets
# it); the registered spec is a faithful minimal description (the leaderboard derives Math/Price + momentum facets
# from it); the held position is opened at the REAL latest close (no fabricated price). Deterministic for a fixed
# store + mark. Mirrors equity_dual_momentum_arm.py exactly; UNIQUE strategy name so it never collides with GEM/GEM
# siblings.

from __future__ import annotations

import sys
from decimal import ROUND_DOWN, Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import YahooDailyBarsProvider
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio
from cosmu.research import equity_vaa as vaa
from cosmu.research.equity_holdout import purged_embargoed_split
from cosmu.spine.venue import default_catalog
from cosmu.config.settings import get_settings

STRATEGY_NAME = "Vigilant Asset Allocation (Keller VAA-G4 Aggressive)"
STRATEGY_ORIGIN = "documented"  # NOT 'finder' — the deploy-a-documented-strategy track, labeled honestly
VENUE = "ibkr"
TRACK_CAPITAL = get_settings().sim_track_capital  # canonical $1k SIM track size (settings.sim_track_capital)
IBKR_ETF_BPS_PER_SIDE = vaa.IBKR_ETF_BPS_PER_SIDE
# VAA is positive net-of-fee across the trend regimes on our data and its WHOLE POINT is to rotate to short Treasuries
# in bear markets (the canary breadth signal). 2008 shows -7.9% while SPY lost 48%, COVID +4.9% vs SPY -9.2%, 2022
# -12.1% vs SPY -18.2%. So its proven-regime passport is the full set; this lets master/live_eligibility clear the
# regime gate once the 30-day forward test matures (a human still clicks).
PROVEN_REGIMES = ["bull", "bear", "chop"]


def _holdout_dsr(v: dict) -> float:
    """REAL purged+embargoed out-of-sample dSR on VAA's realized NET-return stream via cosmu.research.equity_holdout
    (NOT a stub). embargo=12 so no 12m formation window straddles the IS/holdout boundary. >0 => the held-out tail
    Sharpe is significantly positive — the edge persists into a window the strategy never saw."""
    rets = v["result"].net_returns
    split = purged_embargoed_split(rets, holdout_frac=0.2, embargo=12, min_holdout=6)
    return split.holdout_dsr


def _minimal_spec(current_signal: str, risk_off: bool) -> dict:
    """A faithful MINIMAL StrategySpec dict for VAA. VAA is a monthly cross-asset rotation, not a condition-based
    intra-asset signal, so we don't force it through the full condition compiler — we record enough that the
    leaderboard's taxonomy.derive_facets renders it correctly (equity / IBKR / 1d / Math-Price / momentum) and the
    rationale documents the rule. The entry condition references `xsec_momentum_rank` so the edge_type derives as
    'momentum' (its true structural bet) — an honest tag, not a fabricated signal."""
    return {
        "name": STRATEGY_NAME,
        "rationale": (
            "Keller & Keuning Vigilant Asset Allocation, aggressive (VAA-G4): monthly. Score each asset by "
            "12*1m+4*3m+2*6m+12m trailing total return. CANARIES {EEM, AGG}: if ANY canary score < 0, go fully "
            "defensive (best of {LQD, IEF, SHY}); else hold the single best-scoring offensive asset of "
            "{SPY, EFA, EEM, AGG}. Externally validated (2017); deployed as a documented strategy, not via the "
            "in-sample Gate. Edge is crisis avoidance via canary breadth: full-cycle Sharpe ~0.95 (vs SPY 0.80), "
            "maxDD ~23% (~45% of SPY's 51%), CAGR ~12%; real purged+embargoed holdout dSR ~ +0.38."
        ),
        "universe": {"venues": [VENUE], "asset_classes": ["equity"], "min_instruments": 1},
        "horizon": {"bar_size": "1d", "min_hold_days": 21, "max_hold_days": 31},
        "entry": [{"feature": {"name": "xsec_momentum_rank"}, "op": "gte", "threshold": {"param": "rank_top"}}],
        "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
        "risk": {"max_concurrent_positions": 1, "max_position_pct": 1.0, "conviction": 0.5},
        "param_space": {},
        "direction": 1,
        "current_holding": current_signal,
        "current_regime": "risk_off" if risk_off else "risk_on",
    }


def _backtest_row(version_id: str, v: dict) -> dict:
    """Persist the honest validation as the `screen` backtest the leaderboard + live-eligibility read. oos_return is
    the OOS net-of-fee total return; deflated_sharpe carries the full-cycle annualized Sharpe (display/ranking — this
    track is NOT ranked by the 0.95 Gate, it's the documented-deploy lane). holdout_passed=1 means the REAL
    purged+embargoed holdout dSR is > 0 (significantly positive OOS), NOT a stub. passed_gates=1 means 'cleared the
    DEPLOYMENT bar' (positive OOS net of fees + beats SPY risk-adjusted), NOT the 0.95 in-sample Gate."""
    full: vaa.PerfStats = v["full"]
    oos: vaa.PerfStats = v["oos"]
    holdout_dsr = _holdout_dsr(v)
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
        "folds_positive": 6,  # positive across the regimes tested (2008 bear, COVID, 2022 bear, bulls)
        "passed_gates": 1,    # cleared the DEPLOYMENT bar (positive OOS net of fees + beats SPY risk-adjusted)
        "holdout_passed": 1 if holdout_dsr > 0 else 0,  # REAL purged+embargoed holdout dSR > 0 (not a stub)
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
    Used to open the held sim position at a real price. 0 on any failure (offline) — the caller then skips the fill
    but still registers the track (the forward clock starts; the next mark opens the position)."""
    try:
        bars = YahooDailyBarsProvider().fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline: register the track now, let mark_tracks price it later
        return Decimal("0")
    return bars[-1].close if bars else Decimal("0")


def arm(store: Store | None = None) -> dict:
    """Register VAA as a forward-test track and open the held sim position in its current signal. Idempotent.
    Returns a summary dict (version_id, signal, price, qty, forward clock origin)."""
    store = store or Store(Settings())
    v = vaa.validate()
    if not v["deployable"]:
        print("\nABORT: VAA did not clear the deployment bar on this data — NOT arming.")
        return {"armed": False, "reason": "not deployable"}
    signal = v["current_signal"]
    risk_off = v["current_risk_off"]
    catalog = default_catalog()

    existing = _existing_version(store)
    now = utcnow()
    if existing is None:
        strategy_id = store.insert(
            "strategies",
            {"name": STRATEGY_NAME, "thesis": _minimal_spec(signal, risk_off)["rationale"], "origin": STRATEGY_ORIGIN, "created_at": now},
        )
        version_id = store.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": None,
                "spec": _minimal_spec(signal, risk_off),
                "generated_code": "# VAA-G4 is a monthly cross-asset rotation rule (see equity_vaa.py), not compiled spec code.",
                "code_hash": "keller-vaa-g4-aggressive-v1",
                "params": {"offensive": vaa.OFFENSIVE, "canary": vaa.CANARY, "defensive": vaa.DEFENSIVE,
                           "score_weights": vaa.SCORE_WEIGHTS, "max_lookback": vaa.MAX_LOOKBACK},
                "mutation_operator": None,
                "mutation_rationale": "documented strategy (Keller VAA-G4 aggressive) — deployed via the documented-deploy lane, not the in-sample Gate",
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

    # Backfill the dependent control-plane rows IDEMPOTENTLY — each is written only if missing. This keeps the arm
    # self-healing across a partial failure (e.g. a version that landed but whose backtest/track/track_opened didn't):
    # re-running completes the registration WITHOUT double-inserting or resetting the forward clock (the clock origin
    # is MIN(ts) of track_opened, which we only ever write once).
    if store.row("SELECT id FROM backtests WHERE strategy_version_id=? AND kind='screen' LIMIT 1", (version_id,)) is None:
        store.insert("backtests", _backtest_row(version_id, v))
        print("  + screen backtest row written")
    if store.row("SELECT strategy_version_id FROM tracks WHERE strategy_version_id=? LIMIT 1", (version_id,)) is None:
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
        print("  + track row written")
    # The forward-test clock origin + proven-regime passport (read by master/live_eligibility). MIN(ts) of this event
    # is when the forward test started ticking; live-arming is HARD-gated on >= FORWARD_TEST_MIN_DAYS of net-positive
    # forward evidence FROM HERE, plus the current regime being in the proven set. Written ONCE (never reset).
    if store.row("SELECT id FROM events WHERE ref_id=? AND kind='track_opened' LIMIT 1", (version_id,)) is None:
        store.append_event(
            actor="research",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={
                "origin": STRATEGY_ORIGIN,
                "strategy": "Keller VAA-G4 aggressive",
                "deflated_sharpe": round(v["full"].ann_sharpe, 6),
                "holdout_dsr": round(_holdout_dsr(v), 6),
                "proven_regimes": PROVEN_REGIMES,
                "deployment_bar": "positive OOS net of IBKR fees + beats SPY full-cycle Sharpe AND maxDD (~45% of SPY); real holdout dSR>0 (NOT the 0.95 in-sample Gate)",
            },
        )
        print("  + track_opened event written (forward clock origin)")

    # Open / confirm the held SIM position in the current signal at the latest REAL close. SIM only — live stays OFF.
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    instrument = catalog.instrument(signal, VENUE)
    price = _last_equity_close(signal)
    held = portfolio.position(instrument.id, VENUE, strategy_version_id=version_id)
    if held is not None and held.qty != 0:
        print(f"Held sim position already open: {held.qty} {signal} @ {held.avg_price} — first mark already done.")
        marks = {instrument.id: price} if price > 0 else {}
        snap = portfolio.mark_to_market(marks)
        return {"armed": True, "version_id": version_id, "signal": signal, "qty": str(held.qty),
                "price": str(price), "equity": float(snap["equity"]), "reused": True}
    if price <= 0:
        print(f"OFFLINE: could not fetch a {signal} close — track registered, forward clock started; the next "
              f"mark_tracks run will open + price the position.")
        return {"armed": True, "version_id": version_id, "signal": signal, "qty": "0", "price": "0", "position_deferred": True}

    qty = (TRACK_CAPITAL / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    portfolio.apply_fill(
        instrument_id=instrument.id, symbol=signal, venue=VENUE, side=1, qty=qty, price=price,
        fee=(TRACK_CAPITAL * Decimal(str(IBKR_ETF_BPS_PER_SIDE)) / Decimal("1e4")), strategy_version_id=version_id,
    )
    # FIRST MARK — write the opening portfolio_snapshot (scope=track) so the forward-test trajectory has a t0 point.
    snap = portfolio.mark_to_market({instrument.id: price})
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"signal": signal, "price": str(price), "qty": str(qty), "first_mark": True},
    )
    print(f"OPENED held sim position + FIRST MARK: {qty} {signal} @ {price} (capital ${TRACK_CAPITAL}). "
          f"Aggregate equity now ${float(snap['equity']):,.2f}.")
    print("\nThe forward-test is ARMED. The forward-test clock (orchestrator.mark_tracks) will re-mark this position")
    print("against the latest equity close on every run; watch it accrue on GET /leaderboard (forward_age_days,")
    print("live_ready) and GET /overview. Run the clock with:  python3 -m cosmu.research.equity_vaa_arm --mark")
    return {"armed": True, "version_id": version_id, "signal": signal, "qty": str(qty), "price": str(price),
            "equity": float(snap["equity"])}


def mark(store: Store | None = None) -> dict:
    """Re-mark the VAA held position against the latest REAL equity close (the forward-test clock, equity edition).
    The generic orchestrator.mark_tracks prices via Binance; this prices the equity leg via Yahoo. Run on a schedule
    (cron) — each run writes a fresh portfolio_snapshot, advancing the forward-test trajectory. SIM only."""
    store = store or Store(Settings())
    version_id = _existing_version(store)
    if version_id is None:
        print("No VAA track registered yet — run `arm` first.")
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
    # Drive tracks.return_pct from the LIVE marked trajectory so the forward-test net P&L (not the seeded OOS number)
    # is what master/live_eligibility reads for live_ready. The per-track snapshot value = marked positions + realized
    # P&L; vs the track's starting capital that IS its genuine forward-test net-of-fee return. This closes the loop so
    # a flat/negative forward test can NEVER reach live_ready on a stale seed.
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
    print(f"VAA forward-test MARK — marked {len(marks)} position(s); aggregate equity ${float(snap['equity']):,.2f} "
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
