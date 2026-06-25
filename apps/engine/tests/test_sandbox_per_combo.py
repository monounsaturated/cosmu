# SANDBOX per-combo risk model (operator decision Q1 = "sandbox + global backstop").
#
# 1 wallet = 1 combo (a track = strategy_version × symbol × venue). A combo can NEVER lose more than its
# allocated starting_capital: master/risk.validate_order_full bounds a BUY to the track's OWN deployable cash
# (per-track view, NOT the aggregate pool), and emits a per-combo KILL flag when the wallet is spent. The
# aggregate drawdown_killswitch + daily_loss caps remain the FINAL backstop and are NEVER removed.
#
# These tests pin: (i) a would-be over-loss order is rejected on the per-track wallet bound; (ii) the per-combo
# kill fires + a reduce_only exit stays exempt; (iii) the aggregate backstop still fires; (iv) the gate is on the
# PER-TRACK view (a fat aggregate pool never rescues a spent combo, and a thin pool never blocks a solvent combo).

from __future__ import annotations

from decimal import Decimal

from cosmu.adapters.exec.binance import BinanceSpotExecutionAdapter
from cosmu.config.settings import RiskSettings, Settings
from cosmu.knowledge.store import Store
from cosmu.master.execution import IntendedOrder, execute_orders
from cosmu.master.portfolio import Portfolio
from cosmu.master.risk import OrderIntent, PortfolioRiskState, validate_order_full
from cosmu.spine.venue import default_catalog

CATALOG = default_catalog()
VENUE = CATALOG.venue("binance")
INSTR = CATALOG.instrument("BTCUSDT", "binance")


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/sandbox.sqlite3"))


def _buy(notional: Decimal, *, price: Decimal = Decimal("100"), reduce_only: bool = False, side: str = "buy") -> OrderIntent:
    qty = (notional / price)
    return OrderIntent(
        symbol="BTCUSDT", side=side, qty=qty, price=price,
        stop_loss=Decimal("90") if side == "buy" and not reduce_only else None,
        take_profit=Decimal("130") if side == "buy" and not reduce_only else None,
        conviction=Decimal("1.0"), sizing_basis="equity_vol_conviction", reduce_only=reduce_only,
    )


# ── (ii) unit: validate_order_full per-combo bound ────────────────────────────────────────────────


def test_per_combo_bound_rejects_order_exceeding_wallet():
    """A BUY whose notional exceeds THIS track's own deployable cash is rejected — the combo can never deploy
    (hence lose) more than its starting_capital. The aggregate pool is huge; only the per-track cash binds."""
    state = PortfolioRiskState(
        equity=Decimal("100000"), cash=Decimal("100000"),  # fat aggregate pool — must NOT rescue
        track_starting_capital=Decimal("1000"), track_equity=Decimal("1000"), track_cash=Decimal("1000"),
    )
    # $1500 > the $1000 wallet → rejected on the per-combo bound.
    over = validate_order_full(_buy(Decimal("1500")), VENUE, INSTR, RiskSettings(), state)
    assert over.accepted is False
    assert "combo_capital_exceeded" in over.issues
    # Exactly the wallet → accepted (the boundary is inclusive: a combo may deploy its whole slice all-in).
    at = validate_order_full(_buy(Decimal("1000")), VENUE, INSTR, RiskSettings(), state)
    assert at.accepted is True and "combo_capital_exceeded" not in at.issues


def test_per_combo_bound_uses_remaining_cash_after_prior_loss():
    """The wallet shrinks with realized loss: track_cash already nets the combo's own losses + open notional, so
    after a drawdown the combo can deploy only what's LEFT — never topping itself back up to its original slice."""
    # Started at $1000, lost $400 → only $600 deployable. A $700 add is rejected; $600 is allowed.
    state = PortfolioRiskState(
        equity=Decimal("100000"), cash=Decimal("100000"),
        track_starting_capital=Decimal("1000"), track_equity=Decimal("600"), track_cash=Decimal("600"),
    )
    assert validate_order_full(_buy(Decimal("700")), VENUE, INSTR, RiskSettings(), state).accepted is False
    assert validate_order_full(_buy(Decimal("600")), VENUE, INSTR, RiskSettings(), state).accepted is True


