# The keystone for leading-signal strategies: alt-data (funding_rate, …) joined point-in-time into the
# screen backtest. Without it, alt features read None and their conditions can never fire. These tests pin
# (1) the as-of join never looks ahead, and (2) a funding-gated spec trades ONLY when the join is supplied.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.data.altdata import AltDataPoint
from cosmu.data.backtest import align_asof, run_strategy_backtest
from cosmu.data.market import Bar
from cosmu.research.fixtures import edge_bearing_screen_market
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


def _d(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=UTC)


def _bar(day: int) -> Bar:
    return Bar(ts=_d(day), open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"))


def test_align_asof_is_point_in_time_no_lookahead():
    bars = [_bar(d) for d in (1, 2, 3, 4)]
    points = [
        AltDataPoint(ts=_d(1), available_at=_d(2), value=0.001),  # observed day1 but only KNOWN day2
        AltDataPoint(ts=_d(3), available_at=_d(3), value=0.005),
    ]
    aligned = align_asof(points, bars)
    assert _d(1).isoformat() not in aligned          # day1: nothing known yet — never the day-2-published value
    assert aligned[_d(2).isoformat()] == 0.001        # day2: first point now available
    assert aligned[_d(3).isoformat()] == 0.005        # day3: newer point
    assert aligned[_d(4).isoformat()] == 0.005        # day4: carries the last known value forward


def _funding_gated_spec() -> StrategySpec:
    return StrategySpec(
        name="funding-gated-test",
        rationale="momentum that only fires while funding is below a ceiling — needs the alt join to trade",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=7),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
            Condition(feature=FeatureRef(name="funding_rate"), op="lt", threshold=ParamRef(param="funding_ceiling")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=5, hi=20),
            "mom_floor": ParamSpace(kind="float", lo=-1.0, hi=1.0),
            "funding_ceiling": ParamSpace(kind="float", lo=0.0, hi=1.0),
            "stop": ParamSpace(kind="float", lo=0.05, hi=0.2),
            "tp": ParamSpace(kind="float", lo=0.05, hi=0.3),
        },
    )


def test_funding_gate_trades_only_with_alt_join():
    spec = _funding_gated_spec()
    params = {"mom_lookback": 10, "mom_floor": -0.5, "funding_ceiling": 0.01, "stop": 0.1, "tp": 0.2}
    bars = edge_bearing_screen_market(n=200)["BTCUSDT"]
    market = {"BTCUSDT": bars}
    fee = Decimal("10")

    # Funding sits below the ceiling on every bar → the funding condition can pass when joined.
    alt = {"BTCUSDT": {"funding_rate": {b.ts.isoformat(): 0.0001 for b in bars}}}

    with_alt = run_strategy_backtest(spec, params, market, fee_bps=fee, alt_by_symbol=alt)
    without_alt = run_strategy_backtest(spec, params, market, fee_bps=fee)  # funding_rate → None

    assert without_alt.num_trades == 0, "alt feature must be unsatisfiable without the join (prior behaviour)"
    assert with_alt.num_trades > 0, "the point-in-time alt join must make the funding-gated strategy tradable"


def _multi_alt_spec() -> StrategySpec:
    """Momentum gated by BOTH funding (calm) AND fear_greed (crowd fearful) — needs two alt features joined,
    not just funding. Proves the screen now evaluates the whole registry, not a single hand-wired key."""
    return StrategySpec(
        name="funding-and-fear-test",
        rationale="buy momentum only while funding is calm and the crowd is fearful — two leading signals",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=7),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
            Condition(feature=FeatureRef(name="funding_rate"), op="lt", threshold=ParamRef(param="funding_ceiling")),
            Condition(feature=FeatureRef(name="fear_greed"), op="lt", threshold=ParamRef(param="greed_ceiling")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=5, hi=20),
            "mom_floor": ParamSpace(kind="float", lo=-1.0, hi=1.0),
            "funding_ceiling": ParamSpace(kind="float", lo=0.0, hi=1.0),
            "greed_ceiling": ParamSpace(kind="float", lo=0.0, hi=100.0),
            "stop": ParamSpace(kind="float", lo=0.05, hi=0.2),
            "tp": ParamSpace(kind="float", lo=0.05, hi=0.3),
        },
    )


