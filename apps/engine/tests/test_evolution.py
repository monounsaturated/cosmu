import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.backtest import run_strategy_backtest
from cosmu.data.market import Bar
from cosmu.evolution import mutator
from cosmu.evolution.loop import FarmLoop, fit_params
from cosmu.evolution.seeder import seed_population
from cosmu.knowledge.store import Store
from cosmu.spine.venue import default_catalog
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.pine import translate_pine
from cosmu.strategy.static_check import validate_spec


class FixtureProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.calls: list[tuple[str, str, int]] = []

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        self.calls.append((symbol, timeframe, limit))
        return self.bars[-limit:]


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/evo.sqlite3"))


def _fixture_bars(count: int = 420, start: Decimal = Decimal("100")) -> list[Bar]:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    price = start
    bars: list[Bar] = []
    for idx in range(count):
        cycle = Decimal(idx % 18)
        move = Decimal("0.012") if cycle < 9 else Decimal("-0.009")
        if idx % 53 == 0:
            move -= Decimal("0.035")
        open_ = price
        close = (price * (Decimal("1") + move)).quantize(Decimal("0.0001"))
        high = max(open_, close) * Decimal("1.006")
        low = min(open_, close) * Decimal("0.994")
        bars.append(
            Bar(
                ts=ts + timedelta(days=idx),
                open=open_,
                high=high.quantize(Decimal("0.0001")),
                low=low.quantize(Decimal("0.0001")),
                close=close,
                volume=Decimal("1000") + Decimal(idx),
            )
        )
        price = close
    return bars


def test_seed_population_is_diverse_and_valid():
    specs = seed_population()
    assert len(specs) >= 4
    names = {s.name for s in specs}
    assert len(names) == len(specs)  # no duplicates
    for spec in specs:
        assert validate_spec(spec) == []


def test_every_mutation_operator_keeps_spec_valid_and_compilable():
    rng = random.Random(0)
    parents = seed_population()
    for op in mutator.EXPLOIT_OPERATORS:
        child = op(parents[0], rng)
        assert validate_spec(child.spec) == [], f"{op.__name__} produced invalid spec"
        compile_spec(child.spec, fit_params(child.spec))  # must not raise


def test_wildcards_and_crossover_stay_valid():
    rng = random.Random(1)
    parents = seed_population()
    for _ in range(40):
        child = mutator.wildcard(parents, rng)
        assert validate_spec(child.spec) == [], f"{child.operator} invalid"
    cross = mutator.crossover(parents[0], parents[1], rng)
    assert validate_spec(cross.spec) == []


def test_pine_import_lifts_thresholds_into_param_space():
    pine = """
    //@version=5
    strategy("RSI + MA cross", overlay=true)
    rsiVal = ta.rsi(close, 14)
    fast = ta.sma(close, 10)
    slow = ta.ema(close, 30)
    longCondition = ta.crossover(fast, slow) and rsiVal < 35
    strategy.exit("x", stop=0.05, limit=0.12)
    """
    tr = translate_pine(pine)
    # spec must be valid and free of magic-number thresholds (all ParamRefs)
    assert validate_spec(tr.spec) == []
    assert tr.spec.param_space, "expected lifted params"
    assert tr.indicators, "expected indicators detected"
    # the hardcoded rsi threshold 35 and stop/take were lifted into the search space
    assert any(round(v) == 35 for v in tr.lifted_params.values())


def test_pine_garbage_input_still_yields_valid_spec():
    tr = translate_pine("this is not pine at all")
    assert validate_spec(tr.spec) == []
    assert tr.spec.entry  # always non-empty fallback


def test_cohort_run_is_deterministic_and_kills_most(tmp_path):
    store = _store(tmp_path)
    provider = FixtureProvider(_fixture_bars())
    loop = FarmLoop(settings=store.settings, store=store, market_data=provider)
    a = loop.run_cohort(seed=7, cohort_size=120)
    assert a.generated > 0
    assert a.kill_rate >= 0.70  # real bars still gate most candidates in this fixture
    # graveyard rows all carry a reason
    for row in a.graveyard:
        assert row.reasons
    assert provider.calls

    store_b = _store(tmp_path / "b")
    loop_b = FarmLoop(settings=store_b.settings, store=store_b, market_data=FixtureProvider(_fixture_bars()))
    b = loop_b.run_cohort(seed=7, cohort_size=120)
    assert (a.generated, a.passed, a.killed) == (b.generated, b.passed, b.killed)


def test_pine_scripts_enter_the_cohort(tmp_path):
    store = _store(tmp_path)
    loop = FarmLoop(settings=store.settings, store=store, market_data=FixtureProvider(_fixture_bars()))
    summary = loop.run_cohort(seed=3, cohort_size=40, pine_scripts=["strategy('x')\nrsiVal = ta.rsi(close, 14)\nlongCondition = rsiVal < 30"])
    assert summary.pine_imported == 1


def _seed_venues(store: Store) -> None:
    for v in default_catalog().venues:
        store.insert(
            "venues",
            {"id": v.id, "name": v.name, "kind": v.kind, "adapter": v.adapter, "fee_schedule": "{}", "constraints": "{}", "enabled": int(v.enabled)},
        )


def test_universe_gate_filters_binance_symbols():
    from cosmu.evolution.loop import _binance_symbols

    spec = seed_population()[0]
    assert "crypto" in spec.universe.asset_classes and "binance" in spec.universe.venues
    assert _binance_symbols(spec, {"binance"}, {"crypto"})  # enabled → symbols
    assert _binance_symbols(spec, set(), set()) == []  # globally disabled → none
    assert _binance_symbols(spec, {"ibkr"}, {"equity"}) == []  # only other venues enabled


def test_disabling_binance_starves_the_cohort(tmp_path):
    from cosmu.spine.universe import enabled_universe, has_live_data, set_venue_enabled

    store = _store(tmp_path)
    _seed_venues(store)
    set_venue_enabled(store, "binance", False)

    venues, classes = enabled_universe(store)
    assert "binance" not in venues and "crypto" not in classes
    assert has_live_data(store) is False

    loop = FarmLoop(settings=store.settings, store=store, market_data=FixtureProvider(_fixture_bars()))
    summary = loop.run_cohort(seed=7, cohort_size=40)
    assert summary.passed == 0  # no enabled data path → no trades → nothing survives


def test_set_venue_enabled_keeps_one_venue_and_audits(tmp_path):
    from cosmu.spine.universe import set_venue_enabled

    store = _store(tmp_path)
    _seed_venues(store)
    set_venue_enabled(store, "ibkr", False)
    set_venue_enabled(store, "polymarket", False)

    try:
        set_venue_enabled(store, "binance", False)
        raise AssertionError("expected refusal to disable the last venue")
    except ValueError:
        pass

    events = store.rows("SELECT kind, ref_id FROM events WHERE kind = 'venue_toggle_changed'")
    assert {e["ref_id"] for e in events} == {"ibkr", "polymarket"}


def test_real_bar_backtest_charges_binance_fees():
    spec = seed_population()[0]
    params = fit_params(spec)
    bars = _fixture_bars()
    venue = default_catalog().venue("binance")

    with_fees = run_strategy_backtest(spec, params, {"BTCUSDT": bars}, fee_bps=venue.taker_fee_bps)
    no_fees = run_strategy_backtest(spec, params, {"BTCUSDT": bars}, fee_bps=Decimal("0"))

    assert with_fees.num_trades > 0
    assert with_fees.oos_return < no_fees.oos_return