def test_per_combo_kill_flag_when_wallet_spent():
    """When the track's own equity hits its kill floor the decision carries kill_combo=True, a new entry is
    rejected with combo_wallet_spent, and the loss is thereby bounded — the combo takes no further risk."""
    state = PortfolioRiskState(
        equity=Decimal("100000"), cash=Decimal("100000"),
        track_starting_capital=Decimal("1000"), track_equity=Decimal("0"), track_cash=Decimal("0"),
        track_kill_floor_pct=Decimal("0"),
    )
    d = validate_order_full(_buy(Decimal("10")), VENUE, INSTR, RiskSettings(), state)
    assert d.kill_combo is True
    assert d.accepted is False and "combo_wallet_spent" in d.issues


def test_per_combo_kill_floor_fraction_fires_early():
    """A positive kill floor fraction kills BEFORE the wallet is fully drained (so the next adverse mark can't
    breach it): equity at 10% of a $1000 wallet with floor 0.10 trips the kill."""
    state = PortfolioRiskState(
        equity=Decimal("100000"), cash=Decimal("100000"),
        track_starting_capital=Decimal("1000"), track_equity=Decimal("100"), track_cash=Decimal("100"),
        track_kill_floor_pct=Decimal("0.10"),
    )
    assert validate_order_full(_buy(Decimal("10")), VENUE, INSTR, RiskSettings(), state).kill_combo is True
    # Just above the floor → not killed, a within-cash entry is fine.
    ok = PortfolioRiskState(
        equity=Decimal("100000"), cash=Decimal("100000"),
        track_starting_capital=Decimal("1000"), track_equity=Decimal("101"), track_cash=Decimal("101"),
        track_kill_floor_pct=Decimal("0.10"),
    )
    d = validate_order_full(_buy(Decimal("50")), VENUE, INSTR, RiskSettings(), ok)
    assert d.kill_combo is False and d.accepted is True


def test_reduce_only_exit_exempt_from_per_combo_bound_even_when_killed():
    """A reduce_only CLOSE is NEVER trapped by the per-combo bound or the kill — closing the leg is exactly what
    a spent wallet needs. The kill flag is still reported so the executor liquidates it."""
    state = PortfolioRiskState(
        equity=Decimal("100000"), cash=Decimal("100000"),
        track_starting_capital=Decimal("1000"), track_equity=Decimal("-50"), track_cash=Decimal("0"),
        existing_qty=Decimal("5"),  # long 5 → a sell of ≤5 genuinely reduces
    )
    close = OrderIntent(
        symbol="BTCUSDT", side="sell", qty=Decimal("5"), price=Decimal("80"),
        stop_loss=None, take_profit=None, conviction=Decimal("1.0"),
        sizing_basis="equity_vol_conviction", reduce_only=True,
    )
    d = validate_order_full(close, VENUE, INSTR, RiskSettings(), state)
    assert d.accepted is True            # the exit clears
    assert d.kill_combo is True          # but the kill is still signalled to the caller
    assert "combo_wallet_spent" not in d.issues and "combo_capital_exceeded" not in d.issues


def test_per_combo_checks_skipped_without_a_wallet():
    """No tracks row (bare-position tests/tools) ⇒ track_starting_capital None ⇒ the per-combo bound is SKIPPED
    and the aggregate gauntlet governs (today's behaviour exactly)."""
    state = PortfolioRiskState(
        equity=Decimal("100000"), cash=Decimal("100000"), track_starting_capital=None,
    )
    d = validate_order_full(_buy(Decimal("50000")), VENUE, INSTR, RiskSettings(), state)
    # No per-combo issue at all — a $50k order is fine vs the aggregate $100k pool/caps.
    assert "combo_capital_exceeded" not in d.issues and "combo_wallet_spent" not in d.issues
    assert d.kill_combo is False


