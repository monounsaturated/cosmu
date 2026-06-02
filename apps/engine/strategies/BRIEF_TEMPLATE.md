# Cosmu Strategy Brief

> Upload this file to **any** LLM (Claude, ChatGPT, local models). Describe your thesis. Get back a valid `StrategySpec` JSON to drop in `strategies/inbox/`.

A **StrategySpec** is a typed hypothesis — it declares *what* to look for and *how to search*, but never hardcodes a threshold. The deterministic gate scores it honestly; the LLM never touches the money path.

---

## Feature vocabulary

Every `entry` condition references a feature from this list. Each has a stated prior (the hypothesis for why it should work). Use features that match your thesis.

### Crypto

| Feature | Prior |
|---------|-------|
| `funding_rate` | Funding extremes proxy crowded leverage; used as a long filter (spot, long-only). |
| `fear_greed` | Crowd fear mean-reverts at swing horizon — buy fear, fade greed. |
| `news_sentiment` | A positive news-flow shift precedes multi-day continuation before it is fully priced. |
| `open_interest` | OI changes reveal leverage build-up. |
| `perp_spot_basis` | Basis captures risk appetite and carry. |
| `exchange_netflow` | Net inflows can precede sell pressure. |
| `liquidation_cascade` | Spike in long+short liquidations marks forced deleveraging that overshoots — mean-reverts at swing. |
| `defi_tvl` | DeFi TVL flows indicate risk appetite and liquidity across crypto protocols. |

### Cross-asset (crypto + equity)

| Feature | Prior |
|---------|-------|
| `pm_risk_on` | Prediction-market odds on macro/risk events price the risk regime before any single asset. |
| `xasset_risk_appetite` | Crypto perp funding is a fast 24/7 read on speculative risk appetite that leads slower equity/macro signals. |
| `macro_regime` | Macro regime (curve slope, real rates, liquidity) conditions risk premia across every asset class. |
| `vix_level` | VIX measures implied volatility; extremes signal regime shifts and mean-revert at swing horizon. |
| `fed_funds_rate` | Federal funds rate changes drive risk premia across all asset classes. |
| `vix_term_slope` | Term slope encodes risk regime. |
| `dxy` | Dollar strength changes risk appetite. |
| `cftc_net_positioning` | Crowded positioning can unwind. |
| `osint_air_activity` | Aircraft activity as crude macro risk-appetite proxy (low-confidence, must earn its place via OOS). |

### Equity

| Feature | Prior |
|---------|-------|
| `putcall_ratio` | Sentiment extremes mean-revert at swing horizon. |
| `yield_curve_2s10s` | Curve slope tracks macro regime. |
| `credit_spread` | Credit stress drives equity risk premia. |
| `days_to_earnings` | Earnings windows alter drift and volatility. |
| `insider_buy_ratio` | Insider buying can signal undervaluation. |
| `short_interest_ratio` | High short interest can fuel squeezes. |

### Price-derived (all asset classes)

| Feature | Prior |
|---------|-------|
| `ret_Nd` | Medium-term return captures momentum/reversal. |
| `atr` | ATR normalizes risk and stop distance. |
| `rsi` | RSI captures overextension. |
| `adx` | ADX separates trend from chop. |
| `bb_z` | Band z-score captures statistically unusual price. |
| `vol_realized` | Realized vol gates capacity and risk. |

### Prediction markets

| Feature | Prior |
|---------|-------|
| `pm_implied_prob` | Odds are a cross-market probability signal. |
| `pm_prob_velocity` | Probability repricing speed identifies changing beliefs. |
| `pm_book_depth` | Depth defines fillable capacity. |

---

## Composable modules (optional)

Layer these onto any strategy via the `setup` and `exit.plan` fields. All thresholds must be ParamRefs.

