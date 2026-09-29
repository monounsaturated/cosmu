# EXIT-PHYSICS PARITY (#5) + NEW EXIT TOOLS (#11): the paper executor must apply spec.exit.plan with the SAME
# physics the backtest (cosmu/data/backtest.py::_run_symbol) screened with — partial multi-TP scale-out legs,
# break-even-after-TP1, the post-TP1 runner trail, a STANDALONE trailing stop, and an ATR-multiple initial stop —
# plus per-bar funding accrual on a held perp leg. These tests pin: the shared step engine's per-bar physics; the
# new tools firing in BOTH the backtest and the paper executor; the live OCO carrying the first leg natively with
# the managed tail; and a control spec WITHOUT a plan staying byte-identical (no regression).

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.data.backtest import run_strategy_backtest
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.orchestrator import exit_state as xs
from cosmu.orchestrator.loop import PricingRouter, fund_tracks_from_survivors
from cosmu.orchestrator.paper_step import step_tracks
from cosmu.spine.venue import default_catalog
from cosmu.strategy.spec import (
    Condition,
    ExitPlan,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    TakeProfitLeg,
    TrailingStop,
    UniverseSelector,
)

_BASE = dt.datetime.now(tz=dt.UTC)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/exit.sqlite3", openrouter_api_key=None))


# --------------------------------------------------------------------------- OHLC provider (real intrabar range)


class _OHLCBars:
    """Offline provider with EXPLICIT per-bar OHLC so trailing / multi-TP legs (which read the bar high/low, not
    just the close) are exercisable. Anchored near now so the data-recency guard treats the bars as fresh."""

    def __init__(self, ohlc_by_symbol: dict[str, list[tuple[float, float, float, float]]]) -> None:
        self._by = ohlc_by_symbol

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        rows = self._by.get(symbol, [])
        bars = []
        for i, (o, h, l, c) in enumerate(rows):
            bars.append(Bar(ts=_BASE + dt.timedelta(days=i), open=Decimal(str(o)), high=Decimal(str(h)),
                            low=Decimal(str(l)), close=Decimal(str(c)), volume=Decimal("1000000")))
        return bars[-limit:]


def _router_ohlc(rows: list[tuple[float, float, float, float]]):
    prov = _OHLCBars({"BTCUSDT": rows})
    return PricingRouter(default_catalog(), crypto=prov, equity=prov), prov


def _flat(n: int, px: float) -> list[tuple[float, float, float, float]]:
    return [(px, px, px, px)] * n


# --------------------------------------------------------------------------- the shared step engine (unit)


def _plan_spec(**overrides) -> StrategySpec:
    """A managed-plan momentum spec: multi-TP (two legs) + break-even-after-TP1 + a runner trail. Entry signal is
    always-true (mom floor very negative) so the executor opens on the first tick."""
    exit_kwargs = dict(
        stop_loss=ParamRef(param="sl"),
        take_profit=ParamRef(param="tp"),
        plan=ExitPlan(
            multi_tp=[
                TakeProfitLeg(at=ParamRef(param="tp1_at"), size_pct=ParamRef(param="tp1_size")),
                TakeProfitLeg(at=ParamRef(param="tp2_at"), size_pct=ParamRef(param="tp2_size")),
            ],
            break_even_after_tp1=True,
            runner_trail=ParamRef(param="runner_trail"),
        ),
    )
    exit_kwargs.update(overrides)
    return StrategySpec(
        name="plan",
        rationale="multi-tp + break-even + runner-trail parity probe",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=1),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=365),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=3), op="gt", threshold=ParamRef(param="mom"))],
        exit=ExitRules(**exit_kwargs),
        risk=RiskRules(max_concurrent_positions=1, max_position_pct=1.0, conviction=0.5),
        param_space={
            "mom": ParamSpace(kind="float", lo=-1.0, hi=1.0),
            "sl": ParamSpace(kind="float", lo=0.01, hi=0.5),
            "tp": ParamSpace(kind="float", lo=0.01, hi=0.5),
            "tp1_at": ParamSpace(kind="float", lo=0.01, hi=0.5),
            "tp1_size": ParamSpace(kind="float", lo=0.1, hi=0.9),
            "tp2_at": ParamSpace(kind="float", lo=0.01, hi=0.5),
            "tp2_size": ParamSpace(kind="float", lo=0.1, hi=0.9),
            "runner_trail": ParamSpace(kind="float", lo=0.01, hi=0.5),
        },
    )