# ── (iii) the AGGREGATE backstop is NOT removed ───────────────────────────────────────────────────


def test_aggregate_drawdown_killswitch_still_fires_under_sandbox():
    """The aggregate drawdown kill-switch remains the FINAL backstop: a solvent per-combo wallet does NOT
    exempt an order from the pool-level kill-switch (Q1 = sandbox + filet global)."""
    risk = RiskSettings()
    state = PortfolioRiskState(
        equity=Decimal("80000"), cash=Decimal("80000"),
        drawdown_pct=risk.drawdown_killswitch_pct,  # at the kill-switch
        track_starting_capital=Decimal("1000"), track_equity=Decimal("1000"), track_cash=Decimal("1000"),
    )
    d = validate_order_full(_buy(Decimal("500")), VENUE, INSTR, risk, state)
    assert d.accepted is False and "drawdown_killswitch" in d.issues  # per-combo solvent, pool kill still bites


def test_aggregate_daily_loss_cap_still_fires_under_sandbox():
    state = PortfolioRiskState(
        equity=Decimal("99000"), cash=Decimal("99000"),
        daily_loss=Decimal("300"), daily_loss_cap=Decimal("250"),  # over the daily cap
        track_starting_capital=Decimal("1000"), track_equity=Decimal("1000"), track_cash=Decimal("1000"),
    )
    d = validate_order_full(_buy(Decimal("500")), VENUE, INSTR, RiskSettings(), state)
    assert d.accepted is False and "daily_loss_auto_disarm" in d.issues


# ── (i)+(iv) integration through the real order path with a tracks row ─────────────────────────────


def _seed_track(store: Store, vid: str, starting_capital: str) -> str:
    """A funded paper track row — the per-combo wallet the order path reads via Portfolio.track_risk. Seeds the
    parent strategy + strategy_version (the tracks FK) and returns the real version id."""
    sid = store.insert("strategies", {"name": f"s-{vid}", "thesis": "t", "origin": "seed", "created_at": "2026-06-25"})
    real_vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {}, "generated_code": "", "code_hash": f"h-{vid}", "params": {},
        "origin": "seed", "status": "paper", "created_at": "2026-06-25",
    })
    store.insert("tracks", {
        "strategy_version_id": real_vid, "symbol": "BTCUSDT", "venue_id": "binance",
        "starting_capital": starting_capital, "equity": starting_capital, "return_pct": "0.00",
        "updated_at": "2026-06-25T00:00:00Z",
    })
    return real_vid


def test_order_path_bounds_combo_loss_to_starting_capital(tmp_path):
    """END-TO-END: a $1000-wallet track cannot place a buy larger than $1000 through the live order path — so the
    most it can ever lose is bounded to its starting_capital. A within-wallet buy fills; an over-wallet buy is
    rejected with combo_capital_exceeded even though the SIM pool has $100k."""
    store = _store(tmp_path)
    vid = _seed_track(store, "sv1", "1000")
    pf = Portfolio(store, bankroll=Decimal("100000"))
    adapter = BinanceSpotExecutionAdapter(client=None, mode="disabled")

    def _go(notional: Decimal):
        intent = IntendedOrder(
            strategy_version_id=vid, symbol="BTCUSDT", venue_id="binance", side=1,
            qty=notional / Decimal("100"), price=Decimal("100"),
            stop_loss=Decimal("90"), take_profit=Decimal("130"), conviction=Decimal("1.0"),
            gate_passed=True, client_order_id=f"coid-{notional}",
        )
        return execute_orders([intent], live_enabled=False, kill_switch=False, adapter=adapter,
                              store=store, portfolio=pf, risk=RiskSettings(), catalog=CATALOG)

    over = _go(Decimal("1500"))
    assert over[0].accepted is False and "combo_capital_exceeded" in over[0].issues

    ok = _go(Decimal("900"))
    assert ok[0].accepted is True  # within the wallet → fills
    # The combo deployed ≤ its wallet, so its position notional can never exceed starting_capital.
    pos = pf.position("btc-usdt-binance", "sim", strategy_version_id=vid)
    assert pos is not None and pos.avg_price * pos.qty <= Decimal("1000")


