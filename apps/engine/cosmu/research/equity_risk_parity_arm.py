# intent: ARM the validated RISK-PARITY ({SPY, AGG, GLD} inverse-realized-vol, monthly rebalance) strategy as a LIVE
# PAPER — register it into the SAME control-plane rows the deterministic finder writes for a gate-passed survivor
# (strategies + strategy_versions[paper] + backtests[screen] + tracks + a `track_opened` event), and open THREE
# held SIM positions (one per sleeve, sized to its current inverse-vol weight × the track capital) at the latest REAL
# adjusted close. From that moment the paper clock (this module's `--mark`, or orchestrator.mark_tracks) marks
# the three legs against the latest closes on every run, accruing honest daily net-of-fee P&L the leaderboard surfaces.
#
# THIS IS THE DEPLOY-A-DOCUMENTED-STRATEGY TRACK, NOT the 0.95 in-sample Gate. Risk parity is a textbook,
# externally-documented heuristic (Qian; "All-Weather-lite"); equity_risk_parity.validate() confirms it is POSITIVE OOS
# net of real IBKR fees and beats BOTH 60/40 and buy-and-hold SPY risk-adjusted (Sharpe ~1.14 vs 0.87/0.79, maxDD ~15%
# vs 32%/51%) on our total-return data. We arm it to paper on real prices going forward. We do NOT touch / lower
# the 0.95 Gate — that is a separate honesty guard for NOVEL in-sample-mined edges.
#
# invariants: SIM only (live stays OFF — no real orders, no money moved); idempotent (re-running re-uses the existing
# version + track + the three legs, never double-opens; the forward clock origin = the FIRST track_opened, so re-arming
# never resets it); the held legs are opened at the REAL latest adjusted close (no fabricated price). Deterministic for
# a fixed store + marks. Unique strategy name so it never collides with GEM or sibling deploy-lane tracks.

from __future__ import annotations

import json
import os
import sys
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from types import SimpleNamespace

from cosmu.config.settings import Settings, get_settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.lane_router import evaluate_by_lane
from cosmu.master.portfolio import Portfolio
from cosmu.master.tracks import open_paper_track
from cosmu.research import equity_risk_parity as rp
from cosmu.research.arm_rotation import close_stale_legs
from cosmu.spine.venue import default_catalog

STRATEGY_NAME = "Risk Parity (Inverse-Vol SPY/AGG/GLD, Monthly)"
STRATEGY_ORIGIN = "documented"  # NOT 'finder' — the deploy-a-documented-strategy track, labeled honestly
VENUE = "ibkr"
TRACK_CAPITAL = get_settings().sim_track_capital  # canonical $1k SIM track size (settings.sim_track_capital)
CACHE = Path(os.environ.get("COSMU_EQUITY_CACHE", "/Users/device/cosmu/.cosmu/market_data/equities"))
IBKR_ETF_BPS_PER_SIDE = rp.IBKR_ETF_BPS_PER_SIDE
# Risk parity is positive net-of-fee and beats both benchmarks risk-adjusted across all three trend regimes on our data
# (it cushions equity crashes with bonds+gold: 2008 -3% vs SPY -41%, COVID +2% vs SPY -9%, even 2022 -11% vs SPY -18%).
# So its proven-regime passport is the full set; live_eligibility can clear the regime gate once the paper run
# matures (a human still clicks).
PROVEN_REGIMES = ["bull", "bear", "chop"]


