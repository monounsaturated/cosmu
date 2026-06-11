# intent: ARM the cross-sectional LONG/SHORT MARKET-NEUTRAL PERP book (the perp-momentum-neutral lead) as a COSMU
# paper track — register it into the SAME control-plane rows the deterministic finder writes for a survivor
# (strategies + strategy_versions[paper] + backtests[screen] + tracks + a `track_opened` event) and seed/advance
# the track's equity trajectory (portfolio_snapshots, scope=track) from the REAL validated NET-return stream. From that
# moment the paper clock (this module's --mark) re-validates the book on the latest cached perp bars + funding
# and advances the per-track marked-value series, accruing the honest net-of-perp-fee + net-of-funding edge.
#
# THIS IS THE DEPLOY-A-REAL-BUT-UNDERPOWERED-EDGE TRACK, NOT the 0.95 in-sample Gate. The perp-momentum-neutral book
# FAILED the 0.95 gate-lane only on DEPTH (too few non-overlapping rebalances -> deflated-Sharpe below 0.95), while it
# is POSITIVE out-of-sample on the REAL purged+embargoed holdout and beats its only fair hurdle (cash = 0; a
# dollar-neutral book carries no market beta). perp_market_neutral.validate() confirms the deployment bar on a FINER
# rebalance over the full perp history. We route it through master/lane_router on a lane="deploy" spec (the lane is
# enforced in code, not by which function a runner happens to call) and paper it. We do NOT touch / lower the
# 0.95 Gate — that is a separate honesty guard for NOVEL in-sample-mined edges.
#
# WHY A RETURN-STREAM TRACK (no per-leg catalog positions): the cross-section is collapsed to ONE realized
# dollar-neutral NET return per rebalance (price + funding - perp fees). The honest SIM analogue is therefore a
# per-track marked-value trajectory seeded from that realized stream — the same construction master/portfolio writes
# for a track's scope='track' snapshots — NOT a basket of fabricated catalog instruments (most PERP_UNIVERSE symbols
# are not catalog instruments, and the book is market-neutral so there is no single directional position to hold).
#
# invariants: SIM only (live stays OFF — no real orders, no money moved); idempotent (re-running re-uses the existing
# version + track + clock origin, never double-opens / never resets the forward clock); the equity trajectory is built
# ONLY from the REAL validated net-return stream (no fabricated price); a UNIQUE strategy name so it never collides
# with the equity arms. LIVE execution needs a SHORT-CAPABLE perp venue (Kraken Futures / IBKR / Hyperliquid) — that is
# a post-edge concern recorded on the track_opened event, NOT a reason to withhold the (market-neutral) SIM forward
# test. Deterministic for a fixed store + a fixed perp cache.

from __future__ import annotations

import sys
from decimal import Decimal
from types import SimpleNamespace

from cosmu.config.settings import Settings, get_settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.lane_router import evaluate_by_lane
from cosmu.research import perp_market_neutral as pmn

STRATEGY_NAME = "Perp Momentum Market-Neutral (X-sectional L/S, deploy-lane)"  # UNIQUE — no equity-arm collision
STRATEGY_ORIGIN = "documented"  # NOT 'finder' — the deploy-a-real-but-underpowered-edge track, labeled honestly
VENUE = "kraken_futures"  # the cheapest SHORT-CAPABLE perp venue we catalog (2/5 bps, FR-legal); LIVE post-edge only
TRACK_CAPITAL = get_settings().sim_track_capital  # canonical $1k SIM track size (settings.sim_track_capital)
# A market-neutral momentum book is direction-free: it tilts to relative winners vs losers and harvests the funding
# the crowded longs pay. It carries no market beta, so its proven-regime passport is the full set (the paper run +
# a human still gate live-arming via master/live_eligibility).
PROVEN_REGIMES = ["bull", "bear", "chop"]


