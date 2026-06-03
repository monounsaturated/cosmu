---
name: scan-signals
description: Run an unbiased cross-asset signal sweep — turn raw data sources into testable hypotheses (each with a disconfirmer) and hand them to the Gate. Propose-only; never moves money. Use to discover new edges to try.
---

# scan-signals

A breadth-first sweep over the wired data sources that proposes **testable hypotheses with explicit disconfirmers**, then routes them to the deterministic Gate. The bus is read/propose-only — discovery never executes or sizes anything.

## When to use
"What should we try next?" — generating fresh, falsifiable hypotheses from the data we already ingest.

## Steps
1. **Inventory live sources** from `cosmu/config/feature_registry.py` + `cosmu/ingest/run.py`: which features have fresh point-in-time data (funding, fear/greed, macro/FRED, put-call, liquidations, DeFi TVL, Polymarket odds, OSINT, social).
2. **Propose hypotheses** on the read-only research bus (`cosmu/lab/tools/`): each is `{signal, asset/class, direction, economic why, DISCONFIRMER}`. The disconfirmer is mandatory — a hypothesis you can't kill isn't a hypothesis.
3. **Cross-asset framing:** prefer leading/cross-asset signals (prediction-market odds → crypto, funding → equity, macro → all) over same-asset price patterns — that's where free-data edge survives.
4. **Hand to the Gate:** turn the surviving hypotheses into `StrategySpec`s (use the create-strategy skill) and run-gate. The Gate disposes; this skill only proposes.

## Invariants
- Propose-only. Tools live on `lab/tools/` (read-only); execution is NEVER on the bus.
- Every hypothesis carries a disconfirmer and an economic prior — no data-mined patterns without a "why".
- Offline-safe: with no keys, paid sources return empty and the sweep degrades to free sources.

## Verify
- `cd apps/engine && python3 -m pytest tests/test_lab_research_tools.py tests/test_data_research_loop.py -q`