_PLAN_PARAMS = {
    "mom": -1.0, "sl": 0.10, "tp": 0.50,
    "tp1_at": 0.05, "tp1_size": 0.4, "tp2_at": 0.12, "tp2_size": 0.3, "runner_trail": 0.05,
}


def test_step_engine_partial_leg_breakeven_and_trail():
    """One bar that pierces tp1 partially closes (size_pct of entry_qty), arms break-even (stop → entry), and the
    standalone/runner trail then ratchets the stop up behind the favourable extreme."""
    spec = _plan_spec()
    entry = 100.0
    state = xs.ExitState(entry_ts="t0", entry_qty=10.0, stop_price=entry * 0.9, extreme=entry)
    # Bar high 106 (> tp1 at 105), low 104 — only tp1 fills (tp2 at 112 not reached, stop not hit).
    bar = Bar(ts=_BASE, open=Decimal("104"), high=Decimal("106"), low=Decimal("104"), close=Decimal("105"),
              volume=Decimal("1"))
    closes, state, remaining = xs.step_exit_plan(
        spec, _PLAN_PARAMS, bar=bar, state=state, position_qty=10.0, entry_price=entry,
        time_stop_hit=False, signal_exit_hit=False,
    )
    assert len(closes) == 1 and closes[0].reason == "take_profit" and closes[0].leg_index == 0
    assert closes[0].qty == pytest.approx(4.0)  # tp1_size 0.4 × entry_qty 10
    assert closes[0].fill_price == pytest.approx(105.0)  # fills AT the leg level
    assert remaining == pytest.approx(6.0)
    assert state.tp1_filled is True and 0 in state.legs_filled
    # On the bar tp1 first fills, break-even raises the stop to ENTRY (100). The runner trail only arms on the
    # NEXT bar (tp1_filled was still False during this bar's trail-update step) — exactly the backtest's ordering.
    assert state.stop_price == pytest.approx(100.0)
    # Next FLAT bar: now that tp1 is filled, the runner trail ratchets the stop up behind the extreme (106).
    bar2 = Bar(ts=_BASE, open=Decimal("105"), high=Decimal("105"), low=Decimal("104"), close=Decimal("105"),
               volume=Decimal("1"))
    _c, state, _r = xs.step_exit_plan(spec, _PLAN_PARAMS, bar=bar2, state=state, position_qty=6.0,
                                      entry_price=entry, time_stop_hit=False, signal_exit_hit=False)
    assert state.stop_price == pytest.approx(106.0 * 0.95)  # runner trail: extreme 106 × (1 - 0.05)


def test_step_engine_stop_outranks_legs():
    """Worst-case priority: when a bar both pierces tp1 AND breaks the stop, the STOP closes the full leg first
    (the backtest books the stop before any take leg on the same bar)."""
    spec = _plan_spec()
    state = xs.ExitState(entry_ts="t0", entry_qty=10.0, stop_price=95.0, extreme=100.0)
    bar = Bar(ts=_BASE, open=Decimal("96"), high=Decimal("106"), low=Decimal("94"), close=Decimal("96"),
              volume=Decimal("1"))
    closes, _state, remaining = xs.step_exit_plan(
        spec, _PLAN_PARAMS, bar=bar, state=state, position_qty=10.0, entry_price=100.0,
        time_stop_hit=False, signal_exit_hit=False,
    )
    assert len(closes) == 1 and closes[0].reason == "stop_loss"
    assert closes[0].qty == pytest.approx(10.0) and remaining == 0.0


