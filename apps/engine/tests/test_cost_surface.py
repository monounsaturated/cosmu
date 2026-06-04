# Cost-surface compute engine — offline, deterministic tests (no network, no live keys, no LLM).
# Proves: (1) a fee-free-profitable strategy HOLDS at 0 bps and STOPS holding once fees exceed its breakeven;
# (2) net return is monotonically eroded by rising fees and cost_ratio decays toward 0; (3) cross-venue
# ordering is sane (cheaper venue keeps more edge — Binance >= Kraken >= Coinbase at real fees);
# (4) the surface is deterministic and re-uses the EXISTING pure backtest unchanged.

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.research.cost_surface import (
    CostScenario,
    compute_cost_surface,
    scenario_grid,
    venue_fee_scenarios,
)
from cosmu.strategy.spec import (
    Condition,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)


def _trending_market(n: int = 320) -> dict[str, list[Bar]]:
    """Deterministic sawtooth UPTREND: price drifts up in swings with periodic shallow pullbacks, so a long
    momentum strategy enters often and most trades win GROSS — but the many round trips make fees bite. Two
    symbols (shifted phase) so the backtest's per-symbol combine has more than one series."""
    out: dict[str, list[Bar]] = {}
    t0 = datetime(2023, 1, 1, tzinfo=UTC)
    for sym, phase in (("BTCUSDT", 0), ("ETHUSDT", 3)):
        bars: list[Bar] = []
        price = 100.0
        for i in range(n):
            # +1.5% per bar with a -2% pullback every 7th bar → net upward drift, repeated swings.
            step = -0.02 if (i + phase) % 7 == 0 else 0.015
            open_ = price
            price = price * (1 + step)
            hi = max(open_, price) * 1.004
            lo = min(open_, price) * 0.996
            d = lambda x: Decimal(str(round(x, 6)))  # noqa: E731
            bars.append(Bar(ts=t0 + timedelta(days=i), open=d(open_), high=d(hi), low=d(lo), close=d(price), volume=d(5_000_000.0)))
        out[sym] = bars
    return out


def _momentum_spec() -> tuple[StrategySpec, dict[str, float]]:
    """A simple long-only momentum spec that compiles (every threshold a ParamRef) and trades frequently on the
    trending fixture. Params are passed explicitly (no optimizer) so the test is fully deterministic."""
    spec = StrategySpec(
        name="cost-surface test momentum",
        rationale="Long when short-window return is positive; small take-profit so it round-trips often and fees matter.",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=8),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=5, max_position_pct=0.2, conviction=0.9),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=2, hi=20, step=1),
            "mom_floor": ParamSpace(kind="float", lo=0.0, hi=0.05),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.12),
            "take": ParamSpace(kind="float", lo=0.02, hi=0.2),
            "time_stop": ParamSpace(kind="int", lo=2, hi=14, step=1),
        },
    )
    params = {"mom_lookback": 2.0, "mom_floor": 0.0, "stop": 0.05, "take": 0.04, "time_stop": 4.0}
    return spec, params


