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


def seed_meanrev_spec() -> StrategySpec:
    return StrategySpec(
        name="Oversold mean reversion",
        rationale="At swing horizon, statistically unusual selloffs in liquid names tend to revert when sentiment is washed out.",
        universe=UniverseSelector(venues=["binance", "ibkr"], asset_classes=["crypto", "equity"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=2, max_hold_days=10),
        entry=[
            Condition(feature=FeatureRef(name="rsi", lookback=ParamRef(param="rsi_lookback")), op="lt", threshold=ParamRef(param="rsi_floor")),
            Condition(feature=FeatureRef(name="bb_z", lookback=ParamRef(param="bb_lookback")), op="lt", threshold=ParamRef(param="bb_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=0.03, conviction=0.5),
        param_space={
            "rsi_lookback": ParamSpace(kind="int", lo=5, hi=30, step=1),
            "rsi_floor": ParamSpace(kind="float", lo=15.0, hi=40.0),
            "bb_lookback": ParamSpace(kind="int", lo=10, hi=40, step=1),
            "bb_floor": ParamSpace(kind="float", lo=-3.0, hi=-1.0),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.1),
            "take": ParamSpace(kind="float", lo=0.03, hi=0.18),
            "time_stop": ParamSpace(kind="int", lo=2, hi=14, step=1),
        },
    )


def seed_carry_spec() -> StrategySpec:
    return StrategySpec(
        name="Funding-pressure carry",
        rationale="Crowded perp leverage (extreme funding) precedes mean-reverting unwinds; fade the crowd when basis confirms.",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_liquidity_usd=10_000_000, min_instruments=5),
        horizon=Horizon(bar_size="4h", min_hold_days=1, max_hold_days=7),
        entry=[
            Condition(feature=FeatureRef(name="funding_rate"), op="gt", threshold=ParamRef(param="funding_hi")),
            Condition(feature=FeatureRef(name="perp_spot_basis"), op="gt", threshold=ParamRef(param="basis_hi")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=4, max_position_pct=0.035, conviction=0.55),
        param_space={
            "funding_hi": ParamSpace(kind="float", lo=0.0001, hi=0.01),
            "basis_hi": ParamSpace(kind="float", lo=0.0, hi=0.02),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.08),
            "take": ParamSpace(kind="float", lo=0.03, hi=0.14),
            "time_stop": ParamSpace(kind="int", lo=1, hi=10, step=1),
        },
    )


def seed_momentum_spec() -> StrategySpec:
    return StrategySpec(
        name="Trend-confirmed momentum",
        rationale="When trend strength (ADX) confirms medium-term return, momentum persists across swing bars.",
        universe=UniverseSelector(venues=["binance", "ibkr"], asset_classes=["crypto", "equity"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=3, max_hold_days=21),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
            Condition(feature=FeatureRef(name="adx", lookback=ParamRef(param="adx_lookback")), op="gt", threshold=ParamRef(param="adx_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=5, max_position_pct=0.04, conviction=0.6),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=10, hi=60, step=1),
            "mom_floor": ParamSpace(kind="float", lo=0.01, hi=0.12),
            "adx_lookback": ParamSpace(kind="int", lo=7, hi=30, step=1),
            "adx_floor": ParamSpace(kind="float", lo=15.0, hi=35.0),
            "stop": ParamSpace(kind="float", lo=0.03, hi=0.14),
            "take": ParamSpace(kind="float", lo=0.06, hi=0.3),
            "time_stop": ParamSpace(kind="int", lo=5, hi=21, step=1),
        },
    )


def seed_population() -> list[StrategySpec]:
    """Diverse seed templates so the population never starts collapsed to one style."""
    return [seed_breakout_spec(), seed_meanrev_spec(), seed_carry_spec(), seed_momentum_spec()]