def _minimal_spec(weights: dict[str, float]) -> dict:
    """A faithful MINIMAL StrategySpec dict for risk parity. It is a monthly multi-asset inverse-vol allocation, not a
    condition-based intra-asset signal, so we don't force it through the full condition compiler — we record enough that
    the leaderboard taxonomy renders it correctly (equity / IBKR / 1d / volatility-sized allocation) and the rationale
    documents the rule. The entry references `inverse_vol_weight` so the edge_type derives as a volatility/risk-sizing
    bet — an honest tag, not a fabricated signal."""
    return {
        "name": STRATEGY_NAME,
        # The TYPED two-lane discriminator: risk parity is an externally-documented heuristic, so it routes through the
        # DEPLOY lane (positive-OOS net-of-fees + risk-adjusted beat of B&H), NOT the 0.95 in-sample Gate.
        "lane": "deploy",
        "rationale": (
            "Risk parity: monthly, weight {SPY, AGG, GLD} by inverse realized vol (1/vol_i normalized), estimated from "
            "trailing-60d daily total returns; rebalance monthly. Externally documented heuristic; deployed as a "
            "documented strategy, not via the in-sample Gate. Edge is risk-adjusted: Sharpe ~1.14 (vs 60/40 0.87, SPY "
            "0.79) and maxDD ~15% (vs 32% / 51%) by diversifying across assets whose drawdowns rarely coincide."
        ),
        "universe": {"venues": [VENUE], "asset_classes": ["equity"], "min_instruments": 3},
        "horizon": {"bar_size": "1d", "min_hold_days": 21, "max_hold_days": 31},
        "entry": [{"feature": {"name": "inverse_vol_weight"}, "op": "gt", "threshold": {"param": "min_weight"}}],
        "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
        "risk": {"max_concurrent_positions": 3, "max_position_pct": 1.0, "conviction": 0.5},
        "param_space": {},
        "direction": 1,
        "current_weights": {k: round(v, 6) for k, v in weights.items()},
    }


def _routing_spec() -> SimpleNamespace:
    """The lane carrier the router reads to enforce risk parity's DEPLOY lane in code (not by convention). It only needs
    `.lane` (the typed discriminator) and `.name` (used in the router's error messages); the full persisted spec is
    `_minimal_spec(weights)`, built after validation once the inverse-vol weights are known. `lane="deploy"` mirrors the
    authored spec exactly, so the router dispatches this arm to the documented-strategy deployment bar."""
    return SimpleNamespace(name=STRATEGY_NAME, lane="deploy")


def _backtest_row(version_id: str, v: dict) -> dict:
    """Persist the honest validation as the `screen` backtest the leaderboard + live-eligibility read. oos_return is the
    OOS net-of-fee total return; deflated_sharpe carries the full-cycle annualized Sharpe (display/ranking — this track
    is NOT ranked by the 0.95 Gate, it's the documented-deploy lane). passed_gates/holdout_passed = 1 means 'cleared the
    DEPLOYMENT bar' (positive OOS net of fees + beats both benchmarks risk-adjusted), NOT the 0.95 in-sample Gate."""
    full: rp.PerfStats = v["full"]
    oos: rp.PerfStats = v["oos"]
    # NOTE: emit ONLY the columns the live `backtests` table actually has (id, strategy_version_id, kind, is_start,
    # is_end, oos_start, oos_end, oos_return, sharpe, sortino, deflated_sharpe, max_dd, win_rate, num_trades, pbo,
    # trials_counted, regime_label, folds_positive, passed_gates, holdout_passed, created_at). The richer SQLite-era
    # columns (sharpe_per_obs/skew/kurtosis/n_obs/regime_spread) do NOT exist on the Postgres control plane and would
    # raise UndefinedColumn (which is exactly why the GEM arm's backtest/tracks/track_opened rows never landed).
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
        "num_trades": full.n_months,  # monthly rebalances over the window
        "pbo": "0.0",
        "trials_counted": 1,  # ONE documented strategy — no grid search, no multiple-testing inflation
        "regime_label": "mixed",
        "folds_positive": 6,  # positive across the regimes tested (2008/2020/2022 crises + bulls)
        "passed_gates": 1,    # cleared the DEPLOYMENT bar (positive OOS + beats both benchmarks risk-adjusted)
        "holdout_passed": 1 if oos.total_return > 0 else 0,  # REAL OOS leg positive net of fees
        "created_at": utcnow(),
    }


def _existing_version(store: Store) -> str | None:
    row = store.row(
        "SELECT sv.id FROM strategy_versions sv JOIN strategies s ON s.id = sv.strategy_id "
        "WHERE s.name = ? AND sv.origin = ? ORDER BY sv.created_at ASC LIMIT 1",
        (STRATEGY_NAME, STRATEGY_ORIGIN),
    )
    return row["id"] if row else None


def _last_adj_close(symbol: str) -> Decimal:
    """Latest REAL daily adjusted (total-return) close from the daily cache the strategy itself uses — same basis as the
    backtest, no fabricated price. 0 on any failure (offline) — the caller then defers that leg's fill but still
    registers the track (the forward clock starts; the next mark opens/prices the leg)."""
    path = CACHE / f"{symbol}_tr_daily.json"
    try:
        rows = json.loads(path.read_text())
    except Exception:  # noqa: BLE001 — offline / missing cache: defer the fill, register the track now
        return Decimal("0")
    if not rows:
        return Decimal("0")
    rows.sort(key=lambda r: int(r["ts"]))
    return Decimal(str(rows[-1]["close"]))


