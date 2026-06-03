#!/usr/bin/env python3
"""Author a diverse batch of crypto-spot StrategySpecs into strategies/inbox/, validating each against the
REAL compiler (static_check + compile_spec) before writing — so nothing inert or magic-number'd lands. Each
is a distinct, economically-motivated edge with thresholds in param_space (fit from data, never hardcoded).

Run:  PYTHONPATH=apps/engine python3 scripts/seed_inbox_strategies.py [--write]
Without --write it only validates (dry run). Idempotent: overwrites same-named files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from cosmu.evolution.loop import fit_params
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.spec import StrategySpec

INBOX = Path(__file__).resolve().parents[1] / "strategies" / "inbox"


def _u(min_instruments: int = 5) -> dict:
    return {"venues": ["binance"], "asset_classes": ["crypto"], "min_liquidity_usd": 10_000_000, "min_instruments": min_instruments}


def _risk(maxpos: int = 5, pct: float = 0.2, conv: float = 0.5) -> dict:
    return {"max_concurrent_positions": maxpos, "max_position_pct": pct, "conviction": conv}


# Each spec: a real hypothesis with a disconfirmer baked into its exit. Core signals are price/TA (always
# computable from Binance bars, so they screen NOW) plus funding (already wired into the point-in-time join).
SPECS: list[dict] = [
    {
        "name": "RSI dip-buy in an uptrend (calm-vol gated)",
        "rationale": "Buying short-term oversold (low RSI) inside a confirmed medium-term uptrend harvests mean reversion WITHOUT fighting the trend — the classic 'buy the dip' only when the dip is in an uptrend. Calm realized vol keeps us out of crash regimes where 'oversold' keeps falling. Disconfirmer: exits when RSI normalizes (the dip is bought) or the trend floor breaks.",
        "catalyst": "short-term oversold pullback within an intact uptrend",
        "universe": _u(), "horizon": {"bar_size": "1d", "min_hold_days": 2, "max_hold_days": 10},
        "entry": [
            {"feature": {"name": "rsi"}, "op": "lt", "threshold": {"param": "rsi_floor"}},
            {"feature": {"name": "ret_Nd", "lookback": {"param": "trend_lb"}}, "op": "gt", "threshold": {"param": "trend_floor"}},
            {"feature": {"name": "vol_realized"}, "op": "lt", "threshold": {"param": "vol_ceiling"}},
        ],
        "exit": {"stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"}, "time_stop_days": {"param": "time_stop"},
                 "signal_exits": [{"feature": {"name": "rsi"}, "op": "gt", "threshold": {"param": "rsi_exit"}}]},
        "risk": _risk(),
        "param_space": {
            "rsi_floor": {"kind": "float", "lo": 20, "hi": 40}, "rsi_exit": {"kind": "float", "lo": 55, "hi": 75},
            "trend_lb": {"kind": "int", "lo": 30, "hi": 90, "step": 1}, "trend_floor": {"kind": "float", "lo": 0.0, "hi": 0.05},
            "vol_ceiling": {"kind": "float", "lo": 0.03, "hi": 0.12},
            "stop": {"kind": "float", "lo": 0.05, "hi": 0.15}, "tp": {"kind": "float", "lo": 0.08, "hi": 0.30},
            "time_stop": {"kind": "int", "lo": 5, "hi": 15, "step": 1},
        },
    },
    {
        "name": "Bollinger z-score washout reversion",
        "rationale": "A deeply negative Bollinger z-score marks a statistically unusual washout; in a calm regime price snaps back to its band. Distinct from RSI (band-relative, not momentum-relative). Disconfirmer: exits when z-score reverts toward zero, or the stop fires if the washout was the start of a real breakdown.",
        "catalyst": "statistically unusual downside dislocation in a calm regime",
        "universe": _u(), "horizon": {"bar_size": "1d", "min_hold_days": 2, "max_hold_days": 8},
        "entry": [
            {"feature": {"name": "bb_z"}, "op": "lt", "threshold": {"param": "bbz_floor"}},
            {"feature": {"name": "vol_realized"}, "op": "lt", "threshold": {"param": "vol_ceiling"}},
        ],
        "exit": {"stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"}, "time_stop_days": {"param": "time_stop"},
                 "signal_exits": [{"feature": {"name": "bb_z"}, "op": "gt", "threshold": {"param": "bbz_exit"}}]},
        "risk": _risk(),
        "param_space": {
            "bbz_floor": {"kind": "float", "lo": -3.0, "hi": -1.5}, "bbz_exit": {"kind": "float", "lo": -0.5, "hi": 0.5},
            "vol_ceiling": {"kind": "float", "lo": 0.03, "hi": 0.12},
            "stop": {"kind": "float", "lo": 0.05, "hi": 0.15}, "tp": {"kind": "float", "lo": 0.06, "hi": 0.25},
            "time_stop": {"kind": "int", "lo": 4, "hi": 12, "step": 1},
        },
    },
    {
        "name": "ADX trend-follow (strong-trend continuation)",
        "rationale": "When ADX is high the market is trending, not chopping; entering with positive medium-term return rides the trend that ADX confirms is real. Trend-following is the opposite bet to the reversion specs, so the cohort spans both regimes. Disconfirmer: exits when ADX collapses (trend dies) before the stop.",
        "catalyst": "confirmed strong trend with positive momentum",
        "universe": _u(), "horizon": {"bar_size": "1d", "min_hold_days": 3, "max_hold_days": 20},
        "entry": [
            {"feature": {"name": "adx"}, "op": "gt", "threshold": {"param": "adx_floor"}},
            {"feature": {"name": "ret_Nd", "lookback": {"param": "mom_lb"}}, "op": "gt", "threshold": {"param": "mom_floor"}},
        ],
        "exit": {"stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"}, "time_stop_days": {"param": "time_stop"},
                 "signal_exits": [{"feature": {"name": "adx"}, "op": "lt", "threshold": {"param": "adx_exit"}}]},
        "risk": _risk(),
        "param_space": {
            "adx_floor": {"kind": "float", "lo": 20, "hi": 35}, "adx_exit": {"kind": "float", "lo": 12, "hi": 20},
            "mom_lb": {"kind": "int", "lo": 14, "hi": 40, "step": 1}, "mom_floor": {"kind": "float", "lo": 0.0, "hi": 0.08},
            "stop": {"kind": "float", "lo": 0.06, "hi": 0.18}, "tp": {"kind": "float", "lo": 0.10, "hi": 0.40},
            "time_stop": {"kind": "int", "lo": 8, "hi": 25, "step": 1},
        },
    },
    {
        "name": "Dual-timeframe momentum confirmation",
        "rationale": "Requiring BOTH a fast and a slow lookback to be positive filters out single-window noise — momentum that survives two horizons is likelier to be real persistence than a fluke. Calm-vol gate caps capacity-eating turbulence. Disconfirmer: exits when the fast leg flips negative.",
        "catalyst": "momentum aligned across two horizons",
        "universe": _u(), "horizon": {"bar_size": "1d", "min_hold_days": 3, "max_hold_days": 14},
        "entry": [
            {"feature": {"name": "ret_Nd", "lookback": {"param": "fast_lb"}}, "op": "gt", "threshold": {"param": "fast_floor"}},
            {"feature": {"name": "ret_Nd", "lookback": {"param": "slow_lb"}}, "op": "gt", "threshold": {"param": "slow_floor"}},
            {"feature": {"name": "vol_realized"}, "op": "lt", "threshold": {"param": "vol_ceiling"}},
        ],
        "exit": {"stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"}, "time_stop_days": {"param": "time_stop"},
                 "signal_exits": [{"feature": {"name": "ret_Nd", "lookback": {"param": "fast_lb"}}, "op": "lt", "threshold": {"param": "fast_exit"}}]},
        "risk": _risk(),
        "param_space": {
            "fast_lb": {"kind": "int", "lo": 5, "hi": 15, "step": 1}, "fast_floor": {"kind": "float", "lo": 0.0, "hi": 0.06},
            "slow_lb": {"kind": "int", "lo": 30, "hi": 90, "step": 1}, "slow_floor": {"kind": "float", "lo": 0.0, "hi": 0.10},
            "fast_exit": {"kind": "float", "lo": -0.06, "hi": 0.0}, "vol_ceiling": {"kind": "float", "lo": 0.03, "hi": 0.12},
            "stop": {"kind": "float", "lo": 0.05, "hi": 0.15}, "tp": {"kind": "float", "lo": 0.08, "hi": 0.30},
            "time_stop": {"kind": "int", "lo": 6, "hi": 18, "step": 1},
        },
    },
    {
        "name": "Funding-reset reversion (uncrowded oversold)",
        "rationale": "When perp funding is low/negative shorts are paying longs — positioning is uncrowded, the opposite of a frothy top. Pairing that with an oversold RSI buys reversion precisely when leverage is NOT crowded against us (the trap a naive dip-buy walks into). Disconfirmer: exits when RSI normalizes.",
        "catalyst": "oversold price while perp funding is uncrowded",
        "universe": _u(), "horizon": {"bar_size": "1d", "min_hold_days": 2, "max_hold_days": 10},
        "entry": [
            {"feature": {"name": "rsi"}, "op": "lt", "threshold": {"param": "rsi_floor"}},
            {"feature": {"name": "funding_rate"}, "op": "lt", "threshold": {"param": "funding_ceiling"}},
        ],
        "exit": {"stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"}, "time_stop_days": {"param": "time_stop"},
                 "signal_exits": [{"feature": {"name": "rsi"}, "op": "gt", "threshold": {"param": "rsi_exit"}}]},
        "risk": _risk(),
        "param_space": {
            "rsi_floor": {"kind": "float", "lo": 20, "hi": 38}, "rsi_exit": {"kind": "float", "lo": 52, "hi": 70},
            "funding_ceiling": {"kind": "float", "lo": 0.0, "hi": 0.005},
            "stop": {"kind": "float", "lo": 0.05, "hi": 0.15}, "tp": {"kind": "float", "lo": 0.06, "hi": 0.25},
            "time_stop": {"kind": "int", "lo": 4, "hi": 12, "step": 1},
        },
    },
    {
        "name": "Volatility-expansion momentum breakout",
        "rationale": "A short-horizon return surge that coincides with a rising-but-bounded realized vol is an early breakout — momentum igniting before the move is crowded, while the vol band keeps us out of blow-off tops. Disconfirmer: time-stop + a momentum-fade signal exit close it if the breakout stalls.",
        "catalyst": "early breakout: momentum surge with expanding (not extreme) vol",
        "universe": _u(), "horizon": {"bar_size": "4h", "min_hold_days": 1, "max_hold_days": 6},
        "entry": [
            {"feature": {"name": "ret_Nd", "lookback": {"param": "bo_lb"}}, "op": "gt", "threshold": {"param": "bo_floor"}},
            {"feature": {"name": "vol_realized"}, "op": "gt", "threshold": {"param": "vol_floor"}},
            {"feature": {"name": "vol_realized"}, "op": "lt", "threshold": {"param": "vol_ceiling"}},
        ],
        "exit": {"stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"}, "time_stop_days": {"param": "time_stop"},
                 "signal_exits": [{"feature": {"name": "ret_Nd", "lookback": {"param": "bo_lb"}}, "op": "lt", "threshold": {"param": "bo_exit"}}]},
        "risk": _risk(maxpos=5, pct=0.2, conv=0.5),
        "param_space": {
            "bo_lb": {"kind": "int", "lo": 3, "hi": 10, "step": 1}, "bo_floor": {"kind": "float", "lo": 0.03, "hi": 0.15},
            "bo_exit": {"kind": "float", "lo": -0.04, "hi": 0.01},
            "vol_floor": {"kind": "float", "lo": 0.02, "hi": 0.05}, "vol_ceiling": {"kind": "float", "lo": 0.08, "hi": 0.20},
            "stop": {"kind": "float", "lo": 0.04, "hi": 0.12}, "tp": {"kind": "float", "lo": 0.06, "hi": 0.25},
            "time_stop": {"kind": "int", "lo": 2, "hi": 8, "step": 1},
        },
    },
    {
        "name": "Fear & Greed contrarian (buy extreme fear)",
        "rationale": "At sentiment extremes the crowd is wrong at the swing horizon — extreme fear marks washed-out positioning that mean-reverts. A medium-term trend floor avoids catching a structural downtrend. NOTE: needs the fear_greed feed ingested to fire; queued until then. Disconfirmer: exits when sentiment swings back to greed.",
        "catalyst": "extreme crowd fear in a non-broken trend",
        "universe": _u(), "horizon": {"bar_size": "1d", "min_hold_days": 3, "max_hold_days": 15},
        "entry": [
            {"feature": {"name": "fear_greed"}, "op": "lt", "threshold": {"param": "fear_floor"}},
            {"feature": {"name": "ret_Nd", "lookback": {"param": "trend_lb"}}, "op": "gt", "threshold": {"param": "trend_floor"}},
        ],
        "exit": {"stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"}, "time_stop_days": {"param": "time_stop"},
                 "signal_exits": [{"feature": {"name": "fear_greed"}, "op": "gt", "threshold": {"param": "greed_exit"}}]},
        "risk": _risk(),
        "param_space": {
            "fear_floor": {"kind": "float", "lo": 10, "hi": 30}, "greed_exit": {"kind": "float", "lo": 55, "hi": 80},
            "trend_lb": {"kind": "int", "lo": 40, "hi": 120, "step": 1}, "trend_floor": {"kind": "float", "lo": -0.05, "hi": 0.03},
            "stop": {"kind": "float", "lo": 0.06, "hi": 0.18}, "tp": {"kind": "float", "lo": 0.10, "hi": 0.35},
            "time_stop": {"kind": "int", "lo": 6, "hi": 20, "step": 1},
        },
    },
    {
        "name": "Liquidation-cascade reversal",
        "rationale": "A spike in total long+short liquidations marks forced deleveraging that overshoots — the cascade exhausts sellers and price snaps back at the swing horizon. Calm-after-the-storm vol gate avoids buying mid-cascade. NOTE: needs the liquidation_cascade feed ingested to fire; queued until then. Disconfirmer: time-stop closes it if the bounce never comes.",
        "catalyst": "post-liquidation-cascade exhaustion bounce",
        "universe": _u(), "horizon": {"bar_size": "4h", "min_hold_days": 1, "max_hold_days": 7},
        "entry": [
            {"feature": {"name": "liquidation_cascade"}, "op": "gt", "threshold": {"param": "cascade_floor"}},
            {"feature": {"name": "rsi"}, "op": "lt", "threshold": {"param": "rsi_floor"}},
        ],
        "exit": {"stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"}, "time_stop_days": {"param": "time_stop"},
                 "signal_exits": [{"feature": {"name": "rsi"}, "op": "gt", "threshold": {"param": "rsi_exit"}}]},
        "risk": _risk(),
        "param_space": {
            "cascade_floor": {"kind": "float", "lo": 1.5, "hi": 3.5}, "rsi_floor": {"kind": "float", "lo": 20, "hi": 40},
            "rsi_exit": {"kind": "float", "lo": 50, "hi": 68},
            "stop": {"kind": "float", "lo": 0.05, "hi": 0.15}, "tp": {"kind": "float", "lo": 0.06, "hi": 0.22},
            "time_stop": {"kind": "int", "lo": 2, "hi": 9, "step": 1},
        },
    },
]


def slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name]
    s = "".join(keep)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")[:48]


def main() -> int:
    write = "--write" in sys.argv
    ok, fail = 0, 0
    for d in SPECS:
        try:
            spec = StrategySpec.model_validate(d)
            compile_spec(spec, fit_params(spec))  # runs static_check (no magic numbers, valid features) + compiles
        except Exception as exc:  # noqa: BLE001 — report and continue so one bad spec doesn't hide the rest
            fail += 1
            print(f"FAIL  {d['name']}\n      {type(exc).__name__}: {exc}")
            continue
        ok += 1
        if write:
            path = INBOX / f"{slug(d['name'])}.json"
            path.write_text(json.dumps(d, indent=2) + "\n")
            print(f"PASS  {d['name']}  ->  {path.relative_to(INBOX.parents[1])}")
        else:
            print(f"PASS  {d['name']}  (dry run)")
    print(f"\n{ok} valid, {fail} invalid" + ("" if write else "  — re-run with --write to author"))
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
