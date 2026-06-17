# Guard test for the strategy MODEL discriminator `kind` (quant|llm) — the P0.1 keystone of the LLM strategy lane
# (docs/epics/agentic-lane.md). Proves: (1) a legacy spec defaults to "quant" (byte-identical), (2) kind round-trips
# through JSON incl. legacy JSON with no field, (3) the Literal rejects anything else, (4) kind is orthogonal to
# lane/strategy_kind, (5) the strategy_versions.kind column defaults to "quant" so the ~15 quant write sites that
# omit it stay byte-identical. Matches the no-DB-CHECK convention (knowledge/lifecycle_status.py): the vocabulary is
# enforced by the spec Literal + this test, not a DB constraint.

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
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


def _spec(**kw) -> StrategySpec:
    return StrategySpec(
        name="kind-test",
        rationale="test",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"]),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=5),
        entry=[Condition(feature=FeatureRef(name="rsi"), op="lt", threshold=ParamRef(param="thr"))],
        exit=ExitRules(stop_loss=ParamRef(param="sl"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space={
            "thr": ParamSpace(kind="float", lo=10, hi=40),
            "sl": ParamSpace(kind="float", lo=0.01, hi=0.1),
            "tp": ParamSpace(kind="float", lo=0.01, hi=0.2),
        },
        **kw,
    )


def test_unset_kind_defaults_to_quant():
    assert _spec().kind == "quant"


def test_kind_round_trips_and_legacy_json_defaults_quant():
    again = StrategySpec.model_validate(_spec(kind="llm").model_dump(mode="json"))
    assert again.kind == "llm"
    legacy = _spec().model_dump(mode="json")
    legacy.pop("kind", None)
    assert StrategySpec.model_validate(legacy).kind == "quant"


def test_kind_literal_rejects_unknown():
    with pytest.raises(ValidationError):
        _spec(kind="bogus")


def test_kind_is_orthogonal_to_lane_and_strategy_kind():
    spec = _spec(kind="llm")
    assert spec.lane == "gate"
    assert spec.strategy_kind == "indicator"


def test_strategy_versions_kind_column_defaults_to_quant(tmp_path):
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/kind.sqlite3"))
    with store.batch() as b:
        b.insert("strategies", {"id": "s1", "name": "n", "thesis": "t", "origin": "test", "created_at": utcnow()})
        b.insert(
            "strategy_versions",
            {
                "id": "v1", "strategy_id": "s1", "parent_id": None,
                "spec": "{}", "generated_code": "", "code_hash": "h", "params": "{}",
                "origin": "test", "status": "screened", "created_at": utcnow(),
            },
        )
    row = store.row("SELECT kind FROM strategy_versions WHERE id = ?", ("v1",))
    assert row is not None and row["kind"] == "quant"