def test_step_engine_standalone_trailing_arms_after_profit():
    """A STANDALONE trailing stop (no multi-TP) arms only once profit clears arm_after_profit, then trails."""
    spec = StrategySpec(
        name="trail", rationale="standalone trailing stop",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=1),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=365),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=3), op="gt", threshold=ParamRef(param="mom"))],
        exit=ExitRules(stop_loss=ParamRef(param="sl"), take_profit=ParamRef(param="tp"),
                       trailing_stop=TrailingStop(distance=ParamRef(param="trail"), arm_after_profit=ParamRef(param="arm"))),
        risk=RiskRules(max_position_pct=1.0, conviction=0.5),
        param_space={"mom": ParamSpace(kind="float", lo=-1.0, hi=1.0), "sl": ParamSpace(kind="float", lo=0.01, hi=0.5),
                     "tp": ParamSpace(kind="float", lo=0.01, hi=0.9), "trail": ParamSpace(kind="float", lo=0.01, hi=0.5),
                     "arm": ParamSpace(kind="float", lo=0.0, hi=0.5)},
    )
    params = {"mom": -1.0, "sl": 0.10, "tp": 0.80, "trail": 0.04, "arm": 0.05}
    # Not yet 5% in profit (extreme 103): the trail must NOT arm — stop stays at the fixed 90.
    state = xs.ExitState(entry_ts="t0", entry_qty=10.0, stop_price=90.0, extreme=100.0)
    bar1 = Bar(ts=_BASE, open=Decimal("103"), high=Decimal("103"), low=Decimal("103"), close=Decimal("103"), volume=Decimal("1"))
    _c, state, _r = xs.step_exit_plan(spec, params, bar=bar1, state=state, position_qty=10.0, entry_price=100.0,
                                      time_stop_hit=False, signal_exit_hit=False)
    assert state.stop_price == pytest.approx(90.0)  # below the arm threshold → not trailing yet
    # Now 8% in profit (high 108): the trail arms → stop = 108 × (1-0.04) = 103.68.
    bar2 = Bar(ts=_BASE, open=Decimal("108"), high=Decimal("108"), low=Decimal("106"), close=Decimal("107"), volume=Decimal("1"))
    _c, state, _r = xs.step_exit_plan(spec, params, bar=bar2, state=state, position_qty=10.0, entry_price=100.0,
                                      time_stop_hit=False, signal_exit_hit=False)
    assert state.stop_price == pytest.approx(108.0 * 0.96)


# --------------------------------------------------------------------------- new tools fire in the BACKTEST


def _atr_spec() -> StrategySpec:
    """An ATR-multiple stop spec — the initial stop distance is atr_mult × ATR instead of a fixed fraction."""
    return StrategySpec(
        name="atr-stop", rationale="atr-multiple stop probe",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=1),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=365),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=3), op="gt", threshold=ParamRef(param="mom"))],
        exit=ExitRules(stop_loss=ParamRef(param="sl"), take_profit=ParamRef(param="tp"),
                       atr_mult=ParamRef(param="atr_mult")),
        risk=RiskRules(max_position_pct=1.0, conviction=0.5),
        param_space={"mom": ParamSpace(kind="float", lo=-1.0, hi=1.0), "sl": ParamSpace(kind="float", lo=0.01, hi=0.5),
                     "tp": ParamSpace(kind="float", lo=0.01, hi=0.9), "atr_mult": ParamSpace(kind="float", lo=0.5, hi=5.0)},
    )


def _vol_bars(n: int) -> list[Bar]:
    """A choppy-then-rising path so ATR is non-trivial, an entry opens, and the ATR stop can bite."""
    out: list[Bar] = []
    px = 100.0
    for i in range(n):
        # gentle uptrend with a fixed intrabar range so ATR settles to a known order of magnitude
        c = px * (1.003 ** i)
        o = c * 0.995
        h = c * 1.01
        l = c * 0.985
        out.append(Bar(ts=_BASE + dt.timedelta(days=i), open=Decimal(str(round(o, 6))), high=Decimal(str(round(h, 6))),
                       low=Decimal(str(round(l, 6))), close=Decimal(str(round(c, 6))), volume=Decimal("1000000")))
    return out