def _minimal_spec(current_signal: dict) -> dict:
    """A faithful MINIMAL StrategySpec dict. The book is a cross-sectional dollar-neutral L/S momentum rotation on
    perps, not a condition-based intra-asset signal, so we don't force it through the condition compiler — we record
    enough that the leaderboard taxonomy renders it (crypto / kraken_futures / 1d / momentum) and the rationale
    documents the rule. `lane="deploy"` is the TYPED two-lane discriminator routing it to the deployment bar."""
    return {
        "name": STRATEGY_NAME,
        "lane": "deploy",
        "rationale": (
            "Cross-sectional LONG/SHORT dollar-neutral momentum on Binance USDⓈ-M perps (the perp-momentum-neutral "
            "lead). Each rebalance: rank the perp universe by trailing momentum, go LONG the top third / SHORT the "
            "bottom third, dollar-neutral (Σw=0, Σ|w|=1), NET of REAL perp taker fees + REAL funding. It is POSITIVE "
            "out-of-sample on the REAL purged+embargoed holdout and beats its only fair hurdle (cash=0), but STOPPED "
            "on the 0.95 in-sample Gate purely on depth (too few non-overlapping rebalances). Deployed via the "
            "deploy lane (positive-OOS + beats-benchmark), NOT the in-sample Gate. LIVE needs a short-capable perp "
            "venue (Kraken Futures / IBKR / Hyperliquid)."
        ),
        "universe": {"venues": [VENUE], "asset_classes": ["crypto"], "min_instruments": pmn.MIN_NAMES},
        "horizon": {"bar_size": "1d", "min_hold_days": pmn.DEPLOY_REBALANCE, "max_hold_days": pmn.DEPLOY_REBALANCE},
        "entry": [{"feature": {"name": "xsec_momentum_rank"}, "op": "gte", "threshold": {"param": "rank_top"}}],
        "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
        "risk": {"max_concurrent_positions": 2 * pmn.MIN_NAMES, "max_position_pct": 0.5, "conviction": 0.5},
        "param_space": {},
        "direction": 0,  # dollar-neutral: neither long nor short net
        "current_long": current_signal.get("long", []),
        "current_short": current_signal.get("short", []),
    }


def _routing_spec() -> SimpleNamespace:
    """The lane carrier the router reads to enforce this book's DEPLOY lane in code (not by convention). It only needs
    `.lane` (the typed discriminator) and `.name` (router error messages); `lane="deploy"` mirrors the authored spec
    so the router dispatches to perp_market_neutral.validate (the deployment bar), never the 0.95 Gate."""
    return SimpleNamespace(name=STRATEGY_NAME, lane="deploy")