| Module | Field | What it does |
|--------|-------|-------------|
| **MA trend filter** | `setup.ma_trend_filter` | Only enter when price is above its MA (long-only regime gate). |
| **Opening range breakout** | `setup.orb` | Enter on an upside break of the opening range. `anchor`: `"session"` or `"rolling"`. |
| **Fair value gap** | `setup.fvg` | Enter on a bullish FVG retest; `max_retests` caps re-entries. |
| **Multi-TP exit** | `exit.plan.multi_tp` | Take profit in legs (partial exits) instead of all-or-nothing. |
| **Break-even stop** | `exit.plan.break_even_after_tp1` | Move stop to entry after TP1 fills — frees the runner. |
| **Runner trail** | `exit.plan.runner_trail` | Trailing stop on the remaining position after break-even. |

---

## Rules

1. **No hardcoded numbers.** Every threshold in `entry`, `exit`, and `setup` must be a `ParamRef` pointing to a named key in `param_space`. The optimizer fits them.
2. **SL + TP required.** `exit.stop_loss` and `exit.take_profit` are mandatory ParamRefs.
3. **Features must be from the list above.** Unknown features will be rejected by the static checker.
4. **`param_space` ranges must be sensible.** `lo < hi`, `step` for ints, no degenerate single-point ranges.
5. **`min_instruments >= 5`.** The universe must be broad enough for honest cross-validation.

---

## JSON schema

```json
{
  "name": "string — short descriptive name",
  "rationale": "string — plain-language thesis (why this should work)",
  "universe": {
    "venues": ["binance", "ibkr"],
    "asset_classes": ["crypto", "equity", "prediction"],
    "min_liquidity_usd": 5000000,
    "min_instruments": 5
  },
  "horizon": {
    "bar_size": "1h | 4h | 1d",
    "min_hold_days": 2,
    "max_hold_days": 14
  },
  "catalyst": "optional string — what event/regime triggers this",
  "entry": [
    {
      "feature": {"name": "feature_name", "lookback": {"param": "param_name"}},
      "op": "gt | gte | lt | lte | cross_up | cross_down | between",
      "threshold": {"param": "param_name"}
    }
  ],
  "exit": {
    "stop_loss": {"param": "stop"},
    "take_profit": {"param": "take"},
    "time_stop_days": {"param": "time_stop"},
    "signal_exits": [],
    "plan": {
      "multi_tp": [{"at": {"param": "tp1_at"}, "size_pct": {"param": "tp1_size"}}],
      "break_even_after_tp1": false,
      "runner_trail": {"param": "runner_trail"}
    }
  },
  "risk": {
    "max_concurrent_positions": 3,
    "max_position_pct": 0.04,
    "conviction": 0.5
  },
  "param_space": {
    "param_name": {"kind": "int | float | choice", "lo": 0, "hi": 100, "step": 1}
  },
  "setup": {
    "ma_trend_filter": {"ma_lookback": {"param": "ma_lookback"}},
    "orb": {"range_bars": {"param": "orb_range"}, "buffer": {"param": "orb_buffer"}, "anchor": "rolling"},
    "fvg": {"max_retests": {"param": "fvg_retests"}, "gap_min": {"param": "fvg_gap_min"}}
  }
}
```

---

## Example 1: simple (Fear & Greed mean-reversion)

```json
{
  "name": "Fear-regime buy-the-dip",
  "rationale": "Extreme crowd fear combined with elevated realized vol signals washed-out selling that mean-reverts at swing horizon.",
  "universe": {
    "venues": ["binance"],
    "asset_classes": ["crypto"],
    "min_liquidity_usd": 10000000,
    "min_instruments": 5
  },
  "horizon": {"bar_size": "1d", "min_hold_days": 2, "max_hold_days": 14},
  "entry": [
    {"feature": {"name": "fear_greed"}, "op": "lt", "threshold": {"param": "fg_floor"}},
    {"feature": {"name": "vol_realized", "lookback": {"param": "vol_lookback"}}, "op": "gt", "threshold": {"param": "vol_floor"}}
  ],
  "exit": {
    "stop_loss": {"param": "stop"},
    "take_profit": {"param": "take"},
    "time_stop_days": {"param": "time_stop"}
  },
  "risk": {"max_concurrent_positions": 3, "max_position_pct": 0.04, "conviction": 0.6},
  "param_space": {
    "fg_floor": {"kind": "float", "lo": 10.0, "hi": 35.0},
    "vol_lookback": {"kind": "int", "lo": 10, "hi": 40, "step": 1},
    "vol_floor": {"kind": "float", "lo": 0.01, "hi": 0.06},
    "stop": {"kind": "float", "lo": 0.03, "hi": 0.12},
    "take": {"kind": "float", "lo": 0.05, "hi": 0.25},
    "time_stop": {"kind": "int", "lo": 3, "hi": 21, "step": 1}
  }
}
```

