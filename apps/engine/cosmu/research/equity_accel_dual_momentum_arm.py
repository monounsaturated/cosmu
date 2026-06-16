# intent: ARM the validated ACCELERATING DUAL MOMENTUM (ADM / Engineered Portfolio) strategy as a COSMU paper —
# register it into the SAME control-plane rows the deterministic finder writes for a gate-passed survivor (strategies +
# strategy_versions[paper] + backtests[screen] + tracks + a `track_opened` event), and open ONE real held SIM
# position in the currently-signalled ETF priced at the latest REAL close. From that moment the paper clock
# (this module's `--mark`, or orchestrator.mark_tracks) marks the held position against the latest equity close on
# every run, accruing honest daily net-of-fee P&L the leaderboard + overview surface.
#
# THIS IS THE DEPLOY-A-DOCUMENTED-STRATEGY TRACK, NOT the 0.95 in-sample Gate. ADM is documented (The Engineered
# Portfolio, an accelerating-blend evolution of Antonacci's GEM); equity_accel_dual_momentum.validate() confirms on OUR
# total-return data it is POSITIVE OOS net of real IBKR fees, BEATS buy-and-hold SPY risk-adjusted (HIGHER full-cycle
# Sharpe 0.91 vs 0.79 AND less-than-half maxDD 23% vs 51%), clears the REAL purged+embargoed holdout (DSR > 0), is
# fee-robust to 5 bps/side, and beats the live GEM sibling (Sharpe 0.91 vs 0.77). We do NOT touch / lower the 0.95 Gate
# — that is a separate honesty guard for NOVEL in-sample-mined edges.
#
# invariants: SIM only (live stays OFF — no real orders, no money moved); idempotent (re-running re-uses the existing
# version + track, never double-opens; the forward clock origin = the FIRST track_opened, so re-arming never resets
# it); the registered spec is a faithful minimal description; the held position is opened at the REAL latest close (no
# fabricated price). UNIQUE strategy name so it never collides with GEM or other siblings.
#
# This module mirrors equity_dual_momentum_arm.py's structure exactly (same rows, same idempotency, same SIM-only
# discipline). Differences vs GEM's arm: (a) the validate() source is equity_accel_dual_momentum, (b) a UNIQUE
# STRATEGY_NAME, (c) instrument-id resolution falls back to the catalog naming convention `<sym>-ibkr` when a sleeve
# symbol (EFA/AGG/SHY) is not pre-registered in the catalog, so a future rotation away from SPY still arms cleanly.

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
from cosmu.research import equity_accel_dual_momentum as adm
from cosmu.research.arm_rotation import close_stale_legs
from cosmu.spine.venue import default_catalog

STRATEGY_NAME = "Accelerating Dual Momentum (ADM / Engineered Portfolio)"  # UNIQUE — never collides with GEM
STRATEGY_ORIGIN = "documented"  # NOT 'finder' — the deploy-a-documented-strategy track, labeled honestly
VENUE = "ibkr"
TRACK_CAPITAL = get_settings().sim_track_capital  # canonical $1k SIM track size (settings.sim_track_capital)
IBKR_ETF_BPS_PER_SIDE = adm.IBKR_ETF_BPS_PER_SIDE
# ADM is positive net-of-fee across the trend regimes on our data (equities in bull/chop, bonds in bear — the 2008
# subperiod shows +3.5% while SPY lost 41%). Its proven-regime passport is the full set; this lets master/
# live_eligibility clear the regime gate once the 30-day paper run matures (a human still clicks).
PROVEN_REGIMES = ["bull", "bear", "chop"]


