# The TYPED two-lane router: a spec's `lane` discriminator dispatches to the ONE correct evaluator — deploy-lane
# (taa.validate-style positive-OOS deployment bar) vs gate-lane (promote_cohort: 0.95 deflated-Sharpe + BH-FDR).
# These tests prove routing is explicit (not an accident of which function a runner called) and that the default /
# unset lane is "gate" — so EVERY existing spec keeps its current gate-lane behaviour. No thresholds are touched.

from __future__ import annotations

from decimal import Decimal

import pytest

from cosmu.config.settings import GateSettings, Settings
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, Promotion
from cosmu.master.lane_router import evaluate_by_lane, lane_of, route_spec
from cosmu.master.scorer import BacktestMetrics
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


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/lane.sqlite3"))


def _metrics(sharpe_per_obs: float, n_obs: int = 500, *, strong: bool = True) -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal("0.1"),
        sharpe=Decimal(str(sharpe_per_obs * 19)),
        sortino=Decimal("0"),
        max_drawdown=Decimal("0.10") if strong else Decimal("0.30"),
        win_rate=Decimal("0.55"),
        num_trades=50,
        sharpe_per_obs=Decimal(str(sharpe_per_obs)),
        skew=Decimal("0"),
        kurtosis=Decimal("3"),
        n_obs=n_obs,
        pbo=Decimal("0.1"),
        trials_counted=1,
        folds_positive_pct=Decimal("0.80") if strong else Decimal("0.30"),
        holdout_deflated_sharpe=Decimal("0.05") if strong else Decimal("-0.1"),
    )


def _spec(name: str, lane: str | None = None) -> StrategySpec:
    """A minimal valid spec. `lane=None` builds it WITHOUT passing lane, so the field's default ("gate") applies —
    this is how we prove a legacy/unset spec routes to the gate-lane."""
    kw = {} if lane is None else {"lane": lane}
    return StrategySpec(
        name=name,
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


# --------------------------------------------------------------------------- discriminator (pure read)


def test_unset_lane_defaults_to_gate():
    # A spec built WITHOUT a lane keeps the typed default — preserving every existing spec's gate-lane behaviour.
    spec = _spec("legacy")
    assert spec.lane == "gate"
    assert lane_of(spec) == "gate"
    assert route_spec(spec) == "gate"


def test_explicit_lanes_resolve():
    assert route_spec(_spec("mined", lane="gate")) == "gate"
    assert route_spec(_spec("documented", lane="deploy")) == "deploy"


# --------------------------------------------------------------------------- deploy-lane dispatch


def test_deploy_lane_routes_to_deploy_bar_not_the_gate():
    # The deploy-lane must call the supplied taa.validate-style deployment bar — NOT promote_cohort. We spy on the
    # callable and assert it (and only it) ran, with the kwargs forwarded.
    calls: list[dict] = []

    def fake_validate(**kw) -> dict:
        calls.append(kw)
        return {"deployable": True, "oos_positive": True}

    out = evaluate_by_lane(
        _spec("documented", lane="deploy"),
        deploy_validate=fake_validate,
        validate_kwargs={"lookback": 12},
    )
    assert out == {"deployable": True, "oos_positive": True}
    assert calls == [{"lookback": 12}]  # exactly one call, kwargs forwarded


def test_deploy_lane_without_validator_fails_loud():
    # A mis-wired deploy-lane runner must FAIL FAST, never silently fall through to the gate (the bug we're killing).
    with pytest.raises(ValueError, match="deploy-lane"):
        evaluate_by_lane(_spec("documented", lane="deploy"))


# --------------------------------------------------------------------------- gate-lane dispatch (real evaluator)


def test_gate_lane_routes_to_095_bh_fdr_gate(tmp_path):
    # The gate-lane (default) must call the REAL promote_cohort — the 0.95 deflated-Sharpe + BH-FDR cohort gate.
    # We pass a genuinely strong and a genuinely weak candidate and check the honest verdict comes back unchanged.
    store = _store(tmp_path)
    cands = [
        Candidate("strong", _metrics(0.4), net_profit=0.20, source="test"),
        Candidate("weak", _metrics(0.05, n_obs=200, strong=False), net_profit=0.01, source="test"),
    ]
    out = evaluate_by_lane(_spec("mined", lane="gate"), store=store, candidates=cands, gates=GateSettings())
    assert isinstance(out, list) and all(isinstance(p, Promotion) for p in out)
    by_id = {p.candidate_id: p for p in out}
    assert by_id["strong"].promoted and by_id["strong"].rank == 1
    assert not by_id["weak"].promoted
    assert "deflated_sharpe" in by_id["weak"].reasons  # the 0.95 bar bit, unchanged
    # the gate registers EVERY candidate as a trial (FDR validity) — proof we hit the real evaluator, not a stub
    assert store.rows("SELECT COUNT(*) AS n FROM trials")[0]["n"] == 2


def test_unset_lane_routes_through_the_gate(tmp_path):
    # The default/unset lane must dispatch to the gate evaluator too (not just report "gate").
    store = _store(tmp_path)
    cands = [Candidate("c", _metrics(0.4), net_profit=0.2, source="test")]
    out = evaluate_by_lane(_spec("legacy"), store=store, candidates=cands, gates=GateSettings())
    assert isinstance(out, list) and out[0].candidate_id == "c"


def test_gate_lane_missing_inputs_fails_loud():
    # Gate-lane needs store+candidates+gates (it judges a cohort). Missing them must raise, not silently mis-route.
    with pytest.raises(ValueError, match="gate-lane"):
        evaluate_by_lane(_spec("mined", lane="gate"))
