# intent: seed typed strategy hypotheses from templates before LLM autonomy is enabled; inputs: feature registry and venue catalog; outputs: StrategySpec; invariants: no hardcoded thresholds outside param_space.

from __future__ import annotations

from cosmu.strategy.spec import (
    Condition,
    EntrySetup,
    ExitPlan,
    ExitRules,
    FairValueGap,
    FeatureRef,
    Horizon,
    MaTrendFilter,
    OpeningRangeBreakout,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    TakeProfitLeg,
    TrailingStop,
    UniverseSelector,
)


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


def seed_orb_fvg_spec() -> StrategySpec:
    """The composable ORB + FVG-multiple seed — the first Finder input. An upside opening-range breakout, gated
    by an MA trend filter (long only above the MA), entering on a fair-value-gap retest (re-entered up to N
    times), with a multi-leg take-profit (partial exits) and a break-even-after-TP1 asymmetric runner. Every
    threshold lives in param_space (no magic numbers) so the Finder/optimizer fits the whole structure. Spot,
    long-only crypto."""
    return StrategySpec(
        name="ORB + FVG-multiple (composable seed)",
        rationale="Upside opening-range breakout into a fair-value-gap retest, trend-filtered, scaled out in legs with a break-even runner — a fully composable, optimizer-fittable setup.",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_liquidity_usd=10_000_000, min_instruments=5),
        horizon=Horizon(bar_size="1h", min_hold_days=1, max_hold_days=10),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
        ],
        exit=ExitRules(
            stop_loss=ParamRef(param="stop"),
            take_profit=ParamRef(param="take"),
            time_stop_days=ParamRef(param="time_stop"),
            plan=ExitPlan(
                multi_tp=[
                    TakeProfitLeg(at=ParamRef(param="tp1_at"), size_pct=ParamRef(param="tp1_size")),
                    TakeProfitLeg(at=ParamRef(param="tp2_at"), size_pct=ParamRef(param="tp2_size")),
                ],
                break_even_after_tp1=True,
                runner_trail=ParamRef(param="runner_trail"),
            ),
        ),
        risk=RiskRules(max_concurrent_positions=4, max_position_pct=0.04, conviction=0.55),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=5, hi=40, step=1),
            "mom_floor": ParamSpace(kind="float", lo=0.0, hi=0.05),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.1),
            "take": ParamSpace(kind="float", lo=0.04, hi=0.24),
            "time_stop": ParamSpace(kind="int", lo=2, hi=14, step=1),
            "tp1_at": ParamSpace(kind="float", lo=0.02, hi=0.08),
            "tp1_size": ParamSpace(kind="float", lo=0.25, hi=0.6),
            "tp2_at": ParamSpace(kind="float", lo=0.08, hi=0.2),
            "tp2_size": ParamSpace(kind="float", lo=0.2, hi=0.5),
            "runner_trail": ParamSpace(kind="float", lo=0.02, hi=0.1),
            "ma_lookback": ParamSpace(kind="int", lo=20, hi=100, step=1),
            "orb_range": ParamSpace(kind="int", lo=4, hi=24, step=1),
            "orb_buffer": ParamSpace(kind="float", lo=0.0, hi=0.01),
            "fvg_retests": ParamSpace(kind="int", lo=1, hi=4, step=1),
            "fvg_gap_min": ParamSpace(kind="float", lo=0.0, hi=0.02),
        },
        setup=EntrySetup(
            ma_trend_filter=MaTrendFilter(ma_lookback=ParamRef(param="ma_lookback")),
            orb=OpeningRangeBreakout(range_bars=ParamRef(param="orb_range"), buffer=ParamRef(param="orb_buffer"), anchor="rolling"),
            fvg=FairValueGap(max_retests=ParamRef(param="fvg_retests"), gap_min=ParamRef(param="fvg_gap_min")),
        ),
    )