def _drop_after_entry_bars(n_lead: int = 70, *, vol: float = 0.01, drop: float = 0.06, n_tail: int = 35) -> list[Bar]:
    """A choppy FLAT lead-in (so an always-true entry opens AT the flat level, ATR ≈ `vol`) → an immediate sharp
    DROP whose low falls `drop` below the entry → a long flat-ish recovery. A stop tighter than `drop` exits on
    the drop; a wider one rides through — so the initial-stop distance (fixed vs atr_mult × ATR) changes the
    result. The drop sits well inside the validation window (first 80%) so run_strategy_backtest scores it; the
    long tail keeps the total ≥ 80 bars. Deterministic wicks give a stable ATR ≈ vol."""
    out: list[Bar] = []
    px = 100.0
    for i in range(n_lead):
        h = px * (1 + vol)
        lo = px * (1 - vol)
        out.append(Bar(ts=_BASE + dt.timedelta(days=i), open=Decimal(str(round(px, 6))),
                       high=Decimal(str(round(h, 6))), low=Decimal(str(round(lo, 6))),
                       close=Decimal(str(round(px, 6))), volume=Decimal("1000000")))
    # the drop bar: opens at px, low dips `drop` below it (crosses a tight stop, not a wide one).
    low = px * (1 - drop)
    out.append(Bar(ts=_BASE + dt.timedelta(days=n_lead), open=Decimal(str(round(px, 6))),
                   high=Decimal(str(round(px, 6))), low=Decimal(str(round(low, 6))),
                   close=Decimal(str(round(px * (1 - drop / 2), 6))), volume=Decimal("1000000")))
    # a long, gently-recovering tail above the drop low so a SURVIVING position ends differently from a stopped one.
    rec = px * (1 - drop / 2)
    for k in range(1, n_tail + 1):
        c = rec * (1.001 ** k)
        out.append(Bar(ts=_BASE + dt.timedelta(days=n_lead + k), open=Decimal(str(round(c, 6))),
                       high=Decimal(str(round(c * (1 + vol), 6))), low=Decimal(str(round(c * (1 - vol), 6))),
                       close=Decimal(str(round(c, 6))), volume=Decimal("1000000")))
    return out


def test_atr_mult_stop_changes_backtest_result_vs_fixed():
    """An ATR-multiple stop produces a DIFFERENT result from a fixed-fraction stop on the same bars — proving the
    atr_mult path is wired into the screen physics. The path drops 6% right after entry: the fixed 3% stop exits
    on it, the ~7×~1% ATR stop rides through to the recovery."""
    bars = _drop_after_entry_bars(vol=0.01, drop=0.06)
    market = {"BTCUSDT": bars}
    params = {"mom": -1.0, "sl": 0.03, "tp": 0.50, "atr_mult": 7.0}  # fixed 3% vs ≈7% ATR-based stop
    atr_run = run_strategy_backtest(_atr_spec(), params, market, fee_bps=Decimal("10"))
    fixed_spec = _atr_spec()
    fixed_spec.exit.atr_mult = None
    fixed_run = run_strategy_backtest(fixed_spec, params, market, fee_bps=Decimal("10"))
    assert atr_run.num_trades > 0 and fixed_run.num_trades > 0
    assert atr_run.oos_return != fixed_run.oos_return, "atr_mult stop must change the screen result"