def test_order_path_per_combo_kill_audited_and_blocks_new_entry(tmp_path):
    """A spent wallet: after the combo realizes a loss that drains its wallet, the order path audits a
    combo_killed event and refuses a new entry — the per-track gate, not the aggregate pool, decides."""
    store = _store(tmp_path)
    vid = _seed_track(store, "sv1", "1000")
    pf = Portfolio(store, bankroll=Decimal("100000"))
    adapter = BinanceSpotExecutionAdapter(client=None, mode="disabled")

    # Drain the wallet: buy $900 then close at a heavy loss so realized P&L ≈ −$1000 (wallet equity ≤ 0).
    pf.apply_fill(instrument_id="btc-usdt-binance", symbol="BTCUSDT", venue="sim", side=1,
                  qty=Decimal("9"), price=Decimal("100"), fee=Decimal("0"), strategy_version_id=vid)
    pf.apply_fill(instrument_id="btc-usdt-binance", symbol="BTCUSDT", venue="sim", side=-1,
                  qty=Decimal("9"), price=Decimal("0.01"), fee=Decimal("0"), strategy_version_id=vid)
    # track_equity = 1000 + realized(≈ −899.9) + unrealized(0, flat) ≈ 100 > 0 — NOT yet killed at floor 0.
    # Push it under: book another loss so realized < −1000.
    pf.apply_fill(instrument_id="btc-usdt-binance", symbol="BTCUSDT", venue="sim", side=1,
                  qty=Decimal("2"), price=Decimal("100"), fee=Decimal("0"), strategy_version_id=vid)
    pf.apply_fill(instrument_id="btc-usdt-binance", symbol="BTCUSDT", venue="sim", side=-1,
                  qty=Decimal("2"), price=Decimal("0.01"), fee=Decimal("0"), strategy_version_id=vid)
    tr = pf.track_risk(vid, symbol="BTCUSDT", venue="binance")
    assert tr.starting_capital == Decimal("1000") and tr.equity <= Decimal("0")  # wallet spent

    intent = IntendedOrder(
        strategy_version_id=vid, symbol="BTCUSDT", venue_id="binance", side=1,
        qty=Decimal("1"), price=Decimal("100"), stop_loss=Decimal("90"), take_profit=Decimal("130"),
        conviction=Decimal("1.0"), gate_passed=True, client_order_id="coid-after-kill",
    )
    out = execute_orders([intent], live_enabled=False, kill_switch=False, adapter=adapter,
                         store=store, portfolio=pf, risk=RiskSettings(), catalog=CATALOG)
    assert out[0].accepted is False and "combo_wallet_spent" in out[0].issues
    assert store.row("SELECT id FROM events WHERE kind = 'combo_killed'") is not None


def test_solvent_combo_not_blocked_by_thin_aggregate_pool(tmp_path):
    """The bound is on the PER-TRACK view: a solvent $1000 wallet deploying $900 is NOT blocked just because a
    DIFFERENT combo drew the shared sim pool down — per-combo isolation is the whole point of the sandbox."""
    store = _store(tmp_path)
    vid = _seed_track(store, "sv1", "1000")
    # A small pool, but the per-combo wallet is what gates this order.
    pf = Portfolio(store, bankroll=Decimal("2000"))
    adapter = BinanceSpotExecutionAdapter(client=None, mode="disabled")
    intent = IntendedOrder(
        strategy_version_id=vid, symbol="BTCUSDT", venue_id="binance", side=1,
        qty=Decimal("9"), price=Decimal("100"), stop_loss=Decimal("90"), take_profit=Decimal("130"),
        conviction=Decimal("1.0"), gate_passed=True, client_order_id="coid-solvent",
    )
    out = execute_orders([intent], live_enabled=False, kill_switch=False, adapter=adapter,
                         store=store, portfolio=pf, risk=RiskSettings(), catalog=CATALOG)
    assert out[0].accepted is True  # solvent combo, within wallet → fills regardless of pool size
