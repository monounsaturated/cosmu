---
name: run-gate
description: Run the deterministic edge Gate (single-signal or cross-asset ablation) on real data and report the stop-or-go verdict. Use to check whether a signal/strategy has a real, exploitable edge after costs.
---

# run-gate

The Gate is the **deterministic** stop-or-go judge — out of any LLM path. It decides what gets *money*, never what gets *tried*. It is intentionally Binance-spot-priced (fees derived from the catalog, one source of truth).

## When to use
"Is this edge real?" — before funding anything, or to sanity-check a hypothesis.

## Steps
1. **Single-signal gate:** `POST /research/gate` → `GateVerdictResponse` (decision PASS/STOP, deflated-Sharpe prob, CSCV-PBO, regimes positive, buy-and-hold comparison, attempts). Logic in `cosmu/research/gate.py:evaluate_gate`.
2. **Cross-asset ablation:** `POST /research/cross-asset-gate` → `CrossAssetVerdict` — the four-arm test (price-only vs single-alt vs cross-asset) + drop-one source/class attribution. This is what proves an aggregation edge, not a single-feature fluke.
3. **Read the bar:** the verdict carries the preregistered bar it was judged against (`research/gate.py:PREREGISTERED_BAR`): min trades, max drawdown, untouched holdout, multiple-testing correction.
4. **Honest data source:** the verdict reports `data_source` ("live" vs "synthetic"). Synthetic fixtures are CI-only — never present them as a real result.

## Invariants
- The Gate makes ZERO LLM calls. The scorer/money path are deterministic.
- A PASS authorizes *funding eligibility*; live still needs all 5 interlocks.

## Verify
- `cd apps/engine && python3 -m pytest tests/test_cross_asset_gate.py tests/test_cross_asset_gate_api.py tests/test_wall_and_gate.py -q`