def seed_fear_regime_spec() -> StrategySpec:
    return StrategySpec(
        name="Fear-regime buy-the-dip",
        rationale="Extreme crowd fear combined with elevated realized vol signals washed-out selling that mean-reverts at swing horizon.",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_liquidity_usd=10_000_000, min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=2, max_hold_days=14),
        entry=[
            Condition(feature=FeatureRef(name="fear_greed"), op="lt", threshold=ParamRef(param="fg_floor")),
            Condition(feature=FeatureRef(name="vol_realized", lookback=ParamRef(param="vol_lookback")), op="gt", threshold=ParamRef(param="vol_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=0.04, conviction=0.6),
        param_space={
            "fg_floor": ParamSpace(kind="float", lo=10.0, hi=35.0),
            "vol_lookback": ParamSpace(kind="int", lo=10, hi=40, step=1),
            "vol_floor": ParamSpace(kind="float", lo=0.01, hi=0.06),
            "stop": ParamSpace(kind="float", lo=0.03, hi=0.12),
            "take": ParamSpace(kind="float", lo=0.05, hi=0.25),
            "time_stop": ParamSpace(kind="int", lo=3, hi=21, step=1),
        },
    )


def seed_risk_on_cross_asset_spec() -> StrategySpec:
    return StrategySpec(
        name="Risk-on cross-asset directional",
        rationale="When prediction-market risk-on odds align with a supportive macro regime, risk assets tend to trend — a cross-asset confirmation signal.",
        universe=UniverseSelector(venues=["binance", "ibkr"], asset_classes=["crypto", "equity"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="4h", min_hold_days=2, max_hold_days=14),
        entry=[
            Condition(feature=FeatureRef(name="pm_risk_on"), op="gt", threshold=ParamRef(param="risk_on_floor")),
            Condition(feature=FeatureRef(name="macro_regime"), op="gt", threshold=ParamRef(param="macro_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=4, max_position_pct=0.04, conviction=0.55),
        param_space={
            "risk_on_floor": ParamSpace(kind="float", lo=0.5, hi=0.85),
            "macro_floor": ParamSpace(kind="float", lo=-0.5, hi=0.5),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.1),
            "take": ParamSpace(kind="float", lo=0.04, hi=0.2),
            "time_stop": ParamSpace(kind="int", lo=3, hi=21, step=1),
        },
    )


def seed_macro_filtered_momentum_spec() -> StrategySpec:
    return StrategySpec(
        name="Macro-filtered momentum",
        rationale="Medium-term return momentum gated by a supportive macro regime — momentum persists when the macro backdrop confirms.",
        universe=UniverseSelector(venues=["binance", "ibkr"], asset_classes=["crypto", "equity"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=3, max_hold_days=21),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
            Condition(feature=FeatureRef(name="macro_regime"), op="gt", threshold=ParamRef(param="macro_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=5, max_position_pct=0.04, conviction=0.55),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=10, hi=60, step=1),
            "mom_floor": ParamSpace(kind="float", lo=0.01, hi=0.12),
            "macro_floor": ParamSpace(kind="float", lo=-0.5, hi=0.5),
            "stop": ParamSpace(kind="float", lo=0.03, hi=0.14),
            "take": ParamSpace(kind="float", lo=0.06, hi=0.3),
            "time_stop": ParamSpace(kind="int", lo=5, hi=21, step=1),
        },
    )


def seed_funding_squeeze_spec() -> StrategySpec:
    return StrategySpec(
        name="Funding-squeeze mean reversion",
        rationale="Extreme funding rate combined with a liquidation cascade signals forced deleveraging that overshoots — fade the crowd at the exhaustion point.",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_liquidity_usd=10_000_000, min_instruments=5),
        horizon=Horizon(bar_size="4h", min_hold_days=1, max_hold_days=7),
        entry=[
            Condition(feature=FeatureRef(name="funding_rate"), op="gt", threshold=ParamRef(param="funding_hi")),
            Condition(feature=FeatureRef(name="liquidation_cascade"), op="gt", threshold=ParamRef(param="liq_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=0.03, conviction=0.55),
        param_space={
            "funding_hi": ParamSpace(kind="float", lo=0.0001, hi=0.01),
            "liq_floor": ParamSpace(kind="float", lo=0.5, hi=3.0),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.08),
            "take": ParamSpace(kind="float", lo=0.03, hi=0.14),
            "time_stop": ParamSpace(kind="int", lo=1, hi=10, step=1),
        },
    )


def seed_vix_regime_spec() -> StrategySpec:
    return StrategySpec(
        name="VIX-regime volatility breakout",
        rationale="Extreme VIX levels signal regime shifts; when ADX confirms trend strength, volatility breakouts persist across swing bars.",
        universe=UniverseSelector(venues=["binance", "ibkr"], asset_classes=["crypto", "equity"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="4h", min_hold_days=2, max_hold_days=14),
        entry=[
            Condition(feature=FeatureRef(name="vix_level"), op="gt", threshold=ParamRef(param="vix_floor")),
            Condition(feature=FeatureRef(name="adx", lookback=ParamRef(param="adx_lookback")), op="gt", threshold=ParamRef(param="adx_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=4, max_position_pct=0.04, conviction=0.55),
        param_space={
            "vix_floor": ParamSpace(kind="float", lo=20.0, hi=40.0),
            "adx_lookback": ParamSpace(kind="int", lo=7, hi=30, step=1),
            "adx_floor": ParamSpace(kind="float", lo=15.0, hi=35.0),
            "stop": ParamSpace(kind="float", lo=0.03, hi=0.12),
            "take": ParamSpace(kind="float", lo=0.05, hi=0.25),
            "time_stop": ParamSpace(kind="int", lo=3, hi=21, step=1),
        },
    )


def seed_defi_flow_spec() -> StrategySpec:
    return StrategySpec(
        name="DeFi-flow risk appetite",
        rationale="Rising DeFi TVL indicates growing risk appetite across crypto protocols; confirmed by price momentum, the trend persists.",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_liquidity_usd=10_000_000, min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=3, max_hold_days=21),
        entry=[
            Condition(feature=FeatureRef(name="defi_tvl"), op="gt", threshold=ParamRef(param="tvl_floor")),
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take"), time_stop_days=ParamRef(param="time_stop")),
        risk=RiskRules(max_concurrent_positions=4, max_position_pct=0.04, conviction=0.5),
        param_space={
            "tvl_floor": ParamSpace(kind="float", lo=0.01, hi=0.15),
            "mom_lookback": ParamSpace(kind="int", lo=10, hi=40, step=1),
            "mom_floor": ParamSpace(kind="float", lo=0.005, hi=0.08),
            "stop": ParamSpace(kind="float", lo=0.03, hi=0.12),
            "take": ParamSpace(kind="float", lo=0.06, hi=0.25),
            "time_stop": ParamSpace(kind="int", lo=3, hi=21, step=1),
        },
    )


# --------------------------------------------------------------------------- EXIT-toolset seeds
# Before these, only seed_orb_fvg emitted a full ExitPlan and NOTHING used the standalone trailing stop or the
# ATR-multiple stop (PR #375). The autonomous mass-gen surface therefore explored entries widely but exits barely.
# These five seeds span the full exit toolset so the population — and any sweep over it — actually searches SL/TP
# STRUCTURE: a scale-out runner, two standalone-trailing flavours, an ATR-scaled stop, and a time-stop-heavy fast
# scalp. Each keeps a simple, distinct ENTRY (so they're not near-duplicates of each other) and lives every
# threshold in param_space (no magic numbers), exactly like every other seed.


def seed_breakout_runner_spec() -> StrategySpec:
    """Volatility breakout with a SCALE-OUT runner exit: bank profit in two legs, move the stop to break-even after
    TP1, then let the remainder ride a trailing runner. The full multi-TP + break-even + runner structure on a
    plain breakout entry — the toolset's asymmetric 'free runner' shape."""
    return StrategySpec(
        name="Breakout scale-out runner",
        rationale="A volatility breakout that scales out in legs and rides a break-even runner — the trend, if it persists, is harvested by the runner while early partials de-risk the trade.",
        universe=UniverseSelector(venues=["binance", "ibkr"], asset_classes=["crypto", "equity"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="4h", min_hold_days=2, max_hold_days=14),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="lookback")), op="gt", threshold=ParamRef(param="entry_ret")),
            Condition(feature=FeatureRef(name="vol_realized", lookback=ParamRef(param="vol_lookback")), op="gt", threshold=ParamRef(param="vol_floor")),
        ],
        exit=ExitRules(
            stop_loss=ParamRef(param="stop"),
            take_profit=ParamRef(param="take"),
            time_stop_days=ParamRef(param="time_stop"),
            plan=ExitPlan(
                multi_tp=[
                    TakeProfitLeg(at=ParamRef(param="tp1_at"), size_pct=ParamRef(param="tp1_size")),
                    TakeProfitLeg(at=ParamRef(param="tp2_at"), size_pct=ParamRef(param="tp2_size")),
                ],
                break_even_after_tp1=True,
                runner_trail=ParamRef(param="runner_trail"),
            ),
        ),
        risk=RiskRules(max_concurrent_positions=4, max_position_pct=0.04, conviction=0.55),
        param_space={
            "lookback": ParamSpace(kind="int", lo=5, hi=40, step=1),
            "entry_ret": ParamSpace(kind="float", lo=0.005, hi=0.08),
            "vol_lookback": ParamSpace(kind="int", lo=10, hi=60, step=1),
            "vol_floor": ParamSpace(kind="float", lo=0.01, hi=0.08),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.12),
            "take": ParamSpace(kind="float", lo=0.04, hi=0.24),
            "time_stop": ParamSpace(kind="int", lo=3, hi=21, step=1),
            "tp1_at": ParamSpace(kind="float", lo=0.02, hi=0.08),
            "tp1_size": ParamSpace(kind="float", lo=0.25, hi=0.6),
            "tp2_at": ParamSpace(kind="float", lo=0.08, hi=0.2),
            "tp2_size": ParamSpace(kind="float", lo=0.2, hi=0.5),
            "runner_trail": ParamSpace(kind="float", lo=0.02, hi=0.1),
        },
    )


def seed_momentum_trailing_spec() -> StrategySpec:
    """Trend momentum with a STANDALONE trailing stop armed after a profit cushion. No scale-out — the whole
    position rides a single trailing stop once it is `arm_after_profit` in the money, so a fresh entry is not
    stopped out by ordinary noise before it has earned a cushion. The cushioned-trailing lane of the toolset."""
    return StrategySpec(
        name="Momentum trailing-stop runner",
        rationale="Medium-term momentum held with a profit-armed trailing stop: noise can't stop the trade out before it earns a cushion, then the trail locks gains as the move extends.",
        universe=UniverseSelector(venues=["binance", "ibkr"], asset_classes=["crypto", "equity"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=3, max_hold_days=21),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
            Condition(feature=FeatureRef(name="adx", lookback=ParamRef(param="adx_lookback")), op="gt", threshold=ParamRef(param="adx_floor")),
        ],
        exit=ExitRules(
            stop_loss=ParamRef(param="stop"),
            take_profit=ParamRef(param="take"),
            time_stop_days=ParamRef(param="time_stop"),
            trailing_stop=TrailingStop(distance=ParamRef(param="trail_dist"), arm_after_profit=ParamRef(param="trail_arm")),
        ),
        risk=RiskRules(max_concurrent_positions=5, max_position_pct=0.04, conviction=0.6),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=10, hi=60, step=1),
            "mom_floor": ParamSpace(kind="float", lo=0.01, hi=0.12),
            "adx_lookback": ParamSpace(kind="int", lo=7, hi=30, step=1),
            "adx_floor": ParamSpace(kind="float", lo=15.0, hi=35.0),
            "stop": ParamSpace(kind="float", lo=0.03, hi=0.14),
            "take": ParamSpace(kind="float", lo=0.06, hi=0.3),
            "time_stop": ParamSpace(kind="int", lo=5, hi=21, step=1),
            "trail_dist": ParamSpace(kind="float", lo=0.02, hi=0.12),
            "trail_arm": ParamSpace(kind="float", lo=0.01, hi=0.1),
        },
    )


def seed_atr_stop_breakout_spec() -> StrategySpec:
    """Breakout sized by VOLATILITY: the initial stop is `atr_mult × ATR` at entry instead of a fixed fraction, so
    the stop distance adapts to each asset's realized range. A single take-profit on top — the ATR-stop lane of the
    toolset, the structural alternative to a flat percentage stop."""
    return StrategySpec(
        name="ATR-scaled breakout stop",
        rationale="A momentum breakout whose stop scales with each asset's ATR at entry, not a flat fraction — a volatile name gets room to breathe, a quiet one a tight stop, so the same spec sizes risk per instrument.",
        universe=UniverseSelector(venues=["binance", "ibkr"], asset_classes=["crypto", "equity"], min_liquidity_usd=5_000_000, min_instruments=5),
        horizon=Horizon(bar_size="4h", min_hold_days=2, max_hold_days=14),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
        ],
        exit=ExitRules(
            stop_loss=ParamRef(param="stop"),  # warm-up / no-ATR fallback fraction
            take_profit=ParamRef(param="take"),
            time_stop_days=ParamRef(param="time_stop"),
            atr_mult=ParamRef(param="atr_mult"),
        ),
        risk=RiskRules(max_concurrent_positions=4, max_position_pct=0.04, conviction=0.55),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=5, hi=40, step=1),
            "mom_floor": ParamSpace(kind="float", lo=0.0, hi=0.06),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.1),
            "take": ParamSpace(kind="float", lo=0.04, hi=0.24),
            "time_stop": ParamSpace(kind="int", lo=3, hi=21, step=1),
            "atr_mult": ParamSpace(kind="float", lo=1.0, hi=5.0),
        },
    )


def seed_meanrev_scalp_spec() -> StrategySpec:
    """A fast oversold-reversion SCALP whose dominant exit is a tight TIME STOP: the edge is a quick bounce, so the
    trade is force-closed after a few bars if it hasn't worked, with a tight stop and a modest take. The
    time-stop-heavy lane of the toolset (short horizon, the time stop is the binding exit, not stop/take)."""
    return StrategySpec(
        name="Oversold time-stop scalp",
        rationale="A washed-out selloff tends to bounce fast or not at all; a tight time stop force-exits a stale trade in a few bars so capital isn't tied up waiting on a reversion that already failed.",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_liquidity_usd=10_000_000, min_instruments=5),
        horizon=Horizon(bar_size="4h", min_hold_days=1, max_hold_days=5),
        entry=[
            Condition(feature=FeatureRef(name="rsi", lookback=ParamRef(param="rsi_lookback")), op="lt", threshold=ParamRef(param="rsi_floor")),
            Condition(feature=FeatureRef(name="bb_z", lookback=ParamRef(param="bb_lookback")), op="lt", threshold=ParamRef(param="bb_floor")),
        ],
        exit=ExitRules(
            stop_loss=ParamRef(param="stop"),
            take_profit=ParamRef(param="take"),
            time_stop_days=ParamRef(param="time_stop"),  # the binding exit — short, fitted range
        ),
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=0.03, conviction=0.5),
        param_space={
            "rsi_lookback": ParamSpace(kind="int", lo=5, hi=30, step=1),
            "rsi_floor": ParamSpace(kind="float", lo=15.0, hi=40.0),
            "bb_lookback": ParamSpace(kind="int", lo=10, hi=40, step=1),
            "bb_floor": ParamSpace(kind="float", lo=-3.0, hi=-1.0),
            "stop": ParamSpace(kind="float", lo=0.015, hi=0.06),
            "take": ParamSpace(kind="float", lo=0.02, hi=0.1),
            "time_stop": ParamSpace(kind="int", lo=1, hi=5, step=1),
        },
    )