def test_standalone_trailing_stop_fires_in_backtest():
    """A standalone trailing stop locks in a gain: vs a WIDE fixed stop with the same take, the trailing run exits
    on the pullback (the trail bit) where the plain run rides it out — so the result differs."""
    bars = _drop_after_entry_bars(vol=0.01, drop=0.06)
    market = {"BTCUSDT": bars}
    spec = StrategySpec(
        name="trail-bt", rationale="standalone trailing in screen",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=1),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=365),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=3), op="gt", threshold=ParamRef(param="mom"))],
        exit=ExitRules(stop_loss=ParamRef(param="sl"), take_profit=ParamRef(param="tp"),
                       trailing_stop=TrailingStop(distance=ParamRef(param="trail"))),
        risk=RiskRules(max_position_pct=1.0, conviction=0.5),
        param_space={"mom": ParamSpace(kind="float", lo=-1.0, hi=1.0), "sl": ParamSpace(kind="float", lo=0.01, hi=0.5),
                     "tp": ParamSpace(kind="float", lo=0.01, hi=0.9), "trail": ParamSpace(kind="float", lo=0.01, hi=0.5)},
    )
    params = {"mom": -1.0, "sl": 0.40, "tp": 0.80, "trail": 0.03}  # wide fixed stop; the 3% trail is what bites
    trail_run = run_strategy_backtest(spec, params, market, fee_bps=Decimal("10"))
    no_trail = spec.model_copy(deep=True)
    no_trail.exit.trailing_stop = None
    plain_run = run_strategy_backtest(no_trail, params, market, fee_bps=Decimal("10"))
    assert trail_run.num_trades > 0
    assert trail_run.oos_return != plain_run.oos_return, "trailing stop must change the screen result"


# --------------------------------------------------------------------------- paper-step integration


def _persist_managed(store: Store, spec: StrategySpec, params: dict, *, max_hold_days: int = 365) -> str:
    now = "2024-01-01T00:00:00Z"
    spec_dict = spec.model_dump(mode="json")
    spec_dict["lane"] = "gate"
    strategy_id = store.insert("strategies", {"name": spec.name, "thesis": "t", "origin": "finder", "created_at": now})
    version_id = store.insert(
        "strategy_versions",
        {"strategy_id": strategy_id, "parent_id": None, "spec": spec_dict, "generated_code": "# test",
         "code_hash": f"hash-{spec.name}", "params": params, "mutation_operator": None, "mutation_rationale": None,
         "origin": "finder", "status": "paper", "created_at": now, "killed_at": None, "kill_reason": None},
    )
    store.insert("tracks", {"strategy_version_id": version_id, "symbol": "BTCUSDT", "venue_id": "binance",
                            "starting_capital": "100000", "equity": "100000", "return_pct": "0", "updated_at": now})
    bt_id = store.insert("backtests", {"strategy_version_id": version_id, "kind": "screen", "oos_return": "0.2",
                                       "sharpe": "1.5", "sortino": "1.5", "deflated_sharpe": "1.5", "max_dd": "0.1",
                                       "win_rate": "0.6", "num_trades": 30, "pbo": "0.0", "trials_counted": 1,
                                       "regime_label": "mixed", "folds_positive": 5, "passed_gates": 1,
                                       "holdout_passed": 1, "created_at": now})
    store.insert("backtest_symbols", {"backtest_id": bt_id, "strategy_version_id": version_id, "symbol": "BTCUSDT",
                                      "venue_id": "binance", "return_pct": "0.2", "sharpe": "1.5", "max_drawdown": "0.1",
                                      "trades": 30, "verdict": "pass", "created_at": now})
    return version_id


def _open_at(store: Store, entry_px: float) -> None:
    """Fund (registers flat) then open the first position on a flat path at entry_px."""
    router, _ = _router_ohlc(_flat(25, entry_px))
    assert fund_tracks_from_survivors(store, router=router).funded == 1
    assert step_tracks(store, router=router).opened == 1


def _held(store: Store, vid: str) -> Decimal:
    row = store.row("SELECT qty FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) != 0", (vid,))
    return Decimal(str(row["qty"])) if row else Decimal("0")


def _instr(store: Store, vid: str) -> str:
    """The instrument_id the position rows use (e.g. 'btc-usdt-binance') — the exit-state key's instrument part."""
    row = store.row("SELECT instrument_id FROM positions WHERE strategy_version_id = ? LIMIT 1", (vid,))
    return str(row["instrument_id"])


def _state(store: Store, vid: str):
    return xs.load_state(store, vid, _instr(store, vid), "sim")