## Example 2: composable (ORB + FVG + multi-TP)

```json
{
  "name": "ORB + FVG-multiple with scaled exits",
  "rationale": "Upside opening-range breakout into a fair-value-gap retest, trend-filtered, scaled out in legs with a break-even runner.",
  "universe": {
    "venues": ["binance"],
    "asset_classes": ["crypto"],
    "min_liquidity_usd": 10000000,
    "min_instruments": 5
  },
  "horizon": {"bar_size": "1h", "min_hold_days": 1, "max_hold_days": 10},
  "entry": [
    {"feature": {"name": "ret_Nd", "lookback": {"param": "mom_lookback"}}, "op": "gt", "threshold": {"param": "mom_floor"}}
  ],
  "exit": {
    "stop_loss": {"param": "stop"},
    "take_profit": {"param": "take"},
    "time_stop_days": {"param": "time_stop"},
    "plan": {
      "multi_tp": [
        {"at": {"param": "tp1_at"}, "size_pct": {"param": "tp1_size"}},
        {"at": {"param": "tp2_at"}, "size_pct": {"param": "tp2_size"}}
      ],
      "break_even_after_tp1": true,
      "runner_trail": {"param": "runner_trail"}
    }
  },
  "risk": {"max_concurrent_positions": 4, "max_position_pct": 0.04, "conviction": 0.55},
  "param_space": {
    "mom_lookback": {"kind": "int", "lo": 5, "hi": 40, "step": 1},
    "mom_floor": {"kind": "float", "lo": 0.0, "hi": 0.05},
    "stop": {"kind": "float", "lo": 0.02, "hi": 0.1},
    "take": {"kind": "float", "lo": 0.04, "hi": 0.24},
    "time_stop": {"kind": "int", "lo": 2, "hi": 14, "step": 1},
    "tp1_at": {"kind": "float", "lo": 0.02, "hi": 0.08},
    "tp1_size": {"kind": "float", "lo": 0.25, "hi": 0.6},
    "tp2_at": {"kind": "float", "lo": 0.08, "hi": 0.2},
    "tp2_size": {"kind": "float", "lo": 0.2, "hi": 0.5},
    "runner_trail": {"kind": "float", "lo": 0.02, "hi": 0.1},
    "ma_lookback": {"kind": "int", "lo": 20, "hi": 100, "step": 1},
    "orb_range": {"kind": "int", "lo": 4, "hi": 24, "step": 1},
    "orb_buffer": {"kind": "float", "lo": 0.0, "hi": 0.01},
    "fvg_retests": {"kind": "int", "lo": 1, "hi": 4, "step": 1},
    "fvg_gap_min": {"kind": "float", "lo": 0.0, "hi": 0.02}
  },
  "setup": {
    "ma_trend_filter": {"ma_lookback": {"param": "ma_lookback"}},
    "orb": {"range_bars": {"param": "orb_range"}, "buffer": {"param": "orb_buffer"}, "anchor": "rolling"},
    "fvg": {"max_retests": {"param": "fvg_retests"}, "gap_min": {"param": "fvg_gap_min"}}
  }
}
```

---

## How to use

1. Upload this file to any LLM chat.
2. Describe your thesis in plain language (e.g., "I think extreme funding rates combined with liquidation cascades signal exhaustion — fade the crowd").
3. The LLM generates a StrategySpec JSON following the schema above.
4. Save the JSON as a `.json` file (or `.md` with a JSON code block) in `strategies/inbox/`.
5. The engine picks it up, screens it through the deterministic gate, and reports the verdict.
