# intent: seed typed strategy hypotheses from templates before LLM autonomy is enabled; inputs: feature registry and venue catalog; outputs: StrategySpec; invariants: no hardcoded thresholds outside param_space.

from __future__ import annotations

from cosmu.strategy.spec import Condition, ExitRules, FeatureRef, Horizon, ParamRef, ParamSpace, RiskRules, StrategySpec, UniverseSelector


def seed_breakout_spec() -> StrategySpec:
    return StrategySpec(
        name="Cross-asset volatility breakout",
        rationale="Trend continuation after volatility expansion can persist for several swing bars when macro risk is supportive.",
        universe=UniverseSelector(venues=["binance", "ibkr"], asset_classes=["crypto", "equity"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="4h", min_hold_days=2, max_hold_days=14),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="lookback")), op="gt", threshold=ParamRef(param="entry_ret")),
            Condition(feature=FeatureRef(name="vol_realized", lookback=ParamRef(param="vol_lookback")), op="gt", threshold=ParamRef(param="vol_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=4, max_position_pct=0.04, conviction=0.58),
        param_space={
            "lookback": ParamSpace(kind="int", lo=5, hi=40, step=1),
            "entry_ret": ParamSpace(kind="float", lo=0.005, hi=0.08),
            "vol_lookback": ParamSpace(kind="int", lo=10, hi=60, step=1),
            "vol_floor": ParamSpace(kind="float", lo=0.01, hi=0.08),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.12),
            "take": ParamSpace(kind="float", lo=0.04, hi=0.24),
            "time_stop": ParamSpace(kind="int", lo=3, hi=21, step=1),
        },
    )