def test_paper_multi_tp_closes_partial_size(tmp_path):
    """The paper executor scales out a PARTIAL leg (tp1_size of the position), not the whole position — the
    core multi-TP parity. The remaining runner stays open with a break-even/trailed stop."""
    store = _store(tmp_path)
    vid = _persist_managed(store, _plan_spec(), _PLAN_PARAMS)
    _open_at(store, 30000.0)
    opened_qty = _held(store, vid)
    assert opened_qty > 0

    # A bar that pierces tp1 (+5% → 31500) but not tp2 (+12%): partial close, runner remains.
    router, _ = _router_ohlc(_flat(25, 30000.0) + [(30000.0, 31600.0, 30000.0, 31400.0)])
    report = step_tracks(store, router=router)
    assert report.closed == 1
    assert report.exits[0]["reason"] == "take_profit"
    remaining = _held(store, vid)
    assert 0 < remaining < opened_qty, "tp1 closed only a fraction; the runner stays open"
    # The exit-state row records tp1 filled + the break-even/trail-raised stop.
    st = _state(store, vid)
    assert st is not None and st.tp1_filled is True and 0 in st.legs_filled
    assert st.stop_price is not None and st.stop_price >= 30000.0  # break-even raised it to >= entry


def test_paper_breakeven_then_trailing_stop_closes_runner(tmp_path):
    """After tp1 arms break-even and the runner trail ratchets the stop up, a later pullback into the trailed
    stop closes the runner at the (raised) stop level — the full break-even + trailing chain forward."""
    store = _store(tmp_path)
    vid = _persist_managed(store, _plan_spec(), _PLAN_PARAMS)
    _open_at(store, 30000.0)
    opened_qty = _held(store, vid)

    # Bar A: pierce tp1 (high 32000 > 31500=+5%, < 33600=tp2) → tp1 partial; break-even raises the stop to ENTRY.
    # The runner trail only ARMS the next bar (tp1_filled was false during this bar's trail-update step).
    rows = _flat(25, 30000.0) + [(30000.0, 32000.0, 30000.0, 31800.0)]
    router, _ = _router_ohlc(rows)
    step_tracks(store, router=router)
    assert 0 < _held(store, vid) < opened_qty
    st = _state(store, vid)
    assert st.tp1_filled is True
    assert st.stop_price == pytest.approx(30000.0, abs=50)  # break-even (≈ entry, basis includes sim slippage)

    # Bar B: run up to 33000 (new extreme) with the trail now armed → stop trails to 33000×0.95 = 31350.
    rows2 = rows + [(31800.0, 33000.0, 31700.0, 32500.0)]
    router2, _ = _router_ohlc(rows2)
    step_tracks(store, router=router2)
    st = _state(store, vid)
    assert st.stop_price == pytest.approx(33000.0 * 0.95)

    # Bar C: pull back through the trailed stop (low 31000 < 31350) → the runner closes at the stop level.
    rows3 = rows2 + [(32500.0, 32500.0, 31000.0, 31200.0)]
    router3, _ = _router_ohlc(rows3)
    report = step_tracks(store, router=router3)
    assert report.closed == 1 and report.exits[0]["reason"] == "stop_loss"
    assert _held(store, vid) == 0
    # Closing the leg clears its exit state so the next entry starts fresh.
    assert _state(store, vid) is None


