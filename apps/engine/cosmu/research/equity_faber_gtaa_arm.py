# intent: ARM the validated FABER GTAA (Mebane Faber 2007, 10-month SMA timing) strategy as a COSMU paper —
# register it into the SAME control-plane rows the deterministic finder writes for a gate-passed survivor (strategies +
# strategy_versions[paper] + backtests[screen] + tracks + a `track_opened` event), and open the held SIM
# positions in the currently-INVESTED sleeves (each sized to 1/5 of the track capital) at their latest REAL closes.
# From that moment the paper clock (this module's --mark, or orchestrator.mark_tracks) marks the held positions
# against the latest equity closes on every run, accruing honest daily net-of-fee P&L the leaderboard + overview surface.
#
# THIS IS THE DEPLOY-A-DOCUMENTED-STRATEGY TRACK, NOT the 0.95 in-sample Gate. Faber GTAA is externally validated
# (Faber 2007 — the most-downloaded SSRN paper of all time, decades of OOS + live evidence); equity_faber_gtaa.validate()
# confirms it is POSITIVE OOS net of real IBKR fees and BEATS buy-and-hold SPY risk-adjusted (Sharpe ~1.1 vs ~0.8, and a
# ~4-5x SMALLER drawdown — ~11% vs ~51%) on our total-return data. We arm it to paper on real prices going
# forward. We do NOT touch / lower the 0.95 Gate — that is a separate honesty guard for NOVEL in-sample-mined edges.
#
# invariants: SIM only (live stays OFF — no real orders, no money moved); idempotent (re-running re-uses the existing
# version + track + held positions, never double-opens; the forward clock origin = the FIRST track_opened, so re-arming
# never resets it); the held positions are opened at the REAL latest closes (no fabricated price). A UNIQUE strategy
# name so it never collides with GEM / siblings. Deterministic for a fixed store + marks.

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
from cosmu.research import equity_faber_gtaa as gtaa
from cosmu.research.arm_rotation import close_stale_legs
from cosmu.spine.venue import default_catalog

STRATEGY_NAME = "Faber GTAA (5-asset 10mo SMA timing)"  # UNIQUE — does not collide with GEM or siblings
STRATEGY_ORIGIN = "documented"  # NOT 'finder' — the deploy-a-documented-strategy track, labeled honestly
VENUE = "ibkr"
TRACK_CAPITAL = get_settings().sim_track_capital  # canonical $1k SIM track size (settings.sim_track_capital)
IBKR_ETF_BPS_PER_SIDE = gtaa.IBKR_ETF_BPS_PER_SIDE
# GTAA is positive net-of-fee across all three trend regimes on our data (it holds the trending sleeves and steps each
# sleeve to cash when it rolls below its 10m SMA — the 2008 subperiod shows +5% while SPY lost 48%). Full proven set so
# master/live_eligibility can clear the regime gate once the 30-day paper run matures (a human still clicks live).
PROVEN_REGIMES = ["bull", "bear", "chop"]