def seed_funding_atr_runner_spec() -> StrategySpec:
    """Funding-contrarian entry with the FULL composite exit: an ATR-scaled initial stop + a two-leg scale-out +
    break-even + a runner trail. Volatility-scaled risk with an asymmetric scale-out runner — the richest exit the
    toolset composes, on the funding-pressure carry thesis."""
    return StrategySpec(
        name="Funding contrarian ATR runner",
        rationale="Fade crowded perp funding, size the stop by ATR so each coin's volatility sets the risk, then scale out and ride a break-even runner — the unwind, if it comes, is harvested asymmetrically.",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_liquidity_usd=10_000_000, min_instruments=5),
        horizon=Horizon(bar_size="4h", min_hold_days=1, max_hold_days=7),
        entry=[
            Condition(feature=FeatureRef(name="funding_rate"), op="gt", threshold=ParamRef(param="funding_hi")),
        ],
        exit=ExitRules(
            stop_loss=ParamRef(param="stop"),
            take_profit=ParamRef(param="take"),
            time_stop_days=ParamRef(param="time_stop"),
            atr_mult=ParamRef(param="atr_mult"),
            plan=ExitPlan(
                multi_tp=[
                    TakeProfitLeg(at=ParamRef(param="tp1_at"), size_pct=ParamRef(param="tp1_size")),
                    TakeProfitLeg(at=ParamRef(param="tp2_at"), size_pct=ParamRef(param="tp2_size")),
                ],
                break_even_after_tp1=True,
                runner_trail=ParamRef(param="runner_trail"),
            ),
        ),
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=0.03, conviction=0.55),
        param_space={
            "funding_hi": ParamSpace(kind="float", lo=0.0001, hi=0.01),
            "stop": ParamSpace(kind="float", lo=0.02, hi=0.08),
            "take": ParamSpace(kind="float", lo=0.03, hi=0.14),
            "time_stop": ParamSpace(kind="int", lo=1, hi=10, step=1),
            "atr_mult": ParamSpace(kind="float", lo=1.0, hi=5.0),
            "tp1_at": ParamSpace(kind="float", lo=0.02, hi=0.07),
            "tp1_size": ParamSpace(kind="float", lo=0.25, hi=0.6),
            "tp2_at": ParamSpace(kind="float", lo=0.07, hi=0.16),
            "tp2_size": ParamSpace(kind="float", lo=0.2, hi=0.5),
            "runner_trail": ParamSpace(kind="float", lo=0.02, hi=0.08),
        },
    )


def seed_population() -> list[StrategySpec]:
    """Diverse seed templates so the population never starts collapsed to one style — entries AND exits. The exit
    toolset (scale-out runner, standalone trailing, ATR-scaled stop, time-stop scalp, full composite) is seeded
    explicitly so the mass-gen surface searches SL/TP structure, not just entry signals."""
    return [
        seed_breakout_spec(),
        seed_meanrev_spec(),
        seed_carry_spec(),
        seed_momentum_spec(),
        seed_orb_fvg_spec(),
        seed_fear_regime_spec(),
        seed_risk_on_cross_asset_spec(),
        seed_macro_filtered_momentum_spec(),
        seed_funding_squeeze_spec(),
        seed_vix_regime_spec(),
        seed_defi_flow_spec(),
        # Exit-toolset seeds (PR: exit-envelope sweep) — span the full SL/TP structure space.
        seed_breakout_runner_spec(),
        seed_momentum_trailing_spec(),
        seed_atr_stop_breakout_spec(),
        seed_meanrev_scalp_spec(),
        seed_funding_atr_runner_spec(),
    ]