def test_multi_alt_feature_spec_trades_with_join():
    """A spec using TWO alt features (funding_rate + fear_greed) trades only once BOTH are joined PIT —
    the core of this change: the backtest evaluates every joined alt feature, not just funding."""
    spec = _multi_alt_spec()
    params = {"mom_lookback": 10, "mom_floor": -0.5, "funding_ceiling": 0.01, "greed_ceiling": 50.0, "stop": 0.1, "tp": 0.2}
    bars = edge_bearing_screen_market(n=200)["BTCUSDT"]
    market = {"BTCUSDT": bars}
    fee = Decimal("10")

    alt = {
        "BTCUSDT": {
            "funding_rate": {b.ts.isoformat(): 0.0001 for b in bars},  # calm funding, below the ceiling
            "fear_greed": {b.ts.isoformat(): 20.0 for b in bars},      # crowd fear (20 < 50 greed ceiling)
        }
    }

    with_alt = run_strategy_backtest(spec, params, market, fee_bps=fee, alt_by_symbol=alt)
    without_alt = run_strategy_backtest(spec, params, market, fee_bps=fee)
    # Drop only the fear_greed leg → the spec must again be untradable (the second alt feature is load-bearing).
    only_funding = {"BTCUSDT": {"funding_rate": alt["BTCUSDT"]["funding_rate"]}}
    without_fg = run_strategy_backtest(spec, params, market, fee_bps=fee, alt_by_symbol=only_funding)

    assert without_alt.num_trades == 0, "both alt conditions must be unsatisfiable without the join"
    assert without_fg.num_trades == 0, "fear_greed must be load-bearing — funding alone can't satisfy the spec"
    assert with_alt.num_trades > 0, "the PIT join of funding_rate + fear_greed must make the spec tradable"


class _FakeAltStore:
    """Minimal AltDataStore stand-in: returns the canned full history for a (provider, key, metric)."""

    def __init__(self, series: dict[tuple[str, str, str], list[AltDataPoint]]) -> None:
        self.series = series

    def read_all(self, provider: str, key: str, metric: str) -> list[AltDataPoint]:
        return self.series.get((provider, key, metric), [])


def test_farmloop_alt_join_is_registry_driven_and_wires_fear_greed():
    """FarmLoop._alt_by_symbol must build the join for EVERY registered alt feature a spec uses — proving
    it reads the feature_registry (not the old single-funding key list). fear_greed is market-wide, so this
    also exercises StoreBackedAltProvider's MARKET keying end-to-end."""
    from cosmu.config.settings import Settings
    from cosmu.evolution.loop import FarmLoop
    from cosmu.knowledge.store import Store

    spec = _multi_alt_spec()
    bars = edge_bearing_screen_market(n=60)["BTCUSDT"]
    # funding_rate → per-symbol (binance, BTCUSDT); fear_greed → market-wide (alternative.me, MARKET).
    series = {
        ("binance", "BTCUSDT", "funding_rate"): [AltDataPoint(ts=b.ts, available_at=b.ts, value=0.0001) for b in bars],
        ("alternative.me", "MARKET", "fear_greed"): [AltDataPoint(ts=b.ts, available_at=b.ts, value=20.0) for b in bars],
    }

    store = Store(Settings(database_url="sqlite:///:memory:"))
    loop = FarmLoop(settings=store.settings, store=store)
    loop._cache["alt_store"] = _FakeAltStore(series)

    joined = loop._alt_by_symbol(spec, {"BTCUSDT": bars})
    assert joined is not None
    assert set(joined["BTCUSDT"]) == {"funding_rate", "fear_greed"}, "both registered alt features must be wired"
    assert joined["BTCUSDT"]["fear_greed"][bars[-1].ts.isoformat()] == 20.0

    # And the registry-derived universe is the whole alt vocabulary, not a 1-item list. The join logic now lives
    # in the shared cosmu.data.alt_join (one source of truth for the loop screen AND the finder sweep).
    from cosmu.data.alt_join import alt_feature_universe

    universe = alt_feature_universe()
    assert {"funding_rate", "fear_greed"} <= universe
    assert "ret_Nd" not in universe, "price/TA features are computed from bars, never alt-joined"
    assert len(universe) >= 20


def test_every_enabled_feature_is_routable_or_computed():
    """The registry↔route guard. Every ENABLED registry feature must be EITHER store-routed (a provider can
    populate it point-in-time) OR computed (bar-TA + cohort-computed, the PRICE_FEATURES set). A feature that is
    neither is dead weight: referenced by name but never populated — a silent no-op (the exact failure class
    behind the fake tier-0 exchange_netflow and the unwired equity stubs). 0 unaccounted ⇔ no dead features."""
    from cosmu.config.feature_registry import feature_names
    from cosmu.data.backtest import PRICE_FEATURES
    from cosmu.data.providers.store import _STORE_PROVIDER_OF

    unaccounted = feature_names() - (PRICE_FEATURES | set(_STORE_PROVIDER_OF))
    assert not unaccounted, f"no route, not bar-computed: {unaccounted}"