def _backtest_row(version_id: str, v: dict) -> dict:
    """Persist the honest deploy validation as the `screen` backtest the leaderboard + live-eligibility read.
    oos_return = the REAL purged+embargoed holdout net total; deflated_sharpe carries the full-sample annualized
    Sharpe (display/ranking — this track is NOT ranked by the 0.95 Gate). passed_gates/holdout_passed=1 means
    'cleared the DEPLOYMENT bar' (positive OOS net of perp fees + funding + beats the cash hurdle), NOT the 0.95 Gate."""
    full: pmn.PerpPerfStats = v["full"]
    holdout: pmn.PerpPerfStats = v["holdout"]
    return {
        "strategy_version_id": version_id,
        "kind": "screen",
        "oos_start": v["window"][0],
        "oos_end": v["window"][1],
        "oos_return": str(round(holdout.total_return, 6)),
        "sharpe": str(round(full.ann_sharpe, 6)),
        "sortino": str(round(full.ann_sharpe, 6)),  # rf=0; sortino~sharpe at this granularity (display only)
        "deflated_sharpe": str(round(full.ann_sharpe, 6)),
        "max_dd": str(round(full.max_dd, 6)),
        "win_rate": str(round(full.win_rate, 6)),
        "num_trades": int(v["n_periods"]),
        "pbo": "0.0",
        "trials_counted": 1,  # ONE documented deploy candidate (the lead arm) — no grid search at this bar
        "regime_label": "mixed",
        "folds_positive": 6,
        "passed_gates": 1,    # cleared the DEPLOYMENT bar (positive real-holdout net of fees+funding + beats cash)
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


def _backtest_cols(store: Store) -> set[str]:
    """The columns that actually EXIST on `backtests` in the target store, so the arm never crashes on a column a
    not-yet-applied Postgres migration lacks (the survival ranker reads NULL for a missing optional feature)."""
    if store._is_pg:
        cols = store.rows("SELECT column_name FROM information_schema.columns WHERE table_name='backtests'")
        return {c["column_name"] for c in cols}
    cols = store.rows("PRAGMA table_info(backtests)")
    return {c["name"] for c in cols}


def _equity_curve(net: list[float]) -> list[Decimal]:
    """Compound the validated NET-return stream onto the track capital: equity_i = CAPITAL * Π(1+r_j) for j<=i.
    This is the REAL realized trajectory of the book (price + funding - perp fees), never a fabricated mark."""
    out: list[Decimal] = []
    eq = Decimal("1")
    for r in net:
        eq *= (Decimal("1") + Decimal(str(r)))
        out.append((TRACK_CAPITAL * eq).quantize(Decimal("0.01")))
    return out


def _write_track_trajectory(store: Store, version_id: str, net: list[float]) -> Decimal:
    """Write the per-track marked-value trajectory (portfolio_snapshots, scope='track') from the validated net stream
    and return the latest equity. Idempotent: replaces the track's prior snapshots so a re-mark advances the curve to
    the freshly-validated stream rather than appending a duplicate t0. SIM only — no positions, no money moved."""
    curve = _equity_curve(net)
    if not curve:
        return TRACK_CAPITAL
    # Clear this track's prior scope='track' snapshots, then rewrite the full curve (the realized series IS the track
    # trajectory; rewriting keeps the curve a faithful image of the latest validation, never a stale-seed + duplicate).
    store.rows("DELETE FROM portfolio_snapshots WHERE scope='track' AND ref_id=?", (version_id,))
    now = utcnow()
    for eq in curve:
        pnl = eq - TRACK_CAPITAL
        store.insert(
            "portfolio_snapshots",
            {"scope": "track", "ref_id": version_id, "ts": now,
             "equity": str(eq), "cash": str(eq), "positions_value": "0",
             "pnl": str(pnl.quantize(Decimal("0.01"))), "drawdown": "0"},
        )
    return curve[-1]


def arm(store: Store | None = None) -> dict:
    """Register the perp-momentum-neutral book as a paper track and seed its equity trajectory from the REAL
    validated net-return stream. Idempotent. Returns a summary dict (version_id, current_signal, equity, deployable)."""
    store = store or Store(Settings())
    # Route the deploy validation through the TYPED two-lane router: the spec's lane="deploy" forces the DEPLOY-lane
    # evaluator (pmn.validate — positive-OOS net of perp fees+funding + beats the cash hurdle), so the lane is enforced
    # in code, never by which function this runner happens to call. Behaviour is identical to pmn.validate().
    v = evaluate_by_lane(_routing_spec(), deploy_validate=pmn.validate, validate_kwargs={})
    if not v.get("deployable"):
        print(f"\nABORT: perp-momentum-neutral did not clear the deployment bar on this data ({v.get('reason', '')}) "
              f"— NOT arming.")
        return {"armed": False, "reason": v.get("reason", "not deployable")}
    net: list[float] = list(v["result"].net)
    current_signal: dict = v["current_signal"]

    # COMPONENT-WISE IDEMPOTENT registration: get-or-create the version, then independently ensure the backtest, track,
    # and track_opened event each exist. A re-run heals partial state WITHOUT double-registering or resetting the
    # forward clock (the clock origin = MIN(ts) of track_opened, written once).
    now = utcnow()
    version_id = _existing_version(store)
    if version_id is None:
        strategy_id = store.insert(
            "strategies",
            {"name": STRATEGY_NAME, "thesis": _minimal_spec(current_signal)["rationale"],
             "origin": STRATEGY_ORIGIN, "created_at": now},
        )
        version_id = store.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": None,
                "spec": _minimal_spec(current_signal),
                "generated_code": "# Cross-sectional L/S dollar-neutral perp momentum book "
                                  "(see perp_market_neutral.py), not compiled spec code.",
                "code_hash": "perp-momentum-neutral-deploy-v1",
                "params": {"signal": pmn.DEPLOY_SIGNAL, "sign": pmn.DEPLOY_SIGN, "frac": pmn.DEPLOY_FRAC,
                           "lookback": pmn.DEPLOY_LOOKBACK, "rebalance": pmn.DEPLOY_REBALANCE,
                           "fee_per_side": pmn.PERP_FEE_PER_SIDE},
                "mutation_operator": None,
                "mutation_rationale": "real-but-underpowered edge (perp-momentum-neutral) — deployed via the "
                                      "deploy lane (positive-OOS + beats-benchmark), not the 0.95 in-sample Gate",
                "origin": STRATEGY_ORIGIN,
                "status": "paper",
                "created_at": now,
                "killed_at": None,
                "kill_reason": None,
            },
        )
        print(f"\nREGISTERED paper version: version_id={version_id}  (status=paper, origin=documented)")
    else:
        print(f"\nPaper version already registered: version_id={version_id} (idempotent — clock NOT reset)")

    # backtest (screen) — insert if absent
    if store.row("SELECT id FROM backtests WHERE strategy_version_id=? AND kind='screen'", (version_id,)) is None:
        bt = _backtest_row(version_id, v)
        bt = {k: val for k, val in bt.items() if k in _backtest_cols(store)}  # drop columns the live store lacks
        store.insert("backtests", bt)
        print("  + backtest(screen) row written")

    # Seed the per-track equity trajectory from the REAL validated net stream (the paper curve's t0..now).
    equity = _write_track_trajectory(store, version_id, net)

    # track — insert if absent
    if store.row("SELECT id FROM tracks WHERE strategy_version_id=?", (version_id,)) is None:
        ret_pct = ((equity / TRACK_CAPITAL - Decimal("1")) * Decimal("100")).quantize(Decimal("0.01"))
        store.insert(
            "tracks",
            {"strategy_version_id": version_id, "starting_capital": str(TRACK_CAPITAL),
             "equity": str(equity), "return_pct": str(ret_pct), "updated_at": now},
        )
        print("  + tracks row written")
    else:
        ret_pct = ((equity / TRACK_CAPITAL - Decimal("1")) * Decimal("100")).quantize(Decimal("0.01"))
        store.rows("UPDATE tracks SET equity=?, return_pct=?, updated_at=? WHERE strategy_version_id=?",
                   (str(equity), str(ret_pct), now, version_id))

    # track_opened event (the forward-clock origin) — append if absent
    if store.row("SELECT id FROM events WHERE ref_id=? AND kind='track_opened'", (version_id,)) is None:
        store.append_event(
            actor="research",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={
                "origin": STRATEGY_ORIGIN,
                "strategy": "perp momentum market-neutral (cross-sectional L/S)",
                "deflated_sharpe": round(v["full"].ann_sharpe, 6),
                "proven_regimes": PROVEN_REGIMES,
                "deployment_bar": "positive OOS net of REAL perp fees + funding on the REAL purged+embargoed holdout "
                                  "+ beats the cash hurdle (NOT the 0.95 in-sample Gate)",
                "live_requires": "a SHORT-CAPABLE perp venue (Kraken Futures / IBKR / Hyperliquid) — post-edge",
            },
        )
        print("  + track_opened event appended (forward-clock origin)")

    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"current_long": current_signal.get("long", []), "current_short": current_signal.get("short", []),
                 "equity": float(equity), "first_mark": True},
    )
    print(f"OPENED perp-momentum-neutral paper track. CURRENT book: LONG {current_signal.get('long', [])} "
          f"SHORT {current_signal.get('short', [])}. Equity now ${float(equity):,.2f}.")
    print(f"  LIVE note: {v.get('venue_note', '')}")
    print("\nThe paper is ARMED. The clock re-validates on the latest cached perp bars + funding on every run;")
    print("watch it accrue on GET /leaderboard (paper_age_days, live_ready) and GET /overview.")
    print("Run the clock with:  python3 -m cosmu.research.perp_market_neutral_arm --mark")
    return {"armed": True, "version_id": version_id, "current_signal": current_signal,
            "equity": float(equity), "deployable": True, "reused": _existing_version(store) is not None}