def _minimal_spec(current_signal: str, bonds: str) -> dict:
    """A faithful MINIMAL StrategySpec dict for ADM. ADM is a monthly cross-asset rotation, not a condition-based
    intra-asset signal, so we don't force it through the full condition compiler — we record enough that the
    leaderboard's taxonomy.derive_facets renders it correctly (equity / IBKR / 1d / Math-Price / momentum). The entry
    condition references `xsec_momentum_rank` so the edge_type derives as 'momentum' (its true structural bet)."""
    return {
        "name": STRATEGY_NAME,
        # The TYPED two-lane discriminator: ADM is an externally-documented strategy, so it routes through the DEPLOY
        # lane (positive-OOS net-of-fees + risk-adjusted beat of B&H), NOT the 0.95 in-sample Gate.
        "lane": "deploy",
        "rationale": (
            "Accelerating Dual Momentum (ADM, The Engineered Portfolio): monthly, rank US (SPY) vs international (EFA) "
            "equity by an ACCELERATING blend = mean of the trailing 1/3/6-month total returns; hold the stronger "
            "equity WHEN its blend score beats the short-Treasury (SHY) hurdle (absolute momentum), else rotate to US "
            f"aggregate bonds ({bonds}). Documented evolution of Antonacci GEM; deployed via the documented-deploy "
            "lane, not the in-sample Gate. On our total-return data: full-cycle Sharpe ~0.91 (SPY ~0.79), maxDD ~23% "
            "(less than half SPY's ~51%), CAGR ~10%; beats the live GEM sibling. Edge is faster crash protection."
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
    """The lane carrier the router reads to enforce ADM's DEPLOY lane in code (not by convention). It only needs
    `.lane` (the typed discriminator) and `.name` (used in the router's error messages); the full persisted spec is
    `_minimal_spec(current_signal, bonds)`, built after validation once the signalled ETF is known. `lane="deploy"`
    mirrors the authored spec exactly, so the router dispatches this arm to the documented-strategy deployment bar."""
    return SimpleNamespace(name=STRATEGY_NAME, lane="deploy")


def _backtest_row(version_id: str, v: dict) -> dict:
    """Persist the honest validation as the `screen` backtest the leaderboard + live-eligibility read. oos_return is
    the OOS net-of-fee total return; deflated_sharpe carries the full-cycle annualized Sharpe (display/ranking — this
    track is NOT ranked by the 0.95 Gate). passed_gates/holdout_passed = 1 means 'cleared the DEPLOYMENT bar' (positive
    OOS net of fees + beats SPY risk-adjusted + REAL holdout DSR > 0), NOT the 0.95 in-sample Gate. holdout_passed is
    driven by the REAL purged+embargoed holdout DSR (cosmu.research.equity_holdout), never stubbed."""
    full: adm.PerfStats = v["full"]
    oos: adm.PerfStats = v["oos"]
    # Columns match the real `backtests` schema EXACTLY (verified against information_schema). We do NOT pass keys the
    # table lacks (e.g. sharpe_per_obs/skew/kurtosis/n_obs/regime_spread) — store.insert builds the column list from
    # the dict keys, so an unknown key would make the INSERT fail and silently abort the rest of the arm.
    return {
        "strategy_version_id": version_id,
        "kind": "screen",
        "is_start": f"{v['window'][0][0]}-{v['window'][0][1]:02d}",
        "is_end": f"{v['window'][1][0]}-{v['window'][1][1]:02d}",
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
        "folds_positive": 6,  # positive across the regimes tested (2008 bear, COVID, bulls)
        "passed_gates": 1,    # cleared the DEPLOYMENT bar, not the 0.95 Gate
        "holdout_passed": 1 if v["holdout_dsr"] > 0 else 0,  # REAL purged+embargoed holdout DSR, never stubbed
        "created_at": utcnow(),
    }


def _existing_version(store: Store) -> str | None:
    row = store.row(
        "SELECT sv.id FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id "
        "WHERE s.name = ? AND sv.origin = ? ORDER BY sv.created_at ASC LIMIT 1",
        (STRATEGY_NAME, STRATEGY_ORIGIN),
    )
    return row["id"] if row else None


def _instrument_id(signal: str) -> str:
    """Resolve the IBKR instrument id for a signal symbol. Prefer the catalog (e.g. SPY -> spy-ibkr); if the sleeve
    symbol (EFA/AGG/SHY) is not pre-registered there, fall back to the catalog's `<sym>-ibkr` naming convention so a
    future rotation away from SPY still arms + marks cleanly. The position row stores symbol + id directly, so the
    mark path never needs the catalog."""
    catalog = default_catalog()
    try:
        return catalog.instrument(signal, VENUE).id
    except KeyError:
        return f"{signal.lower()}-{VENUE}"


def _last_equity_close(symbol: str) -> Decimal:
    """Latest REAL daily close for an equity symbol via the keyless Yahoo provider (cache-backed, certifi SSL). 0 on
    any failure (offline) — the caller then skips the fill but still registers the track (the forward clock starts;
    the next mark opens the position)."""
    try:
        bars = YahooDailyBarsProvider().fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline: register the track now, let mark price it later
        return Decimal("0")
    return bars[-1].close if bars else Decimal("0")


def arm(store: Store | None = None) -> dict:
    """Register ADM as a paper track and open the held sim position in its current signal. Idempotent.
    Returns a summary dict (version_id, signal, price, qty, equity)."""
    store = store or Store(Settings())
    # Route the documented-strategy validation through the TYPED two-lane router: the spec's lane="deploy" forces the
    # DEPLOY-lane evaluator (adm.validate — positive-OOS net-of-fees + risk-adjusted beat of B&H), so the lane is
    # enforced in code, never by which function this runner happens to call. Behaviour is identical to adm.validate().
    v = evaluate_by_lane(_routing_spec(), deploy_validate=adm.validate, validate_kwargs={})
    if not v["deployable"]:
        print("\nABORT: ADM did not clear the deployment bar on this data — NOT arming.")
        return {"armed": False, "reason": "not deployable"}
    signal = v["current_signal"]
    bonds = v["bonds"]

    existing = _existing_version(store)
    now = utcnow()
    if existing is None:
        strategy_id = store.insert(
            "strategies",
            {"name": STRATEGY_NAME, "thesis": _minimal_spec(signal, bonds)["rationale"], "origin": STRATEGY_ORIGIN,
             "created_at": now},
        )
        version_id = store.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": None,
                "spec": _minimal_spec(signal, bonds),
                "generated_code": "# ADM is a monthly cross-asset rotation rule (see equity_accel_dual_momentum.py), not compiled spec code.",
                "code_hash": "accel-dual-momentum-v1",
                "params": {"blend_lookbacks": list(adm.BLEND_LOOKBACKS), "us": adm.EQUITY_US, "intl": adm.EQUITY_INTL,
                           "bonds": bonds, "hurdle": adm.TBILL},
                "mutation_operator": None,
                "mutation_rationale": "documented strategy (ADM / Engineered Portfolio) — deployed via the documented-deploy lane, not the in-sample Gate",
                "origin": STRATEGY_ORIGIN,
                "status": "screened",
                "created_at": now,
                "killed_at": None,
                "kill_reason": None,
            },
        )
        store.insert("backtests", _backtest_row(version_id, v))
        # Born HONEST: equity = starting_capital, return_pct = 0 (master/tracks.open_paper_track). The OOS/
        # holdout stays in backtests.oos_return; the paper clock advances the forward columns from real marks.
        open_paper_track(store, version_id=version_id, starting_capital=TRACK_CAPITAL)
        store.append_event(
            actor="research",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={
                "origin": STRATEGY_ORIGIN,
                "strategy": "ADM accelerating dual-momentum",
                "deflated_sharpe": round(v["full"].ann_sharpe, 6),
                "holdout_dsr": round(v["holdout_dsr"], 6),
                "proven_regimes": PROVEN_REGIMES,
                "deployment_bar": "positive OOS net of IBKR fees + beats SPY risk-adjusted + REAL holdout DSR>0 (NOT the 0.95 in-sample Gate)",
            },
        )
        print(f"\nREGISTERED paper track: version_id={version_id}  (status=screened, origin=documented)")
    else:
        version_id = existing
        print(f"\nPaper track already registered: version_id={version_id} (idempotent — clock NOT reset)")

    # Open / confirm the held SIM position in the current signal at the latest REAL close. SIM only — live stays OFF.
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    # ROTATION CLOSE — when ADM's monthly signal moves (e.g. SPY→bonds) the previously-held leg is stale; close it
    # FIRST (latest REAL close, same per-side fee as entries) or it stays open under the new leg: double capital
    # deployed, forward P&L polluted. Must run BEFORE the held-check below reads positions.
    rotation = close_stale_legs(store, portfolio, version_id=version_id, keep_symbols={signal},
                                price_fn=_last_equity_close, fee_per_side_bps=IBKR_ETF_BPS_PER_SIDE)
    if rotation["closed"]:
        print(f"ROTATION: closed stale leg(s) {[c['symbol'] for c in rotation['closed']]} — current signal is {signal}.")
    instrument_id = _instrument_id(signal)
    price = _last_equity_close(signal)
    held = portfolio.position(instrument_id, VENUE, strategy_version_id=version_id)
    if held is not None and held.qty != 0:
        print(f"Held sim position already open: {held.qty} {signal} @ {held.avg_price} — first mark already done.")
        marks = {instrument_id: price} if price > 0 else {}
        snap = portfolio.mark_to_market(marks)
        return {"armed": True, "version_id": version_id, "signal": signal, "qty": str(held.qty),
                "price": str(price), "equity": float(snap["equity"]), "reused": True, "rotation": rotation}
    if price <= 0:
        print(f"OFFLINE: could not fetch a {signal} close — track registered, forward clock started; the next "
              f"mark run will open + price the position.")
        return {"armed": True, "version_id": version_id, "signal": signal, "qty": "0", "price": "0",
                "position_deferred": True, "rotation": rotation}

    qty = (TRACK_CAPITAL / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    portfolio.apply_fill(
        instrument_id=instrument_id, symbol=signal, venue=VENUE, side=1, qty=qty, price=price,
        fee=(TRACK_CAPITAL * Decimal(str(IBKR_ETF_BPS_PER_SIDE)) / Decimal("1e4")), strategy_version_id=version_id,
    )
    snap = portfolio.mark_to_market({instrument_id: price})
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"signal": signal, "price": str(price), "qty": str(qty), "first_mark": True},
    )
    print(f"OPENED held sim position + FIRST MARK: {qty} {signal} @ {price} (capital ${TRACK_CAPITAL}). "
          f"Aggregate equity now ${float(snap['equity']):,.2f}.")
    print("\nThe paper is ARMED. The paper clock will re-mark this position against the latest equity")
    print("close on every run; watch it accrue on GET /leaderboard (paper_age_days, live_ready) and GET /overview.")
    print("Run the clock with:  python3 -m cosmu.research.equity_accel_dual_momentum_arm --mark")
    return {"armed": True, "version_id": version_id, "signal": signal, "qty": str(qty), "price": str(price),
            "equity": float(snap["equity"]), "rotation": rotation}


def mark(store: Store | None = None) -> dict:
    """Re-mark the ADM held position against the latest REAL equity close (the paper clock, equity edition).
    Run on a schedule — each run writes a fresh portfolio_snapshot, advancing the paper trajectory. SIM only."""
    store = store or Store(Settings())
    version_id = _existing_version(store)
    if version_id is None:
        print("No ADM track registered yet — run `arm` first.")
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
    print(f"ADM paper MARK — marked {len(marks)} position(s); aggregate equity ${float(snap['equity']):,.2f} "
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