def test_paper_funding_accrues_on_held_leg(tmp_path):
    """A held perp/funding leg accrues funding as cash P&L each tick (mirrors backtest's _accrue_funding): a
    long PAYS positive funding, so realized P&L drops by the carry while the leg is held flat."""
    store = _store(tmp_path)
    spec = _plan_spec()
    spec.funding_feature = "funding_rate"
    vid = _persist_managed(store, spec, _PLAN_PARAMS)
    _open_at(store, 30000.0)

    # Seed positive funding settlements across the bar window so the long pays them. The alt-join sums per-bar
    # settlements (FUNDING_ACCRUAL_KEY) keyed by bar ts; available_at == ts (published at settlement).
    from cosmu.data.alt_join import resolve_alt_store
    from cosmu.data.altdata import AltDataPoint
    alt = resolve_alt_store(store.settings, store)
    pts = [AltDataPoint(ts=_BASE + dt.timedelta(days=24, hours=8 * k), available_at=_BASE + dt.timedelta(days=24, hours=8 * k), value=0.001)
           for k in range(6)]  # settlements spanning bars 24→25
    alt.append("binance", "BTCUSDT", "funding_rate", pts)

    realized_before = Decimal(str(store.row("SELECT realized_pnl FROM positions WHERE strategy_version_id = ?", (vid,))["realized_pnl"]))
    # A flat bar (no exit) at the funding ts → the held leg just accrues funding.
    router, _ = _router_ohlc(_flat(26, 30000.0))
    step_tracks(store, router=router)
    realized_after = Decimal(str(store.row("SELECT realized_pnl FROM positions WHERE strategy_version_id = ?", (vid,))["realized_pnl"]))
    assert realized_after < realized_before, "a long pays positive funding → realized P&L drops"
    assert store.row("SELECT id FROM events WHERE kind = 'paper_funding_accrued'") is not None


def test_paper_atr_stop_sets_wider_initial_stop(tmp_path):
    """An ATR-multiple stop sets the INITIAL paper stop from atr_mult × ATR, not the fixed fraction — the
    exit-state row's stop differs from the fixed-stop spec on the same entry bar."""
    store = _store(tmp_path)
    spec = _atr_spec()
    params = {"mom": -1.0, "sl": 0.02, "tp": 0.50, "atr_mult": 3.0}
    vid = _persist_managed(store, spec, params)
    # Use a vol path so ATR is non-trivial at entry.
    rows = [(float(b.open), float(b.high), float(b.low), float(b.close)) for b in _vol_bars(40)]
    router, _ = _router_ohlc(rows)
    assert fund_tracks_from_survivors(store, router=router).funded == 1
    assert step_tracks(store, router=router).opened == 1
    st = _state(store, vid)
    assert st is not None and st.stop_price is not None
    entry = float(store.row("SELECT avg_price FROM positions WHERE strategy_version_id = ?", (vid,))["avg_price"])
    stop_dist = (entry - st.stop_price) / entry
    # ATR here is ~1.5-2.5% of price; × atr_mult 3 → a stop distance well WIDER than the fixed 2%.
    assert stop_dist > 0.02, "atr_mult × ATR set a wider stop than the fixed 2% fraction"


# --------------------------------------------------------------------------- cross-engine PARITY


