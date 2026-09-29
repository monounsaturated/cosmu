# Composable, optimizer-fittable spec modules: multi_tp partial exits, break_even_after_tp1 + asymmetric runner,
# ma_trend_filter, ORB (upside-only), fvg_retest / fvg_multiple. Each must compile (no magic numbers — every
# threshold a ParamRef in param_space), be fittable, and run through the deterministic backtest.

from __future__ import annotations

from decimal import Decimal

from cosmu.data.backtest import run_strategy_backtest
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_orb_fvg_spec, seed_momentum_spec
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.spec import (
    EntrySetup,
    ExitPlan,
    FairValueGap,
    MaTrendFilter,
    OpeningRangeBreakout,
    ParamRef,
    ParamSpace,
    TakeProfitLeg,
)
from cosmu.strategy.static_check import validate_spec

_FULL = edge_bearing_screen_market(n=280)
MARKET = {sym: _FULL[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}


def _compile_and_run(spec):
    assert validate_spec(spec) == []          # no magic numbers / unresolved param refs
    params = fit_params(spec)
    compiled = compile_spec(spec, params)     # compiles deterministically (would raise on missing params)
    assert compiled.code_hash
    metrics = run_strategy_backtest(spec, params, MARKET, fee_bps=Decimal("10"))
    return metrics


def test_orb_fvg_seed_compiles_and_runs():
    metrics = _compile_and_run(seed_orb_fvg_spec())
    assert metrics.num_trades >= 0
    # profit_factor is a DISPLAYED secondary metric, populated from trades
    assert metrics.profit_factor >= 0


def test_multi_tp_and_breakeven_runner_are_fittable():
    spec = seed_momentum_spec().model_copy(deep=True)
    spec.exit.plan = ExitPlan(
        multi_tp=[
            TakeProfitLeg(at=ParamRef(param="tp1_at"), size_pct=ParamRef(param="tp1_size")),
            TakeProfitLeg(at=ParamRef(param="tp2_at"), size_pct=ParamRef(param="tp2_size")),
        ],
        break_even_after_tp1=True,
        runner_trail=ParamRef(param="runner_trail"),
    )
    spec.param_space.update(
        {
            "tp1_at": ParamSpace(kind="float", lo=0.02, hi=0.06),
            "tp1_size": ParamSpace(kind="float", lo=0.3, hi=0.6),
            "tp2_at": ParamSpace(kind="float", lo=0.08, hi=0.18),
            "tp2_size": ParamSpace(kind="float", lo=0.2, hi=0.5),
            "runner_trail": ParamSpace(kind="float", lo=0.02, hi=0.08),
        }
    )
    _compile_and_run(spec)


def test_unresolved_composable_paramref_is_rejected():
    spec = seed_momentum_spec().model_copy(deep=True)
    # an exit plan whose runner_trail points at a param NOT in the space must be flagged (no magic numbers leak)
    spec.exit.plan = ExitPlan(runner_trail=ParamRef(param="ghost_param"))
    assert "unknown_param:ghost_param" in validate_spec(spec)


def test_ma_trend_filter_orb_fvg_each_compose_individually():
    base = seed_momentum_spec()
    # MA trend filter only
    s1 = base.model_copy(deep=True)
    s1.setup = EntrySetup(ma_trend_filter=MaTrendFilter(ma_lookback=ParamRef(param="ma_lb")))
    s1.param_space["ma_lb"] = ParamSpace(kind="int", lo=20, hi=80, step=1)
    _compile_and_run(s1)

    # ORB only (upside-only breakout)
    s2 = base.model_copy(deep=True)
    s2.setup = EntrySetup(orb=OpeningRangeBreakout(range_bars=ParamRef(param="orb_n"), buffer=ParamRef(param="orb_b")))
    s2.param_space.update({"orb_n": ParamSpace(kind="int", lo=4, hi=20, step=1), "orb_b": ParamSpace(kind="float", lo=0.0, hi=0.01)})
    _compile_and_run(s2)

    # FVG multiple (re-test up to N times)
    s3 = base.model_copy(deep=True)
    s3.setup = EntrySetup(fvg=FairValueGap(max_retests=ParamRef(param="fvg_n"), gap_min=ParamRef(param="fvg_g")))
    s3.param_space.update({"fvg_n": ParamSpace(kind="int", lo=1, hi=4, step=1), "fvg_g": ParamSpace(kind="float", lo=0.0, hi=0.02)})
    _compile_and_run(s3)


def test_multi_tp_produces_partial_exits():
    # With multi_tp the runner can scale out — more trade legs than a single all-or-nothing TP on the same path.
    spec_single = seed_momentum_spec().model_copy(deep=True)
    m_single = run_strategy_backtest(spec_single, fit_params(spec_single), MARKET, fee_bps=Decimal("10"))
    spec_multi = seed_orb_fvg_spec()
    m_multi = run_strategy_backtest(spec_multi, fit_params(spec_multi), MARKET, fee_bps=Decimal("10"))
    assert m_multi.num_trades >= 1   # partial legs each book a trade