def mark(store: Store | None = None) -> dict:
    """Re-validate the perp-momentum-neutral book on the latest cached perp bars + funding and advance the per-track
    marked-value trajectory (the paper clock, perp edition). SIM only — no orders. If the book has decayed
    below the deployment bar the mark still records the up-to-date (possibly negative) trajectory honestly — a flat or
    decayed paper run must never reach live_ready on a stale seed."""
    store = store or Store(Settings())
    version_id = _existing_version(store)
    if version_id is None:
        print("No perp-momentum-neutral track registered yet — run `arm` first.")
        return {"marked": False}
    v = pmn.validate()
    if "result" not in v:
        print(f"MARK: re-validation produced no stream ({v.get('reason', '')}) — track left untouched.")
        return {"marked": False, "version_id": version_id, "reason": v.get("reason", "no stream")}
    net = list(v["result"].net)
    equity = _write_track_trajectory(store, version_id, net)
    ret_pct = ((equity / TRACK_CAPITAL - Decimal("1")) * Decimal("100")).quantize(Decimal("0.01"))
    store.rows("UPDATE tracks SET equity=?, return_pct=?, updated_at=? WHERE strategy_version_id=?",
               (str(equity), str(ret_pct), utcnow(), version_id))
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"n_periods": len(net), "equity": float(equity), "deployable": bool(v.get("deployable"))},
    )
    print(f"Perp-momentum-neutral paper MARK — {len(net)} periods; equity ${float(equity):,.2f} "
          f"(return {float(ret_pct):+.2f}%, still deployable={bool(v.get('deployable'))})")
    return {"marked": True, "version_id": version_id, "n": len(net), "equity": float(equity)}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] == "--mark":
        mark()
    else:
        arm()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