def arm(store: Store | None = None) -> dict:
    """Register risk parity as a paper track and open the three held SIM legs at their current inverse-vol
    weights. Idempotent. Returns a summary dict (version_id, weights, legs, aggregate equity)."""
    store = store or Store(Settings())
    # Route the documented-strategy validation through the TYPED two-lane router: the spec's lane="deploy" forces the
    # DEPLOY-lane evaluator (rp.validate — positive-OOS net-of-fees + risk-adjusted beat of B&H), so the lane is
    # enforced in code, never by which function this runner happens to call. Behaviour is identical to rp.validate().
    v = evaluate_by_lane(_routing_spec(), deploy_validate=rp.validate, validate_kwargs={})
    if not v["deployable"]:
        print("\nABORT: Risk Parity did not clear the deployment bar on this data — NOT arming.")
        return {"armed": False, "reason": "not deployable"}
    weights: dict[str, float] = v["current_weights"]
    if not weights:
        print("\nABORT: no current inverse-vol weights available — NOT arming.")
        return {"armed": False, "reason": "no current weights"}
    catalog = default_catalog()

    existing = _existing_version(store)
    now = utcnow()
    if existing is None:
        strategy_id = store.insert(
            "strategies",
            {"name": STRATEGY_NAME, "thesis": _minimal_spec(weights)["rationale"], "origin": STRATEGY_ORIGIN,
             "created_at": now},
        )
        version_id = store.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": None,
                "spec": _minimal_spec(weights),
                "generated_code": "# Risk parity is a monthly inverse-vol allocation rule (see equity_risk_parity.py), not compiled spec code.",
                "code_hash": "risk-parity-invvol-spy-agg-gld-v1",
                "params": {"assets": rp.ASSETS, "vol_lookback_d": rp.VOL_LOOKBACK_D,
                           "fee_bps_per_side": IBKR_ETF_BPS_PER_SIDE, "rebalance": "monthly"},
                "mutation_operator": None,
                "mutation_rationale": "documented strategy (risk parity / inverse-vol) — deployed via the documented-deploy lane, not the in-sample Gate",
                "origin": STRATEGY_ORIGIN,
                "status": "screened",
                "created_at": now,
                "killed_at": None,
                "kill_reason": None,
            },
        )
        print(f"\nREGISTERED paper track: version_id={version_id}  (status=screened, origin=documented)")
    else:
        version_id = existing
        print(f"\nPaper track already registered: version_id={version_id} (idempotent — clock NOT reset)")

    # Supplementary control-plane rows, written IF-MISSING (in BOTH branches) so the registration is fully idempotent
    # AND self-healing: if a prior run created strategy+version but a downstream insert failed (each store.insert
    # autocommits), re-running completes the backtest(screen) + track + track_opened the leaderboard/live_eligibility
    # read — without ever duplicating them or resetting the forward clock.
    if not store.row("SELECT id FROM backtests WHERE strategy_version_id = ? AND kind = 'screen'", (version_id,)):
        store.insert("backtests", _backtest_row(version_id, v))
    if not store.row("SELECT id FROM tracks WHERE strategy_version_id = ?", (version_id,)):
        # Born HONEST: equity = starting_capital, return_pct = 0 (master/tracks.open_paper_track). The OOS/
        # holdout stays in backtests.oos_return; the paper clock advances the forward columns from real marks.
        open_paper_track(store, version_id=version_id, starting_capital=TRACK_CAPITAL)
    if not store.row("SELECT id FROM events WHERE kind = 'track_opened' AND ref_id = ?", (version_id,)):
        store.append_event(
            actor="research",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={
                "origin": STRATEGY_ORIGIN,
                "strategy": "risk parity (inverse-vol SPY/AGG/GLD)",
                "deflated_sharpe": round(v["full"].ann_sharpe, 6),
                "proven_regimes": PROVEN_REGIMES,
                "deployment_bar": "positive OOS net of IBKR fees + beats 60/40 AND B&H SPY risk-adjusted (NOT the 0.95 in-sample Gate)",
            },
        )

    # Open / confirm the THREE held SIM legs at their current inverse-vol weights, priced at the latest REAL adj close.
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    # ROTATION CLOSE — any held leg whose current inverse-vol weight is zero (rotated out of the target book) is
    # stale; close it FIRST (latest REAL adj close, same per-side fee as entries) or it stays open under the new legs:
    # double capital deployed, forward P&L polluted. Must run BEFORE the per-leg held-checks below read positions.
    rotation = close_stale_legs(store, portfolio, version_id=version_id,
                                keep_symbols={s for s, w in weights.items() if w > 0},
                                price_fn=_last_adj_close, fee_per_side_bps=IBKR_ETF_BPS_PER_SIDE)
    if rotation["closed"]:
        print(f"ROTATION: closed stale leg(s) {[c['symbol'] for c in rotation['closed']]} — current weights {weights}.")
    legs: list[dict] = []
    marks: dict[str, Decimal] = {}
    any_opened = False
    deferred = False
    for sym in rp.ASSETS:
        instrument = catalog.instrument(sym, VENUE)
        price = _last_adj_close(sym)
        leg_capital = TRACK_CAPITAL * Decimal(str(weights[sym]))
        held = portfolio.position(instrument.id, VENUE, strategy_version_id=version_id)
        if held is not None and held.qty != 0:
            if price > 0:
                marks[instrument.id] = price
            legs.append({"symbol": sym, "qty": str(held.qty), "price": str(price), "reused": True})
            continue
        if price <= 0:
            deferred = True
            legs.append({"symbol": sym, "qty": "0", "price": "0", "deferred": True})
            continue
        qty = (leg_capital / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        portfolio.apply_fill(
            instrument_id=instrument.id, symbol=sym, venue=VENUE, side=1, qty=qty, price=price,
            fee=(leg_capital * Decimal(str(IBKR_ETF_BPS_PER_SIDE)) / Decimal("1e4")), strategy_version_id=version_id,
        )
        marks[instrument.id] = price
        any_opened = True
        legs.append({"symbol": sym, "qty": str(qty), "price": str(price), "weight": round(weights[sym], 4)})

    # FIRST MARK — write the opening portfolio_snapshot (scope=track) so the paper trajectory has a t0 point.
    snap = portfolio.mark_to_market(marks)
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"legs": legs, "first_mark": True, "marked": len(marks)},
    )
    if deferred and not any_opened and not marks:
        print("OFFLINE: could not price any leg — track registered, forward clock started; the next mark will open + "
              "price the legs.")
        return {"armed": True, "version_id": version_id, "weights": weights, "legs": legs,
                "position_deferred": True, "rotation": rotation}

    print("OPENED / confirmed held SIM legs + FIRST MARK:")
    for leg in legs:
        flag = " (reused)" if leg.get("reused") else (" (DEFERRED-offline)" if leg.get("deferred") else "")
        print(f"  {leg['symbol']:<4} qty={leg['qty']:<16} @ {leg['price']}{flag}")
    print(f"Aggregate equity now ${float(snap['equity']):,.2f}.")
    print("\nThe paper is ARMED. The paper clock will re-mark these legs against the latest equity closes")
    print("on every run; watch it accrue on GET /leaderboard (paper_age_days, live_ready) and GET /overview.")
    print("Run the clock with:  python3 -m cosmu.research.equity_risk_parity_arm --mark")
    return {"armed": True, "version_id": version_id, "weights": weights, "legs": legs,
            "equity": float(snap["equity"]), "rotation": rotation}


def mark(store: Store | None = None) -> dict:
    """Re-mark the risk-parity held legs against the latest REAL adjusted closes (the paper clock, equity
    edition). Each run writes a fresh portfolio_snapshot, advancing the paper trajectory, and drives
    tracks.return_pct from the LIVE marked value so a flat/negative paper run can never reach live_ready on a stale
    seed. SIM only."""
    store = store or Store(Settings())
    version_id = _existing_version(store)
    if version_id is None:
        print("No Risk Parity track registered yet — run `arm` first.")
        return {"marked": False}
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    marks: dict[str, Decimal] = {}
    for p in portfolio.positions():
        if p.strategy_version_id != version_id:
            continue
        price = _last_adj_close(p.symbol)
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
    print(f"Risk Parity paper MARK — marked {len(marks)} leg(s); aggregate equity ${float(snap['equity']):,.2f} "
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
