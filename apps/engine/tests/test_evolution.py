import random

from cosmu.config.settings import Settings
from cosmu.evolution import mutator
from cosmu.evolution.loop import FarmLoop, fit_params
from cosmu.evolution.seeder import seed_population
from cosmu.knowledge.store import Store
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.pine import translate_pine
from cosmu.strategy.static_check import validate_spec


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/evo.sqlite3"))


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
    loop = FarmLoop(settings=store.settings, store=store)
    a = loop.run_cohort(seed=7, cohort_size=120)
    assert a.generated > 0
    assert a.kill_rate >= 0.85  # explore wide, gate hard
    assert a.passed >= 1
    # graveyard rows all carry a reason
    for row in a.graveyard:
        assert row.reasons

    store_b = _store(tmp_path / "b")
    loop_b = FarmLoop(settings=store_b.settings, store=store_b)
    b = loop_b.run_cohort(seed=7, cohort_size=120)
    assert (a.generated, a.passed, a.killed) == (b.generated, b.passed, b.killed)


def test_pine_scripts_enter_the_cohort(tmp_path):
    store = _store(tmp_path)
    loop = FarmLoop(settings=store.settings, store=store)
    summary = loop.run_cohort(seed=3, cohort_size=40, pine_scripts=["strategy('x')\nrsiVal = ta.rsi(close, 14)\nlongCondition = rsiVal < 30"])
    assert summary.pine_imported == 1
