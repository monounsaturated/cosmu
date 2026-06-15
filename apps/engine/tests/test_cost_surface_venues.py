# Per-venue MARKET DEPTH realism — offline, deterministic (no network, no keys, no LLM).
# Proves: (1) every venue carries a real, positive slippage+impact and sane cross-venue depth ordering
# (a thin event book costs more than a deep spot book; liquid equity costs least); (2) Venue.cost_inputs pairs
# a venue's fee with its OWN depth; (3) venue_fee_scenarios uses per-venue depth by default, an explicit
# override still wins for all venues (back-compat with the fee-only sweep), and per_venue_depth=False restores
# the legacy 5/50; (4) the depth actually flows into the backtest — a thinner book erodes strictly more net
# return at the SAME (zero) fee, so "perf under venue-1 vs venue-2" reflects depth, not just headline fees.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.research.cost_surface import compute_cost_surface, venue_fee_scenarios
from cosmu.spine.venue import default_catalog
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
    """Deterministic sawtooth uptrend over two phase-shifted symbols, so a long-momentum spec round-trips often
    and transaction cost (fee AND depth) has something to eat."""
    out: dict[str, list[Bar]] = {}
    t0 = datetime(2023, 1, 1, tzinfo=UTC)
    for sym, phase in (("BTCUSDT", 0), ("ETHUSDT", 3)):
        bars: list[Bar] = []
        price = 100.0
        for i in range(n):
            step = -0.02 if (i + phase) % 7 == 0 else 0.015
            open_ = price
            price = price * (1 + step)
            d = lambda x: Decimal(str(round(x, 6)))  # noqa: E731
            bars.append(
                Bar(
                    ts=t0 + timedelta(days=i),
                    open=d(open_),
                    high=d(max(open_, price) * 1.004),
                    low=d(min(open_, price) * 0.996),
                    close=d(price),
                    volume=d(5_000_000.0),
                )
            )
        out[sym] = bars
    return out


def _momentum_spec() -> tuple[StrategySpec, dict[str, float]]:
    spec = StrategySpec(
        name="venue-depth test momentum",
        rationale="Long when short-window return is positive; small take so it round-trips often and cost bites.",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=8),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor"))],
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


def test_every_venue_has_market_depth_and_provenance() -> None:
    cat = default_catalog()
    for v in cat.venues:
        assert v.slippage_bps > 0, f"{v.id} has no half-spread"
        assert v.impact_bps > 0, f"{v.id} has no impact coefficient"
    # A thin event book (Polymarket long-tail) costs MORE depth than a deep spot book; liquid equity the least.
    assert cat.venue("polymarket").slippage_bps > cat.venue("binance").slippage_bps
    assert cat.venue("ibkr").slippage_bps < cat.venue("coinbase").slippage_bps
    # Honest (non-enforced) provenance metadata is populated where it matters.
    okx = cat.venue("okx")
    assert okx.region and okx.legal_entity and "Malta" in okx.legal_entity


def test_cost_inputs_pairs_fee_with_its_own_depth() -> None:
    binance = default_catalog().venue("binance")
    taker, slip, impact = binance.cost_inputs()
    assert taker == binance.effective_fee()[1]
    assert slip == binance.slippage_bps
    assert impact == binance.impact_bps


def test_scenarios_use_per_venue_depth_by_default() -> None:
    cat = default_catalog()
    scen = {s.venue: s for s in venue_fee_scenarios(["binance", "polymarket"], include_fee_free=False)}
    assert scen["binance"].slippage_bps == cat.venue("binance").slippage_bps
    assert scen["polymarket"].slippage_bps == cat.venue("polymarket").slippage_bps
    # The two venues genuinely differ in depth — they are not collapsed to one global assumption.
    assert scen["polymarket"].slippage_bps != scen["binance"].slippage_bps
    assert scen["polymarket"].impact_bps != scen["binance"].impact_bps


def test_explicit_depth_override_wins_for_all_venues() -> None:
    # Back-compat with the fee-only sweep (test_cost_surface.py): explicit 0/0 isolates the fee lever everywhere.
    scen = venue_fee_scenarios(
        ["binance", "polymarket"], slippage_bps=Decimal("0"), impact_bps=Decimal("0"), include_fee_free=False
    )
    assert all(s.slippage_bps == Decimal("0") and s.impact_bps == Decimal("0") for s in scen)


def test_per_venue_depth_false_restores_legacy_defaults() -> None:
    scen = venue_fee_scenarios(["polymarket"], per_venue_depth=False, include_fee_free=False)
    assert scen[0].slippage_bps == Decimal("5") and scen[0].impact_bps == Decimal("50")


def test_depth_actually_flows_into_the_backtest() -> None:
    """At the SAME (zero) fee, the only difference between a depth-free run and Polymarket's real thin-book depth
    is slippage+impact — so the thin book must erode strictly more net return. This is what makes "perf under
    venue-1 vs venue-2" honest about market structure, not just headline fees."""
    spec, params = _momentum_spec()
    market = _trending_market()
    depth_free = venue_fee_scenarios(
        ["polymarket"], slippage_bps=Decimal("0"), impact_bps=Decimal("0"), include_fee_free=False
    )
    real_depth = venue_fee_scenarios(["polymarket"], include_fee_free=False)  # per-venue depth ON by default
    depth_free_net = compute_cost_surface(spec, params, market, depth_free).cells[0].net_return
    real_depth_net = compute_cost_surface(spec, params, market, real_depth).cells[0].net_return
    assert real_depth_net < depth_free_net