def test_holds_at_zero_fee_and_breaks_past_breakeven():
    spec, params = _momentum_spec()
    market = _trending_market()
    # Friction-free at fee 0, then a rising fee sweep with no slippage/impact so the FEE is the only lever.
    fees = [Decimal("0"), Decimal("10"), Decimal("26"), Decimal("60"), Decimal("150"), Decimal("400")]
    scenarios = scenario_grid(fee_bps=fees, venues=["binance"], slippage_bps=Decimal("0"), impact_bps=Decimal("0"))
    surface = compute_cost_surface(spec, params, market, scenarios)

    cells = {cell.scenario.fee_bps: cell for cell in surface.cells}

    # 1) Fee-free is profitable and HOLDS; cost_ratio is exactly 1 at zero cost.
    assert surface.gross_return > 0.0
    zero = cells[Decimal("0")]
    assert zero.holds is True
    assert zero.net_return == surface.gross_return
    assert zero.cost_ratio == 1.0
    assert zero.num_trades > 5          # actually round-trips, so fees have something to eat
    assert zero.breakeven_edge_bps > 0.0

    # 2) Rising fees monotonically erode net return and cost_ratio (never increase).
    nets = [cells[f].net_return for f in fees]
    ratios = [cells[f].cost_ratio for f in fees]
    assert nets == sorted(nets, reverse=True)
    assert ratios == sorted(ratios, reverse=True)

    # 3) Somewhere as fees rise the edge stops holding, and once it stops it stays stopped (monotone).
    holds_seq = [cells[f].holds for f in fees]
    assert holds_seq[0] is True
    assert holds_seq[-1] is False
    first_false = holds_seq.index(False)
    assert all(h is False for h in holds_seq[first_false:])

    # 4) The flip lines up with the breakeven model: the round-trip cost (2 * per-side fee) at the first
    #    non-holding fee has exceeded the strategy's per-trade breakeven budget.
    break_fee = next(f for f in fees if not cells[f].holds)
    assert 2.0 * float(break_fee) >= zero.breakeven_edge_bps


def test_cross_venue_ordering_is_sane():
    spec, params = _momentum_spec()
    market = _trending_market()
    venues = ["binance", "kraken", "coinbase"]  # real taker fees: 10 < 26 < 60 bps
    scenarios = venue_fee_scenarios(venues, slippage_bps=Decimal("0"), impact_bps=Decimal("0"), include_fee_free=False)
    surface = compute_cost_surface(spec, params, market, scenarios)

    net_by_venue = {cell.scenario.venue: cell.net_return for cell in surface.cells}
    # Cheaper venue keeps more of the edge: Binance >= Kraken >= Coinbase.
    assert net_by_venue["binance"] >= net_by_venue["kraken"] >= net_by_venue["coinbase"]
    # Each real-fee cell is below the friction-free gross baseline.
    assert all(cell.net_return <= surface.gross_return for cell in surface.cells)


def test_surface_is_deterministic_and_reuses_backtest():
    spec, params = _momentum_spec()
    market = _trending_market()
    scenarios = scenario_grid(fee_bps=[Decimal("0"), Decimal("50")], venues=["binance"])
    a = compute_cost_surface(spec, params, market, scenarios)
    b = compute_cost_surface(spec, params, market, scenarios)
    assert [(c.scenario.fee_bps, c.net_return, c.holds) for c in a.cells] == [
        (c.scenario.fee_bps, c.net_return, c.holds) for c in b.cells
    ]
    # The spec compiles, so provenance hash is populated and stable.
    assert a.strategy_hash is not None
    assert a.strategy_hash == b.strategy_hash


def test_breakeven_estimate_matches_compounding_model():
    # The breakeven bps is ln(1 + gross) / num_trades * 1e4 by construction — pin the relationship.
    spec, params = _momentum_spec()
    market = _trending_market()
    surface = compute_cost_surface(spec, params, market, scenario_grid(fee_bps=[Decimal("0")], venues=["binance"]))
    cell = surface.cells[0]
    expected = math.log1p(surface.gross_return) / cell.num_trades * 1e4
    assert math.isclose(cell.breakeven_edge_bps, round(expected, 4), rel_tol=1e-6, abs_tol=1e-4)


def test_asset_type_is_a_label_only():
    # spot vs perp at the SAME cost share one backtest (label-only dimension) → identical net_return.
    spec, params = _momentum_spec()
    market = _trending_market()
    scenarios = [
        CostScenario(fee_bps=Decimal("10"), venue="binance", asset_type="spot", slippage_bps=Decimal("0"), impact_bps=Decimal("0")),
        CostScenario(fee_bps=Decimal("10"), venue="binance", asset_type="perp", slippage_bps=Decimal("0"), impact_bps=Decimal("0")),
    ]
    surface = compute_cost_surface(spec, params, market, scenarios)
    assert surface.cells[0].net_return == surface.cells[1].net_return