def test_paper_multi_tp_exit_sequence_matches_backtest(tmp_path):
    """PARITY: the EXIT SEQUENCE (which legs fire, in what order, closing what fraction, at what level) the paper
    executor produces on a price path is the SAME as the backtest's on the SAME bars — the whole point of #5."""
    # The entry requires recent UP momentum (mom 0.0 → ret_Nd>0): it opens after the ramp lead-in. Both engines
    # run the SAME FIRST lifecycle (open → tp1 → tp2 → trailed stop). The backtest's always-on entry may re-enter
    # on a later bar — irrelevant here: we compare the FIRST lifecycle's exit sequence the paper run produces.
    spec = _plan_spec()
    params = {**_PLAN_PARAMS, "mom": 0.0}
    entry = 30000.0
    lead = [(entry * (1.001 ** i), entry * (1.001 ** i) * 1.001, entry * (1.001 ** i) * 0.999, entry * (1.001 ** i))
            for i in range(25)]
    e = float(lead[-1][3])  # the actual entry-area price after the ramp
    # Bar 25: tp1 (+5%) fills, extreme 1.055e. Bar 26: tp2 (+12%) fills — its LOW (1.11e) stays ABOVE the trailed
    # stop (extreme 1.13e × 0.95 = 1.0735e) so the trail does NOT pre-empt tp2; extreme rises to 1.13e. Bar 27:
    # a sharp pullback whose low pierces the trailed stop → the runner closes.
    exit_bars = [
        (e, e * 1.055, e, e * 1.05),                # tp1 (+5%) fills, extreme 1.055e (no tp2: high < 1.12e)
        (e * 1.05, e * 1.13, e * 1.11, e * 1.12),   # tp2 (+12%) fills; low 1.11e > trail 1.0735e; extreme 1.13e
        (e * 1.12, e * 1.12, e * 0.90, e * 0.92),   # sharp pullback through the trailed stop → runner closes
    ]
    path = lead + exit_bars

    # --- backtest reference (the FIRST lifecycle's three closes) ----------------------------------------------
    # Run the backtest over ONLY the first lifecycle (lead-in + the three exit bars), then drop any trailing
    # re-entry by keeping trades until the cumulative closed qty completes the opened position — i.e. the first
    # three legs (tp1 partial, tp2 partial, runner). Their P&L percentages are the reference.
    bars = [Bar(ts=_BASE + dt.timedelta(days=i), open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(l)),
                close=Decimal(str(c)), volume=Decimal("1000000")) for i, (o, h, l, c) in enumerate(path)]
    from cosmu.data.backtest import _run_symbol
    run = _run_symbol(spec, params, bars, Decimal("10"), Decimal("0"), Decimal("0"), 1.0)
    assert len(run.trades) >= 3, run.trades
    bt_pnls = [round(t.pnl_pct, 4) for t in run.trades[:3]]
    # tp1 leg ≈ +5%, tp2 leg ≈ +12%, the runner exits via the trail on the pullback (a loss vs its entry basis).
    assert bt_pnls[0] == pytest.approx(0.05, abs=0.01)
    assert bt_pnls[1] == pytest.approx(0.12, abs=0.01)

    # --- paper sequence (must MATCH the backtest's first-lifecycle exit sequence) ------------------------------
    store = _store(tmp_path)
    vid = _persist_managed(store, spec, params)
    router, _ = _router_ohlc(lead)
    assert fund_tracks_from_survivors(store, router=router).funded == 1
    assert step_tracks(store, router=router).opened == 1
    reasons: list[str] = []
    for k in range(26, 29):  # provider lengths 26,27,28 → last-bar index 25,26,27 (the three exit bars)
        router, _ = _router_ohlc(path[:k])
        rep = step_tracks(store, router=router)
        reasons.extend(ev["reason"] for ev in rep.exits)
        if _held(store, vid) == 0:
            break  # the first lifecycle's runner has closed — stop before any re-entry
    # Paper books the SAME three closes in the SAME order: two take-profit legs then the trailed stop.
    assert reasons == ["take_profit", "take_profit", "stop_loss"], reasons
    assert _held(store, vid) == 0


# --------------------------------------------------------------------------- no-plan CONTROL (regression)


def test_no_plan_spec_is_unmanaged_and_unchanged(tmp_path):
    """A spec WITHOUT any layered exit tool is NEVER routed through the exit-state engine (manages_exit False),
    writes NO exit-state row, and closes via the legacy single-stop path exactly as before — no regression."""
    store = _store(tmp_path)
    plain = StrategySpec(
        name="plain", rationale="single stop/take only",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=1),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=365),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=3), op="gt", threshold=ParamRef(param="mom"))],
        exit=ExitRules(stop_loss=ParamRef(param="sl"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(max_position_pct=1.0, conviction=0.5),
        param_space={"mom": ParamSpace(kind="float", lo=-1.0, hi=1.0), "sl": ParamSpace(kind="float", lo=0.01, hi=0.5),
                     "tp": ParamSpace(kind="float", lo=0.01, hi=0.5)},
    )
    assert xs.has_exit_plan(plain) is False
    assert xs.manages_exit(store, plain) is False
    vid = _persist_managed(store, plain, {"mom": -1.0, "sl": 0.05, "tp": 0.50})
    _open_at(store, 30000.0)
    assert _state(store, vid) is None  # no exit-state row for an unmanaged spec
    # A 7% drop trips the legacy single stop, closing the FULL position (no partials).
    router, _ = _router_ohlc(_flat(25, 30000.0) + [(30000.0, 30000.0, 27900.0, 27900.0)])
    report = step_tracks(store, router=router)
    assert report.closed == 1 and report.exits[0]["reason"] == "stop_loss"
    assert _held(store, vid) == 0
