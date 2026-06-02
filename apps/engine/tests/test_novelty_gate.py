# intent: test novelty/complexity gate — structural distance, complexity, dead-end avoidance, monoculture prevention.

from cosmu.knowledge.memory import (
    GraveyardMemory,
    complexity_score,
    novelty_gate,
    structural_distance,
)
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store


def _store(tmp_path):
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/novelty.sqlite3", openrouter_api_key=None))
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


def _spec(features, bar_size="1d", name="test"):
    entry = [
        Condition(
            feature=FeatureRef(name=f),
            op="gt",
            threshold=ParamRef(param=f"th_{f}"),
        )
        for f in features
    ]
    ps = {f"th_{f}": ParamSpace(kind="float", lo=0.0, hi=1.0) for f in features}
    ps["sl"] = ParamSpace(kind="float", lo=0.01, hi=0.1)
    ps["tp"] = ParamSpace(kind="float", lo=0.01, hi=0.2)
    return StrategySpec(
        name=name,
        rationale="test",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"]),
        horizon=Horizon(bar_size=bar_size, min_hold_days=1, max_hold_days=14),
        entry=entry,
        exit=ExitRules(stop_loss=ParamRef(param="sl"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space=ps,
    )


def test_structural_distance_identical():
    a = _spec(["rsi", "adx"])
    b = _spec(["rsi", "adx"])
    assert structural_distance(a, b) == 0.0


def test_structural_distance_disjoint():
    a = _spec(["rsi", "adx"])
    b = _spec(["bb_z", "vol_realized"])
    assert structural_distance(a, b) == 1.0


def test_structural_distance_partial_overlap():
    a = _spec(["rsi", "adx", "bb_z"])
    b = _spec(["rsi", "adx", "vol_realized"])
    d = structural_distance(a, b)
    assert 0 < d < 1


def test_structural_distance_bar_size_penalty():
    a = _spec(["rsi", "adx"], bar_size="1d")
    b = _spec(["rsi", "adx"], bar_size="4h")
    assert structural_distance(a, b) == 0.15


def test_complexity_score():
    s = _spec(["rsi", "adx", "bb_z"])
    assert complexity_score(s) == 3

    s2 = _spec(["rsi"])
    assert complexity_score(s2) == 1


def test_novelty_gate_passes_novel_spec(tmp_path):
    store = _store(tmp_path)
    s = _spec(["rsi", "adx"])
    ok, reason = novelty_gate(s, store)
    assert ok
    assert reason == "novel"


def test_novelty_gate_rejects_too_complex(tmp_path):
    store = _store(tmp_path)
    s = _spec(["rsi", "adx", "bb_z", "vol_realized", "atr", "ret_Nd", "volume_zscore"])
    ok, reason = novelty_gate(s, store, max_complexity=6)
    assert not ok
    assert "too_complex" in reason


def test_novelty_gate_rejects_dead_end_duplicate(tmp_path):
    from cosmu.evolution.loop import Evaluated

    store = _store(tmp_path)
    memory = GraveyardMemory(store)

    dead_spec = _spec(["rsi", "adx"])
    dead_eval = Evaluated(
        version_id="v1", name="dead", origin="seed", lane="seed",
        deflated_sharpe=-0.5, oos_return_pct=-10.0, passed=False,
        reasons=["max_drawdown", "min_trades"],
    )
    memory.remember(dead_spec, dead_eval)

    candidate = _spec(["rsi", "adx"])
    ok, reason = novelty_gate(candidate, store)
    assert not ok
    assert "too_similar_to_dead_end" in reason


def test_novelty_gate_passes_different_from_dead_end(tmp_path):
    from cosmu.evolution.loop import Evaluated

    store = _store(tmp_path)
    memory = GraveyardMemory(store)

    dead_spec = _spec(["rsi", "adx"])
    dead_eval = Evaluated(
        version_id="v1", name="dead", origin="seed", lane="seed",
        deflated_sharpe=-0.5, oos_return_pct=-10.0, passed=False,
        reasons=["max_drawdown"],
    )
    memory.remember(dead_spec, dead_eval)

    candidate = _spec(["bb_z", "vol_realized", "atr"])
    ok, reason = novelty_gate(candidate, store)
    assert ok


def test_novelty_gate_rejects_monoculture(tmp_path):
    store = _store(tmp_path)
    candidate = _spec(["rsi", "adx"])
    live = [_spec(["rsi", "adx"]), _spec(["rsi", "adx"], bar_size="4h")]
    ok, reason = novelty_gate(candidate, store, live_specs=live)
    assert not ok
    assert "monoculture" in reason


def test_novelty_gate_passes_diverse_from_live(tmp_path):
    store = _store(tmp_path)
    candidate = _spec(["bb_z", "vol_realized"])
    live = [_spec(["rsi", "adx"])]
    ok, reason = novelty_gate(candidate, store, live_specs=live)
    assert ok


def test_novelty_gate_no_live_specs_skips_monoculture(tmp_path):
    store = _store(tmp_path)
    candidate = _spec(["rsi", "adx"])
    ok, reason = novelty_gate(candidate, store, live_specs=None)
    assert ok