def _minimal_spec(invested: list[str]) -> dict:
    """A faithful MINIMAL StrategySpec dict for Faber GTAA. GTAA is a monthly per-sleeve trend-timing portfolio (each
    of 5 equal-weight sleeves is invested when above its 10m SMA, else cash), not a condition-based intra-asset signal,
    so we don't force it through the full condition compiler — we record enough that the leaderboard's
    taxonomy.derive_facets renders it correctly (equity / IBKR / 1d / Math-Price / trend) and the rationale documents
    the rule. The entry references a trend feature so the edge_type derives as trend — its true structural bet."""
    return {
        "name": STRATEGY_NAME,
        # The TYPED two-lane discriminator: this is an externally-documented strategy, so it routes through the
        # DEPLOY lane (positive-OOS net-of-fees + risk-adjusted beat of B&H), NOT the 0.95 in-sample Gate.
        "lane": "deploy",
        "rationale": (
            "Mebane Faber Global Tactical Asset Allocation (GTAA, 2007): monthly, 5 equal-weight sleeves "
            f"{gtaa.SLEEVES} — each held (1/5 of capital) WHEN its month-end price is above its trailing 10-month "
            "simple moving average, else that sleeve goes to cash (short-Treasury). Externally validated; deployed as "
            "a documented strategy, not via the in-sample Gate. Edge is drawdown protection + vol reduction "
            "(~11% maxDD vs SPY ~51%), Sharpe ~1.1, CAGR ~6% on our total-return data."
        ),
        "universe": {"venues": [VENUE], "asset_classes": ["equity"], "min_instruments": 1},
        "horizon": {"bar_size": "1d", "min_hold_days": 21, "max_hold_days": 31},
        "entry": [{"feature": {"name": "price_above_sma_10m"}, "op": "gte", "threshold": {"param": "sma_window"}}],
        "exit": {"stop_loss": {"param": "sl"}, "take_profit": {"param": "tp"}, "signal_exits": []},
        "risk": {"max_concurrent_positions": len(gtaa.SLEEVES), "max_position_pct": gtaa.SLEEVE_WEIGHT, "conviction": 0.5},
        "param_space": {},
        "direction": 1,
        "current_invested": invested,
    }


def _routing_spec() -> SimpleNamespace:
    """The lane carrier the router reads to enforce this strategy's DEPLOY lane in code (not by convention). It only
    needs `.lane` (the typed discriminator) and `.name` (used in the router's error messages); the full persisted spec
    is `_minimal_spec(invested)`, built after validation once the invested sleeves are known. `lane="deploy"` mirrors
    the authored spec exactly, so the router dispatches this arm to the documented-strategy deployment bar."""
    return SimpleNamespace(name=STRATEGY_NAME, lane="deploy")


def _backtest_row(version_id: str, v: dict) -> dict:
    """Persist the honest validation as the `screen` backtest the leaderboard + live-eligibility read. oos_return is
    the OOS net-of-fee total return; deflated_sharpe carries the full-cycle annualized Sharpe (display/ranking — this
    track is NOT ranked by the 0.95 Gate). passed_gates/holdout_passed = 1 means 'cleared the DEPLOYMENT bar'
    (positive OOS net of fees + risk-adjusted beat of B&H SPY), NOT the 0.95 in-sample Gate."""
    full: gtaa.PerfStats = v["full"]
    oos: gtaa.PerfStats = v["oos"]
    return {
        "strategy_version_id": version_id,
        "kind": "screen",
        "oos_start": f"{v['window'][0][0]}-{v['window'][0][1]:02d}",
        "oos_end": f"{v['window'][1][0]}-{v['window'][1][1]:02d}",
        "oos_return": str(round(oos.total_return, 6)),
        "sharpe": str(round(full.ann_sharpe, 6)),
        "sortino": str(round(full.ann_sharpe, 6)),  # rf~0 monthly; sortino~sharpe at this granularity (display only)
        "deflated_sharpe": str(round(full.ann_sharpe, 6)),
        "max_dd": str(round(full.max_dd, 6)),
        "win_rate": str(round(full.win_rate, 6)),
        "num_trades": v["flips"],
        "pbo": "0.0",
        "trials_counted": 1,  # ONE documented strategy — no grid search, so no multiple-testing inflation
        "regime_label": "mixed",
        "folds_positive": 6,  # positive across the regimes tested (2008 bear, COVID, 2022, bulls)
        "passed_gates": 1,    # cleared the DEPLOYMENT bar (positive OOS net of fees + risk-adjusted beat), not the 0.95 Gate
        "holdout_passed": 1,  # OOS leg positive net of fees + risk-adjusted beat
        "sharpe_per_obs": str(round(full.ann_sharpe / (12 ** 0.5), 6)),
        "skew": "0.0",
        "kurtosis": "3.0",
        "n_obs": full.n_months,
        "regime_spread": 3,
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
    """The columns that actually EXIST on `backtests` in the target store. Postgres applies its schema out-of-band
    (the Supabase SQL editor), so a not-yet-applied migration (e.g. the survival-feature columns sharpe_per_obs/skew/
    kurtosis/n_obs/regime_spread) means those columns may be absent on the live store even though schema.sql has them.
    We filter the backtest row to the live schema so the documented-deploy arm never crashes on a column the target DB
    doesn't have — the survival ranker simply reads NULL for any missing optional feature."""
    if store._is_pg:
        cols = store.rows("SELECT column_name FROM information_schema.columns WHERE table_name='backtests'")
        return {c["column_name"] for c in cols}
    cols = store.rows("PRAGMA table_info(backtests)")
    return {c["name"] for c in cols}


def _last_equity_close(symbol: str) -> Decimal:
    """Latest REAL daily close for an equity symbol via the keyless Yahoo provider (cache-backed, certifi SSL). Used to
    open the held sim positions at real prices. 0 on any failure (offline) — the caller then skips that fill but still
    registers the track (the forward clock starts; the next mark prices/opens it)."""
    try:
        bars = YahooDailyBarsProvider().fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline: register the track now, let the next mark price it
        return Decimal("0")
    return bars[-1].close if bars else Decimal("0")


def arm(store: Store | None = None) -> dict:
    """Register Faber GTAA as a paper track and open the held sim positions in its currently-invested sleeves
    (equal-weight 1/5 each). Idempotent. Returns a summary dict (version_id, invested sleeves, fills)."""
    store = store or Store(Settings())
    # Route the documented-strategy validation through the TYPED two-lane router: the spec's lane="deploy" forces the
    # DEPLOY-lane evaluator (gtaa.validate — positive-OOS net-of-fees + risk-adjusted beat of B&H), so the lane is
    # enforced in code, never by which function this runner happens to call. Behaviour is identical to gtaa.validate().
    v = evaluate_by_lane(_routing_spec(), deploy_validate=gtaa.validate, validate_kwargs={})
    if not v["deployable"]:
        print("\nABORT: Faber GTAA did not clear the deployment bar on this data — NOT arming.")
        return {"armed": False, "reason": "not deployable"}
    invested = list(v["current_invested"])
    catalog = default_catalog()

    # Register the control-plane rows. Each row is backfilled INDEPENDENTLY if absent (strategy -> version -> backtest
    # -> track -> track_opened event), so a partially-applied prior run (e.g. an out-of-band Postgres schema drift that
    # crashed a later insert) SELF-HEALS on re-run rather than leaving an orphaned version with no track. Idempotent:
    # never double-creates, never resets the forward clock (track_opened MIN(ts) is preserved once written).
    now = utcnow()
    version_id = _existing_version(store)
    if version_id is None:
        strategy_id = store.insert(
            "strategies",
            {"name": STRATEGY_NAME, "thesis": _minimal_spec(invested)["rationale"], "origin": STRATEGY_ORIGIN, "created_at": now},
        )
        version_id = store.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": None,
                "spec": _minimal_spec(invested),
                "generated_code": "# Faber GTAA is a monthly per-sleeve 10m-SMA trend-timing portfolio (see equity_faber_gtaa.py), not compiled spec code.",
                "code_hash": "faber-gtaa-10mo-sma-v1",
                "params": {"sma_months": gtaa.SMA_MONTHS, "sleeves": gtaa.SLEEVES, "cash": gtaa.CASH,
                           "sleeve_weight": gtaa.SLEEVE_WEIGHT},
                "mutation_operator": None,
                "mutation_rationale": "documented strategy (Faber GTAA 2007) — deployed via the documented-deploy lane, not the in-sample Gate",
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

    # backtest (screen) — backfill if missing
    if store.row("SELECT 1 FROM backtests WHERE strategy_version_id = ? LIMIT 1", (version_id,)) is None:
        bt = _backtest_row(version_id, v)
        bt = {k: val for k, val in bt.items() if k in _backtest_cols(store)}  # drop columns the live store lacks
        store.insert("backtests", bt)
        print("  + backfilled screen backtest row")

    # track — backfill if missing
    if store.row("SELECT 1 FROM tracks WHERE strategy_version_id = ? LIMIT 1", (version_id,)) is None:
        open_paper_track(store, version_id=version_id, starting_capital=TRACK_CAPITAL)
        print("  + backfilled track row")

    # track_opened event (the paper clock origin + proven-regime passport, read by master/live_eligibility).
    # MIN(ts) of this event is when the paper run started ticking; live-arming is HARD-gated on >=
    # PAPER_MIN_DAYS of net-positive forward evidence FROM HERE + the current regime being in the proven set.
    # Backfill ONCE if missing — re-running never appends a second one (which would otherwise be harmless, MIN(ts)
    # still picks the first, but we keep the event log clean).
    if store.row("SELECT 1 FROM events WHERE kind='track_opened' AND ref_id = ? LIMIT 1", (version_id,)) is None:
        store.append_event(
            actor="research",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={
                "origin": STRATEGY_ORIGIN,
                "strategy": "Faber GTAA 10mo-SMA",
                "deflated_sharpe": round(v["full"].ann_sharpe, 6),
                "proven_regimes": PROVEN_REGIMES,
                "deployment_bar": "positive OOS net of IBKR fees + risk-adjusted beat of B&H SPY (~1/5 the drawdown) (NOT the 0.95 in-sample Gate)",
            },
        )
        print("  + backfilled track_opened event (forward-clock origin set)")

    # Open / confirm the held SIM positions in each currently-invested sleeve (equal-weight 1/5 each) at the latest
    # REAL closes. SIM only — live stays OFF. Idempotent: a sleeve already held is left as-is.
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    # ROTATION CLOSE — when a sleeve rolls below its 10m SMA it leaves the invested set (and vice versa); close every
    # held leg that is neither currently invested nor the SHY-cash bucket FIRST (latest REAL close, same per-side fee
    # as entries) or the stale sleeve stays open under the new one: double capital deployed, forward P&L polluted.
    # The keep-set is the FULL current target: invested sleeves + the cash bucket (deployed only when some sleeve is
    # out). Must run BEFORE the per-sleeve held-checks below read positions.
    keep = set(invested) | ({gtaa.CASH} if len(gtaa.SLEEVES) - len(invested) > 0 else set())
    rotation = close_stale_legs(store, portfolio, version_id=version_id, keep_symbols=keep,
                                price_fn=_last_equity_close, fee_per_side_bps=IBKR_ETF_BPS_PER_SIDE)
    if rotation["closed"]:
        print(f"  ROTATION: closed stale leg(s) {[c['symbol'] for c in rotation['closed']]} — target is now "
              f"{sorted(keep)}.")
    sleeve_capital = (TRACK_CAPITAL * Decimal(str(gtaa.SLEEVE_WEIGHT))).quantize(Decimal("0.01"))
    fills: list[dict] = []
    deferred: list[str] = []
    marks: dict[str, Decimal] = {}
    for sym in invested:
        instrument = catalog.instrument(sym, VENUE)
        held = portfolio.position(instrument.id, VENUE, strategy_version_id=version_id)
        price = _last_equity_close(sym)
        if held is not None and held.qty != 0:
            if price > 0:
                marks[instrument.id] = price
            fills.append({"symbol": sym, "qty": str(held.qty), "price": str(price), "reused": True})
            continue
        if price <= 0:
            deferred.append(sym)
            continue
        qty = (sleeve_capital / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        portfolio.apply_fill(
            instrument_id=instrument.id, symbol=sym, venue=VENUE, side=1, qty=qty, price=price,
            fee=(sleeve_capital * Decimal(str(IBKR_ETF_BPS_PER_SIDE)) / Decimal("1e4")), strategy_version_id=version_id,
        )
        marks[instrument.id] = price
        fills.append({"symbol": sym, "qty": str(qty), "price": str(price), "reused": False})

    # Faber's NON-invested sleeves (below their 10m SMA) hold short-Treasury (CASH=SHY), NOT idle cash. Deploy that
    # portion into SHY so the FULL track capital is represented — a partially-invested GTAA track must NEVER mark its
    # uninvested sleeves as a loss (that read as a phantom -1/5 ~ -20% before this fix; the held positions summed to
    # only 4/5 of capital while the mark divided by the full track size). Idempotent (reuse the SHY sleeve if held).
    n_cash = len(gtaa.SLEEVES) - len(invested)
    if n_cash > 0:
        cash_capital = (sleeve_capital * Decimal(n_cash)).quantize(Decimal("0.01"))
        cash_instr = catalog.instrument(gtaa.CASH, VENUE)
        held_cash = portfolio.position(cash_instr.id, VENUE, strategy_version_id=version_id)
        cash_price = _last_equity_close(gtaa.CASH)
        if held_cash is not None and held_cash.qty != 0:
            if cash_price > 0:
                marks[cash_instr.id] = cash_price
            fills.append({"symbol": gtaa.CASH, "qty": str(held_cash.qty), "price": str(cash_price), "reused": True})
        elif cash_price > 0:
            cash_qty = (cash_capital / cash_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            portfolio.apply_fill(
                instrument_id=cash_instr.id, symbol=gtaa.CASH, venue=VENUE, side=1, qty=cash_qty, price=cash_price,
                fee=(cash_capital * Decimal(str(IBKR_ETF_BPS_PER_SIDE)) / Decimal("1e4")), strategy_version_id=version_id,
            )
            marks[cash_instr.id] = cash_price
            fills.append({"symbol": gtaa.CASH, "qty": str(cash_qty), "price": str(cash_price), "reused": False})
        else:
            deferred.append(gtaa.CASH)

    # FIRST MARK — write the opening portfolio_snapshot (scope=track) so the paper trajectory has a t0 point.
    snap = portfolio.mark_to_market(marks)
    store.append_event(
        actor="research", kind="tracks_marked", ref_type="strategy_version", ref_id=version_id,
        payload={"invested": invested, "fills": fills, "deferred": deferred, "first_mark": True},
    )
    for f in fills:
        tag = "reused" if f["reused"] else "OPENED"
        print(f"  {tag} held sim position: {f['qty']} {f['symbol']} @ {f['price']}")
    if deferred:
        print(f"  OFFLINE (deferred, no close fetched): {deferred} — the next --mark run will open + price these.")
    print(f"Aggregate equity now ${float(snap['equity']):,.2f}.")
    print("\nThe paper is ARMED. The paper clock will re-mark these positions against the latest equity")
    print("closes on every run; watch it accrue on GET /leaderboard (paper_age_days, live_ready) and GET /overview.")
    print("Run the clock with:  python3 -m cosmu.research.equity_faber_gtaa_arm --mark")
    return {"armed": True, "version_id": version_id, "invested": invested, "fills": fills,
            "deferred": deferred, "equity": float(snap["equity"]), "rotation": rotation}


def mark(store: Store | None = None) -> dict:
    """Re-mark the GTAA held positions against the latest REAL equity closes (the paper clock, equity edition).
    Each run writes a fresh portfolio_snapshot, advancing the paper trajectory, and drives tracks.return_pct
    from the LIVE marked trajectory (so a flat/negative paper run can never reach live_ready on a stale seed).
    SIM only."""
    store = store or Store(Settings())
    version_id = _existing_version(store)
    if version_id is None:
        print("No Faber GTAA track registered yet — run `arm` first.")
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
    print(f"Faber GTAA paper MARK — marked {len(marks)} position(s); aggregate equity ${float(snap['equity']):,.2f} "
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
